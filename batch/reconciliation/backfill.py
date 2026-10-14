"""XDF backfill logic for biosignals and ECHO markers."""

import json
from dataclasses import replace
from pathlib import Path

import psycopg2
import psycopg2.extras

from batch.reconciliation.db import (
    fetch_existing_echo_keys,
    fetch_existing_eeg_keys,
    fetch_existing_sample_indices,
    fetch_session_meta,
    require_sponsor_scope,
    validate_session_meta,
)
from batch.reconciliation.models import (
    _BACKFILL_LOG_EVERY_N_COMMITS,
    _ECHO_STREAM_NAME,
    _STREAM_TABLES,
    BACKFILL_CHUNK_SIZE_ROWS,
    ReconciliationReport,
    SessionMeta,
    XDFReadError,
)
from batch.reconciliation.xdf import (
    inspect_xdf,
    stream_xdf_markers,
    stream_xdf_samples,
    validate_xdf_identity,
)
from capture.echo_handler import parse_echo_marker
from capture.logger import get_logger
from capture.session_lock import acquire_session_lock
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


def _meta_field(meta, key: str, default=None):
    """Read a field from a SessionMeta object or a plain mapping."""
    if isinstance(meta, dict):
        return meta.get(key, default)
    return getattr(meta, key, default)


def _validate_replay(conn, session_id, xdf_path, meta, sponsor_id, site_id, chunk_size, legacy):
    """Validate identity and provenance before any replay writes, under the session lock."""
    scope = require_sponsor_scope(sponsor_id)
    if not isinstance(chunk_size, int) or isinstance(chunk_size, bool) or chunk_size <= 0:
        raise ValueError("backfill chunk_size must be a positive integer")
    acquire_session_lock(conn, session_id)
    canonical = fetch_session_meta(conn, session_id, scope, site_id=site_id)
    validate_session_meta(meta, canonical)
    validate_xdf_identity(
        xdf_path, session_id, scope, canonical.participant_id, canonical.site_id, legacy=legacy
    )
    recording = inspect_xdf(xdf_path, legacy=legacy)
    names = canonical.eeg_channel_names
    devices = dict(canonical.device_ids)
    for stream_name, header in recording.stream_metadata.items():
        header_device = header.get("device_id")
        if header_device:
            if stream_name in devices and devices[stream_name] != header_device:
                raise XDFReadError(f"{stream_name} XDF device differs from session metadata")
            devices[stream_name] = header_device
        if stream_name in _STREAM_TABLES and recording.counts.get(stream_name, 0) > 0:
            if not devices.get(stream_name):
                raise XDFReadError(f"{stream_name} device identity missing from session and XDF")
        if stream_name == "EEG":
            encoded_names = header.get("eeg_channel_names")
            if encoded_names:
                try:
                    values = json.loads(encoded_names)
                except (TypeError, ValueError) as exc:
                    raise XDFReadError("XDF EEG channel names are malformed") from exc
                if (
                    not isinstance(values, list)
                    or not values
                    or any(not isinstance(name, str) or not name for name in values)
                    or len(set(values)) != len(values)
                ):
                    raise XDFReadError("XDF EEG channel names are malformed")
                header_names = tuple(values)
                if names is not None and names != header_names:
                    raise XDFReadError("XDF EEG channels differ from session metadata")
                names = header_names
            if names and len(names) != int(header["channel_count"]):
                raise XDFReadError("EEG channel metadata width differs from XDF")
    return replace(canonical, eeg_channel_names=names, device_ids=devices)


