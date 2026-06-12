"""Pre-ARC validation gates.

ARC processing is post-session, but it still depends on synchronized capture
time. This module verifies that ECHO anchor events and APEX physiological
streams are aligned in LSL time before any convergence profile is computed.
"""

from __future__ import annotations

from dataclasses import dataclass

import psycopg2
from psycopg2 import sql

from batch.reconciliation.models import _STREAM_TABLES

DEFAULT_MAX_ECHO_APEX_DELTA_S = 1.0


@dataclass(frozen=True, slots=True)
class APEXStreamAlignment:
    stream_name: str
    table_name: str
    sample_count: int
    first_lsl_timestamp: float | None
    last_lsl_timestamp: float | None
    max_nearest_echo_delta_s: float | None
    threshold_s: float

    @property
    def is_aligned(self) -> bool:
        return (
            self.sample_count > 0
            and self.max_nearest_echo_delta_s is not None
            and self.max_nearest_echo_delta_s < self.threshold_s
        )


@dataclass(frozen=True, slots=True)
class ARCTemporalAlignmentReport:
    session_id: str
    threshold_s: float
    echo_event_count: int
    first_echo_lsl_timestamp: float | None
    last_echo_lsl_timestamp: float | None
    streams: tuple[APEXStreamAlignment, ...] = ()

    def __post_init__(self) -> None:
        # Accept a {name: alignment} mapping or any iterable of alignments;
        # iteration over the report's streams always yields alignment objects.
        if isinstance(self.streams, dict):
            object.__setattr__(self, "streams", tuple(self.streams.values()))
        else:
            object.__setattr__(self, "streams", tuple(self.streams))

    @property
    def failed_streams(self) -> tuple[str, ...]:
        return tuple(
            s.stream_name
            for s in sorted(self.streams, key=lambda s: s.stream_name)
            if not s.is_aligned
        )

    @property
    def is_aligned(self) -> bool:
        return self.echo_event_count > 0 and not self.failed_streams

    def raise_for_unaligned(self) -> None:
        if self.is_aligned:
            return
        if self.echo_event_count == 0:
            raise RuntimeError(
                f"ARC temporal alignment failed for session {self.session_id}: "
                "no ECHO anchor events found"
            )
        raise RuntimeError(
            f"ARC temporal alignment failed for session {self.session_id}: "
            f"ECHO/APEX nearest-sample delta must be < {self.threshold_s:.3f}s; "
            f"failed streams: {', '.join(self.failed_streams)}"
        )

    def as_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "threshold_s": self.threshold_s,
            "echo_event_count": self.echo_event_count,
            "first_echo_lsl_timestamp": self.first_echo_lsl_timestamp,
            "last_echo_lsl_timestamp": self.last_echo_lsl_timestamp,
            "is_aligned": self.is_aligned,
            "failed_streams": list(self.failed_streams),
            "streams": {
                result.stream_name: {
                    "table_name": result.table_name,
                    "sample_count": result.sample_count,
                    "first_lsl_timestamp": result.first_lsl_timestamp,
                    "last_lsl_timestamp": result.last_lsl_timestamp,
                    "max_nearest_echo_delta_s": result.max_nearest_echo_delta_s,
                    "is_aligned": result.is_aligned,
                }
                for result in self.streams
            },
        }


def validate_arc_temporal_alignment(
    conn: psycopg2.extensions.connection,
    session_id: str,
    sponsor_id: str | None = None,
    threshold_s: float = DEFAULT_MAX_ECHO_APEX_DELTA_S,
    required_streams: tuple[str, ...] = tuple(_STREAM_TABLES),
    anchor_filters: tuple[tuple[str, str], ...] | None = None,
) -> ARCTemporalAlignmentReport:
    """Return ECHO/APEX timestamp alignment status for a session.

    For each required APEX stream, every ECHO anchor event is compared with the
    nearest sample timestamp from that stream. ARC is allowed to start only when
    all nearest deltas are strictly sub-threshold. The default threshold is 1.0s,
    so the effective gate is sub-second alignment.

    sponsor_id: tenancy guard — when provided, every query also filters by
        sponsor_id, so a session queried under the wrong sponsor yields zero
        ECHO events and an unaligned report.

    anchor_filters: optional sequence of (event_type, zone_label) pairs that
        restrict which echo_events count as ARC anchors. When None, all events
        in the session are counted (unfiltered). Pass config.anchor_events as
        tuples to apply the config-driven filter.
    """
    if threshold_s <= 0.0 or threshold_s > 1.0:
        raise ValueError("threshold_s must be > 0.0 and <= 1.0 for sub-second ARC gating")

    echo_count, first_echo, last_echo = _query_echo_bounds(
        conn, session_id, sponsor_id, anchor_filters
    )
    streams: list[APEXStreamAlignment] = []

    for stream_name in required_streams:
        table_name = _STREAM_TABLES[stream_name]
        sample_count, first_sample, last_sample = _query_stream_bounds(
            conn, table_name, session_id, sponsor_id
        )
        max_delta = None
        if echo_count > 0 and sample_count > 0:
            max_delta = _query_max_nearest_echo_delta(conn, table_name, session_id, sponsor_id)
        # Report stream names in lowercase modality form ('eeg', 'hrv', ...),
        # matching session_signal_metadata.modality and baseline modality keys.
        streams.append(
            APEXStreamAlignment(
                stream_name=stream_name.lower(),
                table_name=table_name,
                sample_count=sample_count,
                first_lsl_timestamp=first_sample,
                last_lsl_timestamp=last_sample,
                max_nearest_echo_delta_s=max_delta,
                threshold_s=threshold_s,
            )
        )

    return ARCTemporalAlignmentReport(
        session_id=session_id,
        threshold_s=threshold_s,
        echo_event_count=echo_count,
        first_echo_lsl_timestamp=first_echo,
        last_echo_lsl_timestamp=last_echo,
        streams=tuple(streams),
    )


