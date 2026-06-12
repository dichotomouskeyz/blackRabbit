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
from psycopg2 import sql

from batch.reconciliation.models import _STREAM_TABLES
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


@dataclass(frozen=True, slots=True)
class ARCPostSessionResult:
    """Summary of the ARC post-session handoff."""

    session_id: str
    canonical_anchor_count: int
    cluster_count: int
    baseline_row_count: int
    baseline_window_start: float | None
    baseline_window_end: float | None


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
    sponsor_id: str | None = None,
    anchor_filters: Sequence[AnchorEventFilter] | None = None,
) -> tuple[EchoAnchorRow, ...]:
    """Load anchor-eligible ECHO rows for a session, ordered by timestamp.

    sponsor_id: tenancy guard — when provided, rows are also filtered by
    sponsor_id, so a session queried under the wrong sponsor yields no rows.
    """
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
                  AND (%s::uuid IS NULL OR sponsor_id = %s::uuid)
                  AND (event_type, zone_label) IN %s
                ORDER BY lsl_timestamp ASC, id ASC
                """,
                (session_id, sponsor_id, sponsor_id, filter_pairs),
            )
        else:
            cur.execute(
                """
                SELECT id, session_id, participant_id, site_id, sponsor_id,
                       event_type, source, actor_id, actor_role, zone_label,
                       lsl_timestamp
                FROM echo_events
                WHERE session_id = %s
                  AND (%s::uuid IS NULL OR sponsor_id = %s::uuid)
                ORDER BY lsl_timestamp ASC, id ASC
                """,
                (session_id, sponsor_id, sponsor_id),
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
    sponsor_id: str | None = None,
    anchor_filters: Sequence[AnchorEventFilter] | None = None,
    debounce_gap_s: float = DEFAULT_ECHO_CLUSTER_DEBOUNCE_S,
) -> tuple[EchoAnchorCluster, ...]:
    """Load clustered ARC anchor candidates for a session."""
    rows = load_echo_anchor_rows(conn, session_id, sponsor_id, anchor_filters=anchor_filters)
    return cluster_echo_anchor_rows(rows, debounce_gap_s=debounce_gap_s)


def load_canonical_echo_anchors(
    conn: psycopg2.extensions.connection,
    session_id: str,
    sponsor_id: str | None = None,
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
    conn: psycopg2.extensions.connection,
    session_id: str,
) -> tuple[SessionBaselineRow, ...]:
    """Load persisted ARC baselines for a session."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT session_id, participant_id, site_id, sponsor_id,
                   modality, signal_component, baseline_mean, baseline_std,
                   baseline_window_start, baseline_window_end, sample_count
            FROM session_baselines
            WHERE session_id = %s
            ORDER BY modality, signal_component
            """,
            (session_id,),
        )
        rows = cur.fetchall()

    return tuple(
        SessionBaselineRow(
            session_id=str(row[0]),
            participant_id=str(row[1]),
            site_id=str(row[2]),
            sponsor_id=str(row[3]),
            modality=str(row[4]),
            signal_component=str(row[5]),
            baseline_mean=float(row[6]),
            baseline_std=float(row[7]),
            baseline_window_start=float(row[8]),
            baseline_window_end=float(row[9]),
            sample_count=int(row[10]),
        )
        for row in rows
    )


def upsert_session_baselines(
    conn: psycopg2.extensions.connection,
    rows: Sequence[SessionBaselineRow],
) -> None:
    """Persist ARC baselines with idempotent upsert semantics."""
    if not rows:
        return

    with conn.cursor() as cur:
        for row in rows:
            cur.execute(
                """
                INSERT INTO session_baselines (
                    session_id, participant_id, site_id, sponsor_id, modality,
                    signal_component, baseline_mean, baseline_std,
                    baseline_window_start, baseline_window_end, sample_count
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (session_id, modality, signal_component)
                DO UPDATE SET
                    participant_id = EXCLUDED.participant_id,
                    site_id = EXCLUDED.site_id,
                    sponsor_id = EXCLUDED.sponsor_id,
                    baseline_mean = EXCLUDED.baseline_mean,
                    baseline_std = EXCLUDED.baseline_std,
                    baseline_window_start = EXCLUDED.baseline_window_start,
                    baseline_window_end = EXCLUDED.baseline_window_end,
                    sample_count = EXCLUDED.sample_count
                """,
                (
                    row.session_id,
                    row.participant_id,
                    row.site_id,
                    row.sponsor_id,
                    row.modality,
                    row.signal_component,
                    row.baseline_mean,
                    row.baseline_std,
                    row.baseline_window_start,
                    row.baseline_window_end,
                    row.sample_count,
                ),
            )


def _query_session_meta(
    conn: psycopg2.extensions.connection,
    session_id: str,
    sponsor_id: str | None = None,
) -> tuple[str, str, str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT participant_id, site_id, sponsor_id FROM sessions
            WHERE id = %s
            AND (%s::uuid IS NULL OR sponsor_id = %s::uuid)
            """,
            (session_id, sponsor_id, sponsor_id),
        )
        row = cur.fetchone()
    if not row:
        raise RuntimeError(f"session {session_id} not found in sessions table")
    return str(row[0]), str(row[1]), str(row[2])