def _build_backfill_rows(
    stream_name: str,
    meta: SessionMeta | dict,
    sample_index: int,
    lsl_timestamp: float,
    vals: list[float],
    session_id: str | None = None,
) -> list[dict]:
    """Reconstruct DB row dicts from XDF biosignal sample data.

    meta carries session identity (SessionMeta or a mapping that may also
    include session_id/device_id); an explicit session_id overrides it.
    """
    base = {
        "session_id": session_id or _meta_field(meta, "session_id"),
        "participant_id": _meta_field(meta, "participant_id"),
        "site_id": _meta_field(meta, "site_id"),
        "sponsor_id": _meta_field(meta, "sponsor_id"),
        "device_id": (
            _meta_field(meta, "device_ids", {}).get(stream_name)
            or _meta_field(meta, "device_id")
            or settings.DEVICE_ID
        ),
        "lsl_timestamp": lsl_timestamp,
        "sample_index": sample_index,
    }

    if stream_name == "EEG":
        names = _meta_field(meta, "eeg_channel_names")
        if names is not None and len(names) != len(vals):
            raise ValueError("EEG channel names do not match the XDF sample width")
        if names is None:
            names = tuple(f"ch_{ch}" for ch in range(len(vals)))
        return [{**base, "channel_id": name, "voltage": float(v)} for name, v in zip(names, vals)]

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


