"""Tenant-scoped database helpers for reconciliation."""

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import psycopg2
from psycopg2 import sql
from psycopg2.extras import Json

from batch.reconciliation.models import (
    _ECHO_STREAM_NAME,
    _STREAM_TABLES,
    ReconciliationReport,
    SessionMeta,
    StreamResult,
)


def require_sponsor_scope(sponsor_id: str | None) -> str:
    """Reject absent/invalid scope before a connection or statement is used."""
    if not sponsor_id:
        raise ValueError("reconciliation requires sponsor_id")
    try:
        return str(UUID(str(sponsor_id)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("sponsor_id must be a UUID") from exc


def _scope(session_id: str, sponsor_id: str | None, site_id: str | None):
    return (session_id, require_sponsor_scope(sponsor_id), site_id, site_id)


_SCOPE_SQL = "session_id = %s AND sponsor_id = %s AND (%s::uuid IS NULL OR site_id = %s::uuid)"


def fetch_session_meta(
    conn, session_id: str, sponsor_id: str | None = None, *, site_id: str | None = None
) -> SessionMeta:
    """Read canonical session identity and recording metadata within the caller's scope."""
    scope = _scope(session_id, sponsor_id, site_id)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT participant_id, site_id, sponsor_id, status::text FROM sessions "
            "WHERE id = %s AND sponsor_id = %s AND (%s::uuid IS NULL OR site_id = %s::uuid)",
            scope,
        )
        row = cur.fetchone()
        if row is None:
            raise ValueError("session not found for the supplied sponsor/site")
        cur.execute(
            sql.SQL(
                "SELECT modality, device_id, eeg_channel_names "
                "FROM session_signal_metadata WHERE {scope}"
            ).format(scope=sql.SQL(_SCOPE_SQL)),
            (session_id, scope[1], str(row[1]), str(row[1])),
        )
        recording_rows = cur.fetchall()
    names = None
    devices = {}
    stream_names = {name.lower(): name for name in _STREAM_TABLES}
    for modality, device_id, raw_names in recording_rows:
        if modality in stream_names and device_id is not None:
            devices[stream_names[modality]] = str(device_id)
        if modality == "eeg" and raw_names is not None:
            values = json.loads(raw_names) if isinstance(raw_names, str) else raw_names
            if (
                not isinstance(values, list)
                or not values
                or any(not isinstance(name, str) or not name for name in values)
                or len(set(values)) != len(values)
            ):
                raise ValueError("session EEG channel metadata is invalid")
            names = tuple(values)
    return SessionMeta(str(row[0]), str(row[1]), str(row[2]), names, devices, str(row[3]))


def validate_session_meta(supplied: SessionMeta | dict | None, canonical: SessionMeta) -> None:
    """Caller-supplied metadata is a consistency assertion, never an authority."""
    if supplied is None:
        return
    for key in ("participant_id", "site_id", "sponsor_id"):
        value = supplied.get(key) if isinstance(supplied, dict) else getattr(supplied, key)
        if str(value) != getattr(canonical, key):
            raise ValueError(f"backfill {key} differs from canonical session identity")


def query_db_counts(
    conn, session_id: str, sponsor_id: str | None = None, *, site_id: str | None = None
) -> dict[str, int]:
    """Count complete samples and ECHO records for one canonical scoped session."""
    meta = fetch_session_meta(conn, session_id, sponsor_id, site_id=site_id)
    scope = _scope(session_id, meta.sponsor_id, meta.site_id)
    counts = {}
    with conn.cursor() as cur:
        for stream_name, table in _STREAM_TABLES.items():
            if stream_name == "EEG" and meta.eeg_channel_names:
                cur.execute(
                    sql.SQL(
                        "SELECT COUNT(*) FROM (SELECT sample_index FROM eeg_samples "
                        "WHERE {scope} GROUP BY sample_index "
                        "HAVING COUNT(DISTINCT channel_id) = %s "
                        "AND BOOL_AND(channel_id = ANY(%s))) AS complete_frames"
                    ).format(scope=sql.SQL(_SCOPE_SQL)),
                    (*scope, len(meta.eeg_channel_names), list(meta.eeg_channel_names)),
                )
            else:
                cur.execute(
                    sql.SQL(
                        "SELECT COUNT(DISTINCT sample_index) FROM {table} WHERE {scope}"
                    ).format(table=sql.Identifier(table), scope=sql.SQL(_SCOPE_SQL)),
                    scope,
                )
            row = cur.fetchone()
            counts[stream_name] = int(row[0]) if row else 0
        cur.execute(
            sql.SQL("SELECT COUNT(*) FROM echo_events WHERE {scope}").format(
                scope=sql.SQL(_SCOPE_SQL)
            ),
            scope,
        )
        row = cur.fetchone()
        counts[_ECHO_STREAM_NAME] = int(row[0]) if row else 0
    return counts


def query_max_clock_drift_s(
    conn, session_id: str, sponsor_id: str | None = None, *, site_id: str | None = None
) -> float | None:
    scope = _scope(session_id, sponsor_id, site_id)
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL(
                "SELECT MAX(ABS(remote_clock_offset_s)) FROM clock_drift_log WHERE {scope}"
            ).format(scope=sql.SQL(_SCOPE_SQL)),
            scope,
        )
        row = cur.fetchone()
    return None if not row or row[0] is None else float(row[0])


