"""Database-side helpers for reconciliation."""

from datetime import datetime, timezone
from pathlib import Path

import psycopg2
from psycopg2.extras import Json

from batch.reconciliation.models import (
    _ECHO_STREAM_NAME,
    _STREAM_TABLES,
    ReconciliationReport,
    SessionMeta,
    StreamResult,
)


def query_db_counts(conn: psycopg2.extensions.connection, session_id: str) -> dict[str, int]:
    """Return {stream_name: distinct_sample_count} from TimescaleDB/Postgres."""
    counts: dict[str, int] = {}
    cur = conn.cursor()
    for stream_name, table in _STREAM_TABLES.items():
        cur.execute(
            f"SELECT COUNT(DISTINCT sample_index) FROM {table} WHERE session_id = %s",
            (session_id,),
        )
        row = cur.fetchone()
        counts[stream_name] = int(row[0]) if row else 0
    cur.execute("SELECT COUNT(*) FROM echo_events WHERE session_id = %s", (session_id,))
    row = cur.fetchone()
    counts[_ECHO_STREAM_NAME] = int(row[0]) if row else 0
    cur.close()
    return counts


def query_max_clock_drift_s(conn: psycopg2.extensions.connection, session_id: str) -> float | None:
    """Return the max absolute LSL clock offset recorded for a session."""
    cur = conn.cursor()
    cur.execute(
        "SELECT MAX(ABS(remote_clock_offset_s)) FROM clock_drift_log WHERE session_id = %s",
        (session_id,),
    )
    row = cur.fetchone()
    cur.close()
    if not row or row[0] is None:
        return None
    return float(row[0])


def build_report(
    session_id: str,
    xdf_path: Path,
    xdf_counts: dict[str, int],
    db_counts: dict[str, int],
    max_clock_drift_s: float | None = None,
) -> ReconciliationReport:
    """Compare counts and build a ReconciliationReport."""
    all_streams = set(xdf_counts) | set(db_counts) | set(_STREAM_TABLES) | {_ECHO_STREAM_NAME}
    streams: dict[str, StreamResult] = {}

    for name in sorted(all_streams):
        xdf_n = xdf_counts.get(name, 0)
        db_n = db_counts.get(name, 0)
        streams[name] = StreamResult(xdf_count=xdf_n, db_count=db_n, gap=xdf_n - db_n)

    return ReconciliationReport(
        session_id=session_id,
        xdf_path=xdf_path,
        streams=streams,
        is_reconciled=all(r.gap == 0 for r in streams.values()),
        ran_at=datetime.now(timezone.utc).isoformat(),
        max_clock_drift_s=max_clock_drift_s,
    )


def close_session(
    conn: psycopg2.extensions.connection,
    session_id: str,
    is_reconciled: bool,
) -> None:
    """Set sessions.status and closed_at; DB trigger emits watermark event."""
    new_status = "closed" if is_reconciled else "failed"
    cur = conn.cursor()
    cur.execute(
        "UPDATE sessions SET status = %s, closed_at = NOW() WHERE id = %s",
        (new_status, session_id),
    )
    conn.commit()
    cur.close()


def write_reconciliation_log(
    conn: psycopg2.extensions.connection,
    meta: SessionMeta,
    report: ReconciliationReport,
) -> None:
    """Write an XDF reconciliation summary row into biosignal_integrity_log."""
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO biosignal_integrity_log
            (session_id, participant_id, site_id, sponsor_id, log_type,
             reconciliation_report)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (
            report.session_id,
            meta.participant_id,
            meta.site_id,
            meta.sponsor_id,
            "xdf_reconciliation",
            Json(report.as_dict()),
        ),
    )
    cur.close()


def fetch_session_meta(conn: psycopg2.extensions.connection, session_id: str) -> SessionMeta:
    """Query sessions metadata needed to reconstruct DB rows from XDF."""
    cur = conn.cursor()
    cur.execute(
        "SELECT participant_id, site_id, sponsor_id FROM sessions WHERE id = %s",
        (session_id,),
    )
    row = cur.fetchone()
    cur.close()
    if not row:
        raise RuntimeError(f"session {session_id} not found in sessions table")
    return SessionMeta(
        participant_id=str(row[0]),
        site_id=str(row[1]),
        sponsor_id=str(row[2]),
    )


def fetch_existing_sample_indices(
    conn: psycopg2.extensions.connection, table: str, session_id: str
) -> frozenset[int]:
    """Return sample_index values already present in a biosignal table."""
    cur = conn.cursor()
    cur.execute(
        f"SELECT DISTINCT sample_index FROM {table} WHERE session_id = %s",
        (session_id,),
    )
    result = frozenset(row[0] for row in cur.fetchall())
    cur.close()
    return result


def fetch_existing_echo_timestamps(
    conn: psycopg2.extensions.connection, session_id: str
) -> frozenset[float]:
    """Return ECHO lsl_timestamp values already present for a session."""
    cur = conn.cursor()
    cur.execute(
        "SELECT lsl_timestamp FROM echo_events WHERE session_id = %s",
        (session_id,),
    )
    result = frozenset(float(row[0]) for row in cur.fetchall())
    cur.close()
    return result


def fetch_existing_echo_keys(
    conn: psycopg2.extensions.connection, session_id: str
) -> frozenset[tuple[float, str, str, str, str]]:
    """Return composite ECHO keys already present for a session."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT lsl_timestamp, event_type, actor_id, actor_role, zone_label
        FROM echo_events
        WHERE session_id = %s
        """,
        (session_id,),
    )
    result = frozenset(
        (float(row[0]), str(row[1]), str(row[2]), str(row[3]), str(row[4]))
        for row in cur.fetchall()
    )
    cur.close()
    return result