def _backfill_echo_markers_validated(
    conn: psycopg2.extensions.connection,
    session_id: str,
    xdf_path: Path,
    meta: SessionMeta | dict,
    chunk_size: int = BACKFILL_CHUNK_SIZE_ROWS,
    *,
    legacy: bool = False,
) -> int:
    """Replay ECHO markers from XDF into echo_events."""
    existing = set(
        fetch_existing_echo_keys(
            conn, session_id, _meta_field(meta, "sponsor_id"), site_id=_meta_field(meta, "site_id")
        )
    )
    pending: list[dict] = []
    total_rows = 0
    skipped = 0

    for _, lsl_ts, marker in stream_xdf_markers(xdf_path, legacy=legacy):
        parsed = parse_echo_marker(marker)
        if parsed is None:
            log.warning(
                "ECHO marker in XDF could not be parsed during backfill",
                extra={"marker": marker[:100], "lsl_timestamp": lsl_ts},
            )
            continue

        key = (
            float(lsl_ts),
            str(parsed["event_type"]),
            str(parsed["actor_id"]),
            str(parsed["actor_role"]),
            str(parsed["zone_label"]),
        )
        if key in existing:
            skipped += 1
            log.debug(
                "ECHO replay marker skipped — already present",
                extra={
                    "session_id": session_id,
                    "event_type": parsed["event_type"],
                    "actor_role": parsed["actor_role"],
                    "zone_label": parsed["zone_label"],
                    "lsl_timestamp": lsl_ts,
                    "ingestion_path": "xdf_replay",
                },
            )
            continue

        existing.add(key)
        pending.append(
            {
                "session_id": session_id,
                "participant_id": _meta_field(meta, "participant_id"),
                "site_id": _meta_field(meta, "site_id"),
                "sponsor_id": _meta_field(meta, "sponsor_id"),
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
            log.info(
                "ECHO replay batch inserted",
                extra={
                    "session_id": session_id,
                    "rows_inserted": len(pending),
                    "total_rows_inserted": total_rows,
                    "xdf_path": str(xdf_path),
                    "ingestion_path": "xdf_replay",
                },
            )
            pending = []

    if pending:
        cur = conn.cursor()
        psycopg2.extras.execute_batch(cur, _BACKFILL_ECHO_INSERT, pending)
        conn.commit()
        cur.close()
        total_rows += len(pending)
        log.info(
            "ECHO replay batch inserted",
            extra={
                "session_id": session_id,
                "rows_inserted": len(pending),
                "total_rows_inserted": total_rows,
                "xdf_path": str(xdf_path),
                "ingestion_path": "xdf_replay",
            },
        )

    log.info(
        "ECHO backfill complete",
        extra={
            "session_id": session_id,
            "rows_inserted": total_rows,
            "skipped_existing": skipped,
            "xdf_path": str(xdf_path),
            "ingestion_path": "xdf_replay",
        },
    )
    return total_rows


def _backfill_stream_validated(
    conn: psycopg2.extensions.connection,
    stream_name: str,
    session_id: str,
    xdf_path: Path,
    meta: SessionMeta | dict,
    chunk_size: int = BACKFILL_CHUNK_SIZE_ROWS,
    *,
    legacy: bool = False,
) -> int:
    """Insert missing biosignal rows by replaying samples from XDF."""
    table = _STREAM_TABLES[stream_name]
    insert_sql = _BACKFILL_INSERT[stream_name]
    scope = _meta_field(meta, "sponsor_id")
    site_id = _meta_field(meta, "site_id")
    existing = fetch_existing_sample_indices(conn, session_id, table, scope, site_id=site_id)
    eeg_keys = (
        set(fetch_existing_eeg_keys(conn, session_id, scope, site_id=site_id))
        if stream_name == "EEG"
        else set()
    )

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

    for sample_index, lsl_ts, vals in stream_xdf_samples(xdf_path, stream_name, legacy=legacy):
        if stream_name != "EEG" and sample_index in existing:
            skipped += 1
            continue

        rows = _build_backfill_rows(stream_name, meta, sample_index, lsl_ts, vals, session_id)
        if stream_name == "EEG":
            rows = [row for row in rows if (sample_index, row["channel_id"]) not in eeg_keys]
            eeg_keys.update((sample_index, row["channel_id"]) for row in rows)
        pending.extend(rows)

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


def backfill_stream(
    conn,
    stream_name,
    session_id,
    xdf_path,
    meta,
    chunk_size=BACKFILL_CHUNK_SIZE_ROWS,
    *,
    sponsor_id=None,
    site_id=None,
    legacy=False,
) -> int:
    canonical = _validate_replay(
        conn, session_id, xdf_path, meta, sponsor_id, site_id, chunk_size, legacy
    )
    return _backfill_stream_validated(
        conn, stream_name, session_id, xdf_path, canonical, chunk_size, legacy=legacy
    )


def backfill_echo_markers(
    conn,
    session_id,
    xdf_path,
    meta,
    chunk_size=BACKFILL_CHUNK_SIZE_ROWS,
    *,
    sponsor_id=None,
    site_id=None,
    legacy=False,
) -> int:
    canonical = _validate_replay(
        conn, session_id, xdf_path, meta, sponsor_id, site_id, chunk_size, legacy
    )
    return _backfill_echo_markers_validated(
        conn, session_id, xdf_path, canonical, chunk_size, legacy=legacy
    )


def run_backfill(
    conn: psycopg2.extensions.connection,
    report: ReconciliationReport,
    xdf_path: str | Path | None = None,
    meta: SessionMeta | dict | None = None,
    chunk_size: int = BACKFILL_CHUNK_SIZE_ROWS,
    *,
    sponsor_id: str | None = None,
    site_id: str | None = None,
    legacy: bool = False,
) -> int:
    """Run backfill for every stream where XDF has more samples than DB.

    Returns the total number of rows inserted across all streams.
    xdf_path defaults to the report's recorded path.
    """
    xdf_path = Path(xdf_path) if xdf_path is not None else report.xdf_path
    meta = _validate_replay(
        conn, report.session_id, xdf_path, meta, sponsor_id, site_id, chunk_size, legacy
    )
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
            rows = _backfill_echo_markers_validated(
                conn=conn,
                session_id=report.session_id,
                xdf_path=xdf_path,
                meta=meta,
                chunk_size=chunk_size,
                legacy=legacy,
            )
        else:
            rows = _backfill_stream_validated(
                conn=conn,
                stream_name=stream_name,
                session_id=report.session_id,
                xdf_path=xdf_path,
                meta=meta,
                chunk_size=chunk_size,
                legacy=legacy,
            )
        results[stream_name] = rows

    log.info("backfill rows by stream", extra={"rows_by_stream": results})
    return sum(results.values())