def build_report(
    session_id: str,
    xdf_path: Path,
    xdf_counts: dict[str, int],
    db_counts: dict[str, int],
    max_clock_drift_s: float | None = None,
) -> ReconciliationReport:
    all_streams = set(xdf_counts) | set(db_counts) | set(_STREAM_TABLES) | {_ECHO_STREAM_NAME}
    streams = {
        name: StreamResult(
            xdf_counts.get(name, 0),
            db_counts.get(name, 0),
            xdf_counts.get(name, 0) - db_counts.get(name, 0),
        )
        for name in sorted(all_streams)
    }
    return ReconciliationReport(
        session_id=session_id,
        xdf_path=Path(xdf_path),
        streams=streams,
        is_reconciled=all(result.gap == 0 for result in streams.values()),
        ran_at=datetime.now(timezone.utc).isoformat(),
        max_clock_drift_s=max_clock_drift_s,
    )


def close_session(
    conn: psycopg2.extensions.connection,
    session_id: str,
    sponsor_id: str | None = None,
    is_reconciled: bool = False,
    *,
    site_id: str | None = None,
) -> None:
    """Close exactly one scoped session; the DB trigger owns watermark events."""
    scope = _scope(session_id, sponsor_id, site_id)
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE sessions SET status = %s, closed_at = NOW() WHERE id = %s "
            "AND sponsor_id = %s AND (%s::uuid IS NULL OR site_id = %s::uuid)",
            ("closed" if is_reconciled else "failed", *scope),
        )
        if cur.rowcount != 1:
            conn.rollback()
            raise ValueError("session not found for the supplied sponsor/site; close refused")
    conn.commit()


def write_reconciliation_log(
    conn,
    report: ReconciliationReport,
    meta: SessionMeta | dict | None = None,
    *,
    sponsor_id: str | None = None,
    site_id: str | None = None,
) -> None:
    canonical = fetch_session_meta(conn, report.session_id, sponsor_id, site_id=site_id)
    validate_session_meta(meta, canonical)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO biosignal_integrity_log "
            "(session_id, participant_id, site_id, sponsor_id, log_type, reconciliation_report) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (
                report.session_id,
                canonical.participant_id,
                canonical.site_id,
                canonical.sponsor_id,
                "xdf_reconciliation",
                Json(report.as_dict()),
            ),
        )


def fetch_existing_sample_indices(
    conn, session_id: str, table: str, sponsor_id: str | None = None, *, site_id: str | None = None
) -> frozenset[int]:
    scope = _scope(session_id, sponsor_id, site_id)
    if table not in _STREAM_TABLES.values():
        raise ValueError("unknown biosignal table")
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL("SELECT DISTINCT sample_index FROM {table} WHERE {scope}").format(
                table=sql.Identifier(table), scope=sql.SQL(_SCOPE_SQL)
            ),
            scope,
        )
        return frozenset(int(row[0]) for row in cur.fetchall())


def fetch_existing_eeg_keys(
    conn, session_id: str, sponsor_id: str | None = None, *, site_id: str | None = None
) -> frozenset[tuple[int, str]]:
    scope = _scope(session_id, sponsor_id, site_id)
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL("SELECT sample_index, channel_id FROM eeg_samples WHERE {scope}").format(
                scope=sql.SQL(_SCOPE_SQL)
            ),
            scope,
        )
        return frozenset((int(row[0]), str(row[1])) for row in cur.fetchall())


def fetch_existing_echo_timestamps(
    conn, session_id: str, sponsor_id: str | None = None, *, site_id: str | None = None
) -> frozenset[float]:
    scope = _scope(session_id, sponsor_id, site_id)
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL("SELECT lsl_timestamp FROM echo_events WHERE {scope}").format(
                scope=sql.SQL(_SCOPE_SQL)
            ),
            scope,
        )
        return frozenset(float(row[0]) for row in cur.fetchall())


def fetch_existing_echo_keys(
    conn, session_id: str, sponsor_id: str | None = None, *, site_id: str | None = None
) -> frozenset[tuple[float, str, str, str, str]]:
    scope = _scope(session_id, sponsor_id, site_id)
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL(
                "SELECT lsl_timestamp, event_type, actor_id, actor_role, zone_label "
                "FROM echo_events WHERE {scope}"
            ).format(scope=sql.SQL(_SCOPE_SQL)),
            scope,
        )
        return frozenset(
            (float(row[0]), str(row[1]), str(row[2]), str(row[3]), str(row[4]))
            for row in cur.fetchall()
        )
