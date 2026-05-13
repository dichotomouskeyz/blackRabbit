"""Database-side helpers for reconciliation."""

from datetime import datetime, timezone
from pathlib import Path

import psycopg2

from batch.reconciliation.models import (
    ReconciliationReport,
    SessionMeta,
    StreamResult,
    _ECHO_STREAM_NAME,
    _STREAM_TABLES,
)


def query_db_counts(
    conn: psycopg2.extensions.connection, session_id: str
) -> dict[str, int]:
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


def build_report(
    session_id: str,
    xdf_path: Path,
    xdf_counts: dict[str, int],
    db_counts: dict[str, int],
) -> ReconciliationReport:
    """Compare counts and build a ReconciliationReport."""
    all_streams = (
        set(xdf_counts) | set(db_counts) | set(_STREAM_TABLES) | {_ECHO_STREAM_NAME}
    )
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


def fetch_session_meta(
    conn: psycopg2.extensions.connection, session_id: str
) -> SessionMeta:
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
