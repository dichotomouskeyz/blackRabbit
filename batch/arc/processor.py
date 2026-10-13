"""ARC post-session processing helpers.

This module owns ARC-side anchor selection and baseline persistence helpers.
Raw ECHO rows remain immutable in ``echo_events``; ARC applies debounce
clustering only when choosing which anchors can open windows.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Sequence

import psycopg2

from config.arc_watchdog import AnchorEventFilter, load_arc_watchdog_config

DEFAULT_ECHO_CLUSTER_DEBOUNCE_S = 10.0


class ARCPostSessionError(RuntimeError):
    """Raised when ARC post-session processing cannot complete."""


@dataclass(frozen=True, slots=True)
class EchoAnchorRow:
    """One ECHO row eligible for ARC anchor selection."""

    id: int
    session_id: str
    participant_id: str
    site_id: str
    sponsor_id: str
    event_type: str
    source: str
    actor_id: str | None
    actor_role: str
    zone_label: str
    lsl_timestamp: float

    @property
    def anchor_key(self) -> tuple[str, str]:
        return self.event_type, self.zone_label


@dataclass(frozen=True, slots=True)
class EchoAnchorCluster:
    """A debounce cluster of one or more anchor-eligible ECHO rows."""

    index: int
    members: tuple[EchoAnchorRow, ...]

    def __post_init__(self) -> None:
        if not self.members:
            raise ValueError("EchoAnchorCluster requires at least one member")

    @property
    def canonical_anchor(self) -> EchoAnchorRow:
        return self.members[0]

    @property
    def start_lsl_timestamp(self) -> float:
        return self.members[0].lsl_timestamp

    @property
    def end_lsl_timestamp(self) -> float:
        return self.members[-1].lsl_timestamp

    @property
    def size(self) -> int:
        return len(self.members)


@dataclass(frozen=True, slots=True)
class SessionBaselineRow:
    """Persisted ARC baseline contract row."""

    session_id: str
    participant_id: str
    site_id: str
    sponsor_id: str
    modality: str
    signal_component: str
    baseline_mean: float
    baseline_std: float
    baseline_window_start: float
    baseline_window_end: float
    sample_count: int
    analysis_id: str = ""
    epoch_count: int = 0
    units: str = ""
    extractor_version: str = ""
    config_version: str = ""
    config_sha256: str = ""
    input_sha256: str = ""


@dataclass(frozen=True, slots=True)
class ARCPostSessionResult:
    """Summary of the ARC post-session handoff."""

    session_id: str
    canonical_anchor_count: int
    cluster_count: int
    baseline_row_count: int
    baseline_window_start: float | None
    baseline_window_end: float | None
    analysis_id: str = ""
    event_count: int = 0
    passed_event_count: int = 0
    artifact: dict | None = None


def _anchor_filter_pairs(
    anchor_filters: Sequence[AnchorEventFilter | tuple[str, str]] | None,
) -> tuple[tuple[str, str], ...] | None:
    if not anchor_filters:
        return None
    return tuple(
        (anchor.event_type, anchor.zone_label)
        if isinstance(anchor, AnchorEventFilter)
        else (anchor[0], anchor[1])
        for anchor in anchor_filters
    )


def load_echo_anchor_rows(
    conn: psycopg2.extensions.connection,
    session_id: str,
    sponsor_id: str,
    anchor_filters: Sequence[AnchorEventFilter] | None = None,
) -> tuple[EchoAnchorRow, ...]:
    """Load anchor-eligible ECHO rows for a session, ordered by timestamp.

    sponsor_id: tenancy guard — when provided, rows are also filtered by
    sponsor_id, so a session queried under the wrong sponsor yields no rows.
    """
    if not sponsor_id:
        raise ValueError("sponsor_id is required")
    with conn.cursor() as cur:
        cur.execute(
            "SELECT site_id FROM sessions WHERE id=%s AND sponsor_id=%s", (session_id, sponsor_id)
        )
        tenant = cur.fetchone()
    if not tenant:
        return ()
    site_id = str(tenant[0])
    filter_pairs = _anchor_filter_pairs(anchor_filters)

    with conn.cursor() as cur:
        if filter_pairs:
            cur.execute(
                """
                SELECT id, session_id, participant_id, site_id, sponsor_id,
                       event_type, source, actor_id, actor_role, zone_label,
                       lsl_timestamp
                FROM echo_events
                WHERE session_id = %s
                  AND sponsor_id = %s::uuid AND site_id = %s::uuid
                  AND (event_type, zone_label) IN %s
                ORDER BY lsl_timestamp ASC, id ASC
                """,
                (session_id, sponsor_id, site_id, filter_pairs),
            )
        else:
            cur.execute(
                """
                SELECT id, session_id, participant_id, site_id, sponsor_id,
                       event_type, source, actor_id, actor_role, zone_label,
                       lsl_timestamp
                FROM echo_events
                WHERE session_id = %s
                  AND sponsor_id = %s::uuid AND site_id = %s::uuid
                ORDER BY lsl_timestamp ASC, id ASC
                """,
                (session_id, sponsor_id, site_id),
            )
        rows = cur.fetchall()

    return tuple(
        EchoAnchorRow(
            id=int(row[0]),
            session_id=str(row[1]),
            participant_id=str(row[2]),
            site_id=str(row[3]),
            sponsor_id=str(row[4]),
            event_type=str(row[5]),
            source=str(row[6]),
            actor_id=None if row[7] is None else str(row[7]),
            actor_role=str(row[8]),
            zone_label=str(row[9]),
            lsl_timestamp=float(row[10]),
        )
        for row in rows
    )


def cluster_echo_anchor_rows(
    rows: Sequence[EchoAnchorRow],
    debounce_gap_s: float = DEFAULT_ECHO_CLUSTER_DEBOUNCE_S,
) -> tuple[EchoAnchorCluster, ...]:
    """Group nearby ECHO anchor rows into debounce clusters."""
    if not isfinite(debounce_gap_s) or debounce_gap_s < 0.0:
        raise ValueError("debounce_gap_s must be finite and non-negative")

    ordered = sorted(rows, key=lambda row: (row.lsl_timestamp, row.id))
    if not ordered:
        return ()

    clusters: list[EchoAnchorCluster] = []
    current: list[EchoAnchorRow] = [ordered[0]]
    previous_timestamp = ordered[0].lsl_timestamp

    for row in ordered[1:]:
        if row.lsl_timestamp - previous_timestamp <= debounce_gap_s:
            current.append(row)
        else:
            clusters.append(EchoAnchorCluster(index=len(clusters), members=tuple(current)))
            current = [row]
        previous_timestamp = row.lsl_timestamp

    clusters.append(EchoAnchorCluster(index=len(clusters), members=tuple(current)))
    return tuple(clusters)


def load_echo_anchor_clusters(
    conn: psycopg2.extensions.connection,
    session_id: str,
    sponsor_id: str,
    anchor_filters: Sequence[AnchorEventFilter] | None = None,
    debounce_gap_s: float = DEFAULT_ECHO_CLUSTER_DEBOUNCE_S,
) -> tuple[EchoAnchorCluster, ...]:
    """Load clustered ARC anchor candidates for a session."""
    rows = load_echo_anchor_rows(conn, session_id, sponsor_id, anchor_filters=anchor_filters)
    return cluster_echo_anchor_rows(rows, debounce_gap_s=debounce_gap_s)


def load_canonical_echo_anchors(
    conn: psycopg2.extensions.connection,
    session_id: str,
    sponsor_id: str,
    anchor_filters: Sequence[AnchorEventFilter] | None = None,
    debounce_gap_s: float = DEFAULT_ECHO_CLUSTER_DEBOUNCE_S,
) -> tuple[EchoAnchorRow, ...]:
    """Return the first anchor in each debounce cluster."""
    return tuple(
        cluster.canonical_anchor
        for cluster in load_echo_anchor_clusters(
            conn,
            session_id,
            sponsor_id,
            anchor_filters=anchor_filters,
            debounce_gap_s=debounce_gap_s,
        )
    )


def load_session_baselines(
    conn, session_id: str, sponsor_id: str, *, site_id: str, analysis_id: str
) -> tuple[SessionBaselineRow, ...]:
    """Load baselines only for an explicitly identified tenant and analysis run."""
    from psycopg2.extras import RealDictCursor

    if not sponsor_id or not site_id or not analysis_id:
        raise ValueError("sponsor_id, site_id and analysis_id are required")
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """SELECT session_id, participant_id, site_id, sponsor_id,
            modality, signal_component, baseline_mean, baseline_std,
            baseline_window_start, baseline_window_end, sample_count, analysis_id,
            epoch_count, units, extractor_version, config_version, config_sha256, input_sha256
            FROM session_baselines WHERE session_id=%s AND sponsor_id=%s AND site_id=%s
            AND analysis_id=%s ORDER BY modality, signal_component""",
            (session_id, sponsor_id, site_id, analysis_id),
        )
        return tuple(SessionBaselineRow(**dict(row)) for row in cur.fetchall())


def _build_baseline_row(
    session_id,
    participant_id,
    site_id,
    sponsor_id,
    modality,
    signal_component,
    stats,
    start_lsl_timestamp,
    end_lsl_timestamp,
):
    mean, std, count = stats
    if count <= 0:
        return None
    return SessionBaselineRow(
        session_id,
        participant_id,
        site_id,
        sponsor_id,
        modality,
        signal_component,
        mean,
        std,
        start_lsl_timestamp,
        end_lsl_timestamp,
        count,
    )


def compute_session_baseline_rows(conn, session_id, sponsor_id, config_path=None, *, site_id):
    """Calculate release-contract baselines after the same lifecycle/tenant gate."""
    from batch.arc.pipeline import prepare_baselines
    from batch.arc.storage import load_inputs, require_verified_session

    identity = require_verified_session(conn, session_id, sponsor_id, site_id)
    data, metadata, _, input_hash = load_inputs(conn, identity)
    config = load_arc_watchdog_config(config_path)
    _, _, baselines, _, _ = prepare_baselines(data, metadata, config)
    return tuple(
        SessionBaselineRow(**identity, **row, input_sha256=input_hash) for row in baselines
    )


def upsert_session_baselines(conn, rows):
    """Empty writes remain a no-op; analysis persistence owns all nonempty writes."""
    if rows:
        raise ValueError("Persist baseline provenance atomically using run_arc_post_session")


def run_arc_post_session(
    conn,
    session_id: str,
    sponsor_id: str,
    config_path=None,
    *,
    site_id: str,
    debounce_gap_s: float = DEFAULT_ECHO_CLUSTER_DEBOUNCE_S,
) -> ARCPostSessionResult:
    """Compute a tenant-scoped ARC artifact; caller commits or rolls back atomically."""
    from dataclasses import asdict
    from hashlib import sha256

    from batch.arc.pipeline import analyze_recording
    from batch.arc.preflight import assert_arc_temporal_alignment
    from batch.arc.storage import (
        canonical_json,
        load_inputs,
        persist_analysis,
        require_verified_session,
    )

    try:
        identity = require_verified_session(conn, session_id, sponsor_id, site_id)
        config = load_arc_watchdog_config(config_path)
        data, metadata, safety, input_hash = load_inputs(conn, identity)
        clusters = load_echo_anchor_clusters(
            conn,
            session_id,
            sponsor_id,
            anchor_filters=config.anchor_events,
            debounce_gap_s=debounce_gap_s,
        )
        anchors = [cluster.canonical_anchor for cluster in clusters]
        if not anchors:
            raise RuntimeError("no eligible ECHO anchor events")
        streams = tuple(
            {"eeg": "EEG", "hrv": "HRV", "eda": "EDA", "respiration": "Respiration"}[modality]
            for modality in sorted(data)
            if data[modality] and modality in metadata
        )
        assert_arc_temporal_alignment(
            conn,
            session_id,
            sponsor_id,
            required_streams=streams,
            anchor_filters=tuple((a.event_type, a.zone_label) for a in config.anchor_events),
            site_id=site_id,
        )
        input_hash = sha256(
            (
                input_hash + canonical_json([asdict(a) for a in anchors]) + str(debounce_gap_s)
            ).encode()
        ).hexdigest()
        artifact, baselines, ecps = analyze_recording(
            identity, data, metadata, anchors, config, input_hash, safety
        )
        persist_analysis(conn, artifact, baselines, ecps)
        return ARCPostSessionResult(
            session_id,
            len(anchors),
            len(clusters),
            len(baselines),
            baselines[0]["baseline_window_start"],
            baselines[0]["baseline_window_end"],
            artifact["analysis_id"],
            len(artifact["events"]),
            len(ecps),
            artifact,
        )
    except ARCPostSessionError:
        raise
    except Exception as exc:
        raise ARCPostSessionError(str(exc)) from exc