def assert_arc_temporal_alignment(
    conn: psycopg2.extensions.connection,
    session_id: str,
    sponsor_id: str | None = None,
    threshold_s: float = DEFAULT_MAX_ECHO_APEX_DELTA_S,
    required_streams: tuple[str, ...] = tuple(_STREAM_TABLES),
    anchor_filters: tuple[tuple[str, str], ...] | None = None,
) -> ARCTemporalAlignmentReport:
    """Validate alignment and raise RuntimeError if ARC must not start."""
    report = validate_arc_temporal_alignment(
        conn=conn,
        session_id=session_id,
        sponsor_id=sponsor_id,
        threshold_s=threshold_s,
        required_streams=required_streams,
        anchor_filters=anchor_filters,
    )
    report.raise_for_unaligned()
    return report


def _query_echo_bounds(
    conn: psycopg2.extensions.connection,
    session_id: str,
    sponsor_id: str | None = None,
    anchor_filters: tuple[tuple[str, str], ...] | None = None,
) -> tuple[int, float | None, float | None]:
    with conn.cursor() as cur:
        if anchor_filters:
            # psycopg2 adapts a tuple-of-tuples for IN; a list would become ARRAY[...]
            filter_pairs = tuple(tuple(pair) for pair in anchor_filters)
            cur.execute(
                """
                SELECT COUNT(*), MIN(lsl_timestamp), MAX(lsl_timestamp)
                FROM echo_events
                WHERE session_id = %s
                AND (%s::uuid IS NULL OR sponsor_id = %s::uuid)
                AND (event_type, zone_label) IN %s
                """,
                (session_id, sponsor_id, sponsor_id, filter_pairs),
            )
        else:
            cur.execute(
                """
                SELECT COUNT(*), MIN(lsl_timestamp), MAX(lsl_timestamp)
                FROM echo_events
                WHERE session_id = %s
                AND (%s::uuid IS NULL OR sponsor_id = %s::uuid)
                """,
                (session_id, sponsor_id, sponsor_id),
            )
        row = cur.fetchone()
    return _coerce_bounds(row)


def _query_stream_bounds(
    conn: psycopg2.extensions.connection,
    table_name: str,
    session_id: str,
    sponsor_id: str | None = None,
) -> tuple[int, float | None, float | None]:
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL(
                """
                SELECT COUNT(*), MIN(lsl_timestamp), MAX(lsl_timestamp)
                FROM {}
                WHERE session_id = %s
                AND (%s::uuid IS NULL OR sponsor_id = %s::uuid)
                """
            ).format(sql.Identifier(table_name)),
            (session_id, sponsor_id, sponsor_id),
        )
        row = cur.fetchone()
    return _coerce_bounds(row)


def _query_max_nearest_echo_delta(
    conn: psycopg2.extensions.connection,
    table_name: str,
    session_id: str,
    sponsor_id: str | None = None,
) -> float | None:
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL(
                """
                SELECT MAX(nearest_delta_s)
                FROM (
                    SELECT ABS(nearest_sample.lsl_timestamp - echo.lsl_timestamp)
                        AS nearest_delta_s
                    FROM echo_events echo
                    CROSS JOIN LATERAL (
                        SELECT apex.lsl_timestamp
                        FROM {} apex
                        WHERE apex.session_id = %s
                        AND (%s::uuid IS NULL OR apex.sponsor_id = %s::uuid)
                        ORDER BY ABS(apex.lsl_timestamp - echo.lsl_timestamp)
                        LIMIT 1
                    ) nearest_sample
                    WHERE echo.session_id = %s
                    AND (%s::uuid IS NULL OR echo.sponsor_id = %s::uuid)
                ) nearest
                """
            ).format(sql.Identifier(table_name)),
            (session_id, sponsor_id, sponsor_id, session_id, sponsor_id, sponsor_id),
        )
        row = cur.fetchone()
    if not row or row[0] is None:
        return None
    return float(row[0])


def _coerce_bounds(row: tuple | None) -> tuple[int, float | None, float | None]:
    if not row:
        return 0, None, None
    count = int(row[0])
    first = float(row[1]) if row[1] is not None else None
    last = float(row[2]) if row[2] is not None else None
    return count, first, last