def _query_biosignal_window_start(
    conn: psycopg2.extensions.connection,
    session_id: str,
) -> float | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT MIN(min_lsl_timestamp)
            FROM (
                SELECT MIN(lsl_timestamp) AS min_lsl_timestamp
                FROM eeg_samples
                WHERE session_id = %s
                UNION ALL
                SELECT MIN(lsl_timestamp) AS min_lsl_timestamp
                FROM hrv_samples
                WHERE session_id = %s
                UNION ALL
                SELECT MIN(lsl_timestamp) AS min_lsl_timestamp
                FROM eda_samples
                WHERE session_id = %s
                UNION ALL
                SELECT MIN(lsl_timestamp) AS min_lsl_timestamp
                FROM respiration_samples
                WHERE session_id = %s
            ) bounds
            """,
            (session_id, session_id, session_id, session_id),
        )
        row = cur.fetchone()
    if not row or row[0] is None:
        return None
    return float(row[0])


def _query_biosignal_count(
    conn: psycopg2.extensions.connection,
    table_name: str,
    session_id: str,
    start_lsl_timestamp: float,
    end_lsl_timestamp: float,
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL(
                """
            SELECT COUNT(*)
            FROM {table_name}
            WHERE session_id = %s
              AND lsl_timestamp >= %s
              AND lsl_timestamp < %s
            """
            ).format(table_name=sql.Identifier(table_name)),
            (session_id, start_lsl_timestamp, end_lsl_timestamp),
        )
        row = cur.fetchone()
    return int(row[0]) if row else 0


def _query_scalar_stats(
    conn: psycopg2.extensions.connection,
    sql_query: str,
    params: tuple,
) -> tuple[float, float, int]:
    with conn.cursor() as cur:
        cur.execute(sql_query, params)
        row = cur.fetchone()
    if not row:
        return 0.0, 0.0, 0
    sample_count = int(row[0]) if row[0] is not None else 0
    mean = float(row[1]) if row[1] is not None else 0.0
    std = float(row[2]) if row[2] is not None else 0.0
    return mean, std, sample_count


def _query_eeg_proxy_stats(
    conn: psycopg2.extensions.connection,
    session_id: str,
    start_lsl_timestamp: float,
    end_lsl_timestamp: float,
) -> tuple[float, float, int]:
    return _query_scalar_stats(
        conn,
        """
        SELECT
            COUNT(*),
            AVG(ABS(voltage)),
            COALESCE(STDDEV_SAMP(ABS(voltage)), 0.0)
        FROM eeg_samples
        WHERE session_id = %s
          AND lsl_timestamp >= %s
          AND lsl_timestamp < %s
        """,
        (session_id, start_lsl_timestamp, end_lsl_timestamp),
    )


def _query_hrv_rmssd_stats(
    conn: psycopg2.extensions.connection,
    session_id: str,
    start_lsl_timestamp: float,
    end_lsl_timestamp: float,
) -> tuple[float, float, int]:
    return _query_scalar_stats(
        conn,
        """
        WITH ordered AS (
            SELECT
                rr_interval_ms,
                LAG(rr_interval_ms) OVER (ORDER BY lsl_timestamp, sample_index) AS prev_rr
            FROM hrv_samples
            WHERE session_id = %s
              AND lsl_timestamp >= %s
              AND lsl_timestamp < %s
        ),
        diffs AS (
            SELECT POWER(rr_interval_ms - prev_rr, 2) AS squared_diff
            FROM ordered
            WHERE prev_rr IS NOT NULL
        )
        SELECT
            COUNT(*),
            COALESCE(SQRT(AVG(squared_diff)), 0.0),
            COALESCE(STDDEV_SAMP(squared_diff), 0.0)
        FROM diffs
        """,
        (session_id, start_lsl_timestamp, end_lsl_timestamp),
    )


def _query_hrv_scalar_stats(
    conn: psycopg2.extensions.connection,
    session_id: str,
    start_lsl_timestamp: float,
    end_lsl_timestamp: float,
) -> tuple[float, float, int]:
    return _query_scalar_stats(
        conn,
        """
        SELECT
            COUNT(*),
            AVG(rr_interval_ms),
            COALESCE(STDDEV_SAMP(rr_interval_ms), 0.0)
        FROM hrv_samples
        WHERE session_id = %s
          AND lsl_timestamp >= %s
          AND lsl_timestamp < %s
        """,
        (session_id, start_lsl_timestamp, end_lsl_timestamp),
    )


def _query_hrv_bpm_stats(
    conn: psycopg2.extensions.connection,
    session_id: str,
    start_lsl_timestamp: float,
    end_lsl_timestamp: float,
) -> tuple[float, float, int]:
    return _query_scalar_stats(
        conn,
        """
        SELECT
            COUNT(*),
            AVG(COALESCE(heart_rate_bpm, 60000.0 / NULLIF(rr_interval_ms, 0.0))),
            COALESCE(
                STDDEV_SAMP(COALESCE(heart_rate_bpm, 60000.0 / NULLIF(rr_interval_ms, 0.0))),
                0.0
            )
        FROM hrv_samples
        WHERE session_id = %s
          AND lsl_timestamp >= %s
          AND lsl_timestamp < %s
        """,
        (session_id, start_lsl_timestamp, end_lsl_timestamp),
    )


def _query_eda_mean_stats(
    conn: psycopg2.extensions.connection,
    session_id: str,
    start_lsl_timestamp: float,
    end_lsl_timestamp: float,
) -> tuple[float, float, int]:
    return _query_scalar_stats(
        conn,
        """
        SELECT
            COUNT(*),
            AVG(conductance_us),
            COALESCE(STDDEV_SAMP(conductance_us), 0.0)
        FROM eda_samples
        WHERE session_id = %s
          AND lsl_timestamp >= %s
          AND lsl_timestamp < %s
        """,
        (session_id, start_lsl_timestamp, end_lsl_timestamp),
    )


def _query_eda_scr_stats(
    conn: psycopg2.extensions.connection,
    session_id: str,
    start_lsl_timestamp: float,
    end_lsl_timestamp: float,
) -> tuple[float, float, int]:
    return _query_scalar_stats(
        conn,
        """
        WITH ordered AS (
            SELECT
                conductance_us,
                LAG(conductance_us) OVER (ORDER BY lsl_timestamp, sample_index) AS prev_conductance
            FROM eda_samples
            WHERE session_id = %s
              AND lsl_timestamp >= %s
              AND lsl_timestamp < %s
        ),
        deltas AS (
            SELECT
                CASE
                    WHEN prev_conductance IS NOT NULL AND conductance_us - prev_conductance > 0.1
                    THEN 1.0
                    ELSE 0.0
                END AS scr_indicator
            FROM ordered
        )
        SELECT
            COUNT(*),
            AVG(scr_indicator),
            COALESCE(STDDEV_SAMP(scr_indicator), 0.0)
        FROM deltas
        """,
        (session_id, start_lsl_timestamp, end_lsl_timestamp),
    )


def _query_respiration_rate_stats(
    conn: psycopg2.extensions.connection,
    session_id: str,
    start_lsl_timestamp: float,
    end_lsl_timestamp: float,
) -> tuple[float, float, int]:
    return _query_scalar_stats(
        conn,
        """
        SELECT
            COUNT(*),
            AVG(COALESCE(breaths_per_min, 60.0 / NULLIF(raw_amplitude, 0.0))),
            COALESCE(
                STDDEV_SAMP(COALESCE(breaths_per_min, 60.0 / NULLIF(raw_amplitude, 0.0))),
                0.0
            )
        FROM respiration_samples
        WHERE session_id = %s
          AND lsl_timestamp >= %s
          AND lsl_timestamp < %s
        """,
        (session_id, start_lsl_timestamp, end_lsl_timestamp),
    )


def _query_respiration_amplitude_stats(
    conn: psycopg2.extensions.connection,
    session_id: str,
    start_lsl_timestamp: float,
    end_lsl_timestamp: float,
) -> tuple[float, float, int]:
    return _query_scalar_stats(
        conn,
        """
        SELECT
            COUNT(*),
            AVG(processed_amplitude),
            COALESCE(STDDEV_SAMP(processed_amplitude), 0.0)
        FROM respiration_samples
        WHERE session_id = %s
          AND lsl_timestamp >= %s
          AND lsl_timestamp < %s
        """,
        (session_id, start_lsl_timestamp, end_lsl_timestamp),
    )


def _build_baseline_row(
    session_id: str,
    participant_id: str,
    site_id: str,
    sponsor_id: str,
    modality: str,
    signal_component: str,
    stats: tuple[float, float, int],
    start_lsl_timestamp: float,
    end_lsl_timestamp: float,
) -> SessionBaselineRow | None:
    baseline_mean, baseline_std, sample_count = stats
    if sample_count <= 0:
        return None
    return SessionBaselineRow(
        session_id=session_id,
        participant_id=participant_id,
        site_id=site_id,
        sponsor_id=sponsor_id,
        modality=modality,
        signal_component=signal_component,
        baseline_mean=baseline_mean,
        baseline_std=baseline_std,
        baseline_window_start=start_lsl_timestamp,
        baseline_window_end=end_lsl_timestamp,
        sample_count=sample_count,
    )


def compute_session_baseline_rows(
    conn: psycopg2.extensions.connection,
    session_id: str,
    sponsor_id: str | None = None,
    config_path: str | None = None,
) -> tuple[SessionBaselineRow, ...]:
    """Compute ARC baselines from raw biosignal tables."""
    config = load_arc_watchdog_config(config_path)
    participant_id, site_id, sponsor_id = _query_session_meta(conn, session_id, sponsor_id)
    baseline_start = _query_biosignal_window_start(conn, session_id)
    if baseline_start is None:
        return ()

    baseline_end = baseline_start + float(config.raw["baseline"]["window_duration_s"])
    counts = {
        modality: _query_biosignal_count(
            conn,
            _STREAM_TABLES[stream_name],
            session_id,
            baseline_start,
            baseline_end,
        )
        for modality, stream_name in (
            ("eeg", "EEG"),
            ("hrv", "HRV"),
            ("eda", "EDA"),
            ("respiration", "Respiration"),
        )
    }
    total_rows = sum(counts.values())
    if total_rows == 0:
        return ()

    min_counts = config.raw["baseline"]["min_sample_count"]
    for modality, count in counts.items():
        if count < int(min_counts[modality]):
            raise RuntimeError(
                f"baseline minimum sample count not met for {modality}: "
                f"{count} < {int(min_counts[modality])}"
            )

    rows: list[SessionBaselineRow] = []
    signal_components = config.raw["signal_components"]

    for component in signal_components["eeg"]:
        row = _build_baseline_row(
            session_id,
            participant_id,
            site_id,
            sponsor_id,
            "eeg",
            component,
            _query_eeg_proxy_stats(conn, session_id, baseline_start, baseline_end),
            baseline_start,
            baseline_end,
        )
        if row is not None:
            rows.append(row)

    for component in signal_components["hrv"]:
        if component == "hrv_rmssd":
            stats = _query_hrv_rmssd_stats(conn, session_id, baseline_start, baseline_end)
        elif component == "hrv_sdnn":
            stats = _query_hrv_scalar_stats(conn, session_id, baseline_start, baseline_end)
        else:
            stats = _query_hrv_bpm_stats(conn, session_id, baseline_start, baseline_end)
        row = _build_baseline_row(
            session_id,
            participant_id,
            site_id,
            sponsor_id,
            "hrv",
            component,
            stats,
            baseline_start,
            baseline_end,
        )
        if row is not None:
            rows.append(row)

    for component in signal_components["eda"]:
        if component == "eda_scr_count":
            stats = _query_eda_scr_stats(conn, session_id, baseline_start, baseline_end)
        else:
            stats = _query_eda_mean_stats(conn, session_id, baseline_start, baseline_end)
        row = _build_baseline_row(
            session_id,
            participant_id,
            site_id,
            sponsor_id,
            "eda",
            component,
            stats,
            baseline_start,
            baseline_end,
        )
        if row is not None:
            rows.append(row)

    for component in signal_components["respiration"]:
        if component == "respiration_rate":
            stats = _query_respiration_rate_stats(conn, session_id, baseline_start, baseline_end)
        else:
            stats = _query_respiration_amplitude_stats(
                conn, session_id, baseline_start, baseline_end
            )
        row = _build_baseline_row(
            session_id,
            participant_id,
            site_id,
            sponsor_id,
            "respiration",
            component,
            stats,
            baseline_start,
            baseline_end,
        )
        if row is not None:
            rows.append(row)

    return tuple(rows)


def run_arc_post_session(
    conn: psycopg2.extensions.connection,
    session_id: str,
    sponsor_id: str | None = None,
    config_path: str | None = None,
    debounce_gap_s: float = DEFAULT_ECHO_CLUSTER_DEBOUNCE_S,
) -> ARCPostSessionResult:
    """Cluster ARC anchors and persist session baselines for a closed session."""
    try:
        config = load_arc_watchdog_config(config_path)
        clusters = load_echo_anchor_clusters(
            conn,
            session_id,
            sponsor_id,
            anchor_filters=config.anchor_events,
            debounce_gap_s=debounce_gap_s,
        )
        baseline_rows = compute_session_baseline_rows(
            conn,
            session_id,
            sponsor_id,
            config_path=config_path,
        )
        if baseline_rows:
            upsert_session_baselines(conn, baseline_rows)

        window_start = baseline_rows[0].baseline_window_start if baseline_rows else None
        window_end = baseline_rows[0].baseline_window_end if baseline_rows else None
        return ARCPostSessionResult(
            session_id=session_id,
            canonical_anchor_count=len(clusters),
            cluster_count=len(clusters),
            baseline_row_count=len(baseline_rows),
            baseline_window_start=window_start,
            baseline_window_end=window_end,
        )
    except ARCPostSessionError:
        raise
    except Exception as exc:  # pragma: no cover - defensive wrapping
        raise ARCPostSessionError(str(exc)) from exc
