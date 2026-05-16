"""XDF backfill logic for biosignals and ECHO markers."""

from pathlib import Path

import psycopg2
import psycopg2.extras

from batch.reconciliation.db import (
    fetch_existing_echo_timestamps,
    fetch_existing_sample_indices,
)
from batch.reconciliation.models import (
    _BACKFILL_LOG_EVERY_N_COMMITS,
    _ECHO_STREAM_NAME,
    _STREAM_TABLES,
    BACKFILL_CHUNK_SIZE_ROWS,
    ReconciliationReport,
    SessionMeta,
)
from batch.reconciliation.xdf import stream_xdf_markers, stream_xdf_samples
from capture.echo_handler import parse_echo_marker
from capture.logger import get_logger
from config import settings

log = get_logger("reconcile")

_BACKFILL_EEG_INSERT = """
    INSERT INTO eeg_samples
        (session_id, participant_id, site_id, sponsor_id, device_id,
         channel_id, voltage, lsl_timestamp, sample_index)
    VALUES
        (%(session_id)s, %(participant_id)s, %(site_id)s, %(sponsor_id)s, %(device_id)s,
         %(channel_id)s, %(voltage)s, %(lsl_timestamp)s, %(sample_index)s)
    ON CONFLICT DO NOTHING
"""

_BACKFILL_HRV_INSERT = """
    INSERT INTO hrv_samples
        (session_id, participant_id, site_id, sponsor_id, device_id,
         rr_interval_ms, heart_rate_bpm, beat_quality, lsl_timestamp, sample_index)
    VALUES
        (%(session_id)s, %(participant_id)s, %(site_id)s, %(sponsor_id)s, %(device_id)s,
         %(rr_interval_ms)s, %(heart_rate_bpm)s, %(beat_quality)s,
         %(lsl_timestamp)s, %(sample_index)s)
    ON CONFLICT DO NOTHING
"""

_BACKFILL_EDA_INSERT = """
    INSERT INTO eda_samples
        (session_id, participant_id, site_id, sponsor_id, device_id,
         raw_conductance_us, conductance_us, signal_quality, lsl_timestamp, sample_index)
    VALUES
        (%(session_id)s, %(participant_id)s, %(site_id)s, %(sponsor_id)s, %(device_id)s,
         %(raw_conductance_us)s, %(conductance_us)s, %(signal_quality)s,
         %(lsl_timestamp)s, %(sample_index)s)
    ON CONFLICT DO NOTHING
"""

_BACKFILL_RESPIRATION_INSERT = """
    INSERT INTO respiration_samples
        (session_id, participant_id, site_id, sponsor_id, device_id,
         raw_amplitude, processed_amplitude, breath_phase, breaths_per_min,
         lsl_timestamp, sample_index)
    VALUES
        (%(session_id)s, %(participant_id)s, %(site_id)s, %(sponsor_id)s, %(device_id)s,
         %(raw_amplitude)s, %(processed_amplitude)s, %(breath_phase)s, %(breaths_per_min)s,
         %(lsl_timestamp)s, %(sample_index)s)
    ON CONFLICT DO NOTHING
"""

_BACKFILL_ECHO_INSERT = """
    INSERT INTO echo_events
        (session_id, participant_id, site_id, sponsor_id,
         event_type, source, actor_id, actor_role, zone_label, lsl_timestamp)
    VALUES
        (%(session_id)s, %(participant_id)s, %(site_id)s, %(sponsor_id)s,
         %(event_type)s, 'manual_logging', %(actor_id)s, %(actor_role)s,
         %(zone_label)s, %(lsl_timestamp)s)
"""

_BACKFILL_INSERT: dict[str, str] = {
    "EEG": _BACKFILL_EEG_INSERT,
    "HRV": _BACKFILL_HRV_INSERT,
    "EDA": _BACKFILL_EDA_INSERT,
    "Respiration": _BACKFILL_RESPIRATION_INSERT,
}


def _build_backfill_rows(
    stream_name: str,
    session_id: str,
    sample_index: int,
    lsl_ts: float,
    vals: list[float],
    meta: SessionMeta,
) -> list[dict]:
    """Reconstruct DB row dicts from XDF biosignal sample data."""
    base = {
        "session_id": session_id,
        "participant_id": meta.participant_id,
        "site_id": meta.site_id,
        "sponsor_id": meta.sponsor_id,
        "device_id": settings.DEVICE_ID,
        "lsl_timestamp": lsl_ts,
        "sample_index": sample_index,
    }

    if stream_name == "EEG":
        return [
            {**base, "channel_id": f"ch_{ch}", "voltage": float(v)} for ch, v in enumerate(vals)
        ]

    if stream_name == "HRV":
        rr_ms = float(vals[0])
        return [
            {
                **base,
                "rr_interval_ms": rr_ms,
                "heart_rate_bpm": 60000.0 / rr_ms if rr_ms > 0 else None,
                "beat_quality": None,
            }
        ]

    if stream_name == "EDA":
        conductance = float(vals[0])
        return [
            {
                **base,
                "raw_conductance_us": conductance,
                "conductance_us": conductance,
                "signal_quality": None,
            }
        ]

    if stream_name == "Respiration":
        amplitude = float(vals[0])
        return [
            {
                **base,
                "raw_amplitude": amplitude,
                "processed_amplitude": amplitude,
                "breath_phase": None,
                "breaths_per_min": None,
            }
        ]

    raise ValueError(f"unknown stream_name: {stream_name!r}")


def backfill_echo_markers(
    conn: psycopg2.extensions.connection,
    session_id: str,
    xdf_path: Path,
    meta: SessionMeta,
    chunk_size: int = BACKFILL_CHUNK_SIZE_ROWS,
) -> int:
    """Replay ECHO markers from XDF into echo_events."""
    existing = fetch_existing_echo_timestamps(conn, session_id)
    pending: list[dict] = []
    total_rows = 0
    skipped = 0

    for _, lsl_ts, marker in stream_xdf_markers(xdf_path):
        if lsl_ts in existing:
            skipped += 1
            continue

        parsed = parse_echo_marker(marker)
        if parsed is None:
            log.warning(
                "ECHO marker in XDF could not be parsed during backfill",
                extra={"marker": marker[:100], "lsl_timestamp": lsl_ts},
            )
            continue

        pending.append(
            {
                "session_id": session_id,
                "participant_id": meta.participant_id,
                "site_id": meta.site_id,
                "sponsor_id": meta.sponsor_id,
                "lsl_timestamp": lsl_ts,
                **parsed,
            }
        )

        if len(pending) >= chunk_size:
            cur = conn.cursor()
            psycopg2.extras.execute_batch(cur, _BACKFILL_ECHO_INSERT, pending)
            conn.commit()
            cur.close()
            total_rows += len(pending)
            existing = existing | frozenset(row["lsl_timestamp"] for row in pending)
            pending = []

    if pending:
        cur = conn.cursor()
        psycopg2.extras.execute_batch(cur, _BACKFILL_ECHO_INSERT, pending)
        conn.commit()
        cur.close()
        total_rows += len(pending)

    log.info(
        "ECHO backfill complete",
        extra={"rows_inserted": total_rows, "skipped_existing": skipped},
    )
    return total_rows


def backfill_stream(
    conn: psycopg2.extensions.connection,
    stream_name: str,
    session_id: str,
    xdf_path: Path,
    meta: SessionMeta,
    chunk_size: int = BACKFILL_CHUNK_SIZE_ROWS,
) -> int:
    """Insert missing biosignal rows by replaying samples from XDF."""
    table = _STREAM_TABLES[stream_name]
    insert_sql = _BACKFILL_INSERT[stream_name]
    existing = fetch_existing_sample_indices(conn, table, session_id)

    log.info(
        "backfill starting",
        extra={
            "stream_name": stream_name,
            "existing_in_db": len(existing),
            "chunk_size_rows": chunk_size,
        },
    )

    pending: list[dict] = []
    total_rows = 0
    commits = 0
    skipped = 0

    for sample_index, lsl_ts, vals in stream_xdf_samples(xdf_path, stream_name):
        if sample_index in existing:
            skipped += 1
            continue

        pending.extend(
            _build_backfill_rows(stream_name, session_id, sample_index, lsl_ts, vals, meta)
        )

        if len(pending) >= chunk_size:
            cur = conn.cursor()
            psycopg2.extras.execute_batch(cur, insert_sql, pending)
            conn.commit()
            cur.close()
            total_rows += len(pending)
            commits += 1
            pending = []

            if commits % _BACKFILL_LOG_EVERY_N_COMMITS == 0:
                log.info(
                    "backfill progress",
                    extra={
                        "stream_name": stream_name,
                        "rows_inserted": total_rows,
                        "commits": commits,
                        "skipped_existing": skipped,
                    },
                )

    if pending:
        cur = conn.cursor()
        psycopg2.extras.execute_batch(cur, insert_sql, pending)
        conn.commit()
        cur.close()
        total_rows += len(pending)
        commits += 1

    log.info(
        "backfill complete",
        extra={
            "stream_name": stream_name,
            "rows_inserted": total_rows,
            "commits": commits,
            "skipped_existing": skipped,
            "chunk_size_rows": chunk_size,
        },
    )
    return total_rows


def run_backfill(
    conn: psycopg2.extensions.connection,
    report: ReconciliationReport,
    meta: SessionMeta,
    chunk_size: int = BACKFILL_CHUNK_SIZE_ROWS,
) -> dict[str, int]:
    """Run backfill for every stream where XDF has more samples than DB."""
    results: dict[str, int] = {}

    for stream_name, result in report.streams.items():
        if result.gap == 0:
            continue

        if result.gap < 0:
            log.warning(
                "DB has more samples than XDF - XDF write failures occurred",
                extra={
                    "stream_name": stream_name,
                    "db_count": result.db_count,
                    "xdf_count": result.xdf_count,
                    "excess_in_db": abs(result.gap),
                },
            )
            results[stream_name] = 0
            continue

        log.info(
            "backfill required",
            extra={
                "stream_name": stream_name,
                "gap_samples": result.gap,
                "xdf_count": result.xdf_count,
                "db_count": result.db_count,
            },
        )
        if stream_name == _ECHO_STREAM_NAME:
            rows = backfill_echo_markers(
                conn=conn,
                session_id=report.session_id,
                xdf_path=report.xdf_path,
                meta=meta,
                chunk_size=chunk_size,
            )
        else:
            rows = backfill_stream(
                conn=conn,
                stream_name=stream_name,
                session_id=report.session_id,
                xdf_path=report.xdf_path,
                meta=meta,
                chunk_size=chunk_size,
            )
        results[stream_name] = rows

    return results
