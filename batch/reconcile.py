"""batch/reconcile.py — XDF vs TimescaleDB reconciliation check.

Runs once after the forwarder exits. Compares per-stream sample counts
between the XDF backup file and TimescaleDB. Any discrepancy means samples
were captured to XDF but lost before reaching the DB (or vice versa) and
must be flagged before batch processing is permitted.

Usage:
    python -m batch.reconcile \\
        --session-id  <uuid> \\
        --xdf-path    /path/to/session_<uuid>_<ts>.xdf

Exit codes:
    0  — fully reconciled (counts match for all active streams)
    1  — gaps detected    (mismatch in one or more streams)
    2  — XDF file unreadable (missing, wrong magic, truncated before close)

REGULATORY NOTE — watermark_verified:
    CLAUDE.md requires that a watermark_verified event be written to
    audit_events before any batch job runs. audit_events is append-only
    and written only by database triggers — app code cannot INSERT directly.

    The current trigger on sessions fires only on INSERT, not UPDATE.
    A future migration must add an AFTER UPDATE trigger on sessions that
    writes event_type='watermark_verified' to audit_events when
    sessions.status transitions to 'closed'. Until that migration exists,
    the reconciliation result lives in the structured process log only.

    Blocking batch jobs on this log result is a coordinator responsibility.
"""

import argparse
import struct
import sys
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
import psycopg2.extras

from capture.logger import get_logger, set_session_id
from config import settings

log = get_logger("reconcile")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_XDF_MAGIC = b"XDF:"
_TAG_STREAM_HEADER = 2
_TAG_SAMPLES = 3
_TAG_STREAM_FOOTER = 6

_STREAM_TABLES: dict[str, str] = {
    "EEG": "eeg_samples",
    "HRV": "hrv_samples",
    "EDA": "eda_samples",
    "Respiration": "respiration_samples",
}


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class XDFReadError(Exception):
    """XDF file is missing, has invalid magic, or cannot be parsed."""


class XDFTruncatedError(XDFReadError):
    """XDF file has no stream footers — forwarder was killed before close()."""


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class StreamResult:
    xdf_count: int
    db_count: int
    gap: int  # xdf_count - db_count; positive = lost in DB, negative = lost in XDF


@dataclass
class ReconciliationReport:
    session_id: str
    xdf_path: Path
    streams: dict[str, StreamResult] = field(default_factory=dict)
    is_reconciled: bool = False
    ran_at: str = ""

    def as_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "xdf_path": str(self.xdf_path),
            "is_reconciled": self.is_reconciled,
            "ran_at": self.ran_at,
            "streams": {
                name: {
                    "xdf_count": r.xdf_count,
                    "db_count": r.db_count,
                    "gap": r.gap,
                }
                for name, r in self.streams.items()
            },
        }


# ---------------------------------------------------------------------------
# XDF reader
# ---------------------------------------------------------------------------


def _read_chunk_length(f) -> int | None:
    """Read XDF variable-length integer from open file. Returns None at EOF."""
    nb = f.read(1)
    if not nb:
        return None
    num_bytes = nb[0]
    if num_bytes not in (1, 2, 4, 8):
        raise XDFReadError(
            f"invalid NumLengthBytes={num_bytes} at offset {f.tell() - 1}"
        )
    raw = f.read(num_bytes)
    if len(raw) < num_bytes:
        return None  # truncated
    fmt = {1: "<B", 2: "<H", 4: "<I", 8: "<Q"}[num_bytes]
    return struct.unpack(fmt, raw)[0]


def read_xdf_counts(xdf_path: Path) -> dict[str, int]:
    """Return {stream_name: sample_count} by parsing StreamFooter chunks.

    Reads StreamHeader chunks to build the stream_id → name map, then reads
    StreamFooter chunks for the counts. All other chunk payloads are skipped
    in O(1) memory by seeking past them.

    Raises:
        XDFReadError      — file missing, wrong magic, or parse error.
        XDFTruncatedError — file has no footers (forwarder crashed before close).
    """
    if not xdf_path.exists():
        raise XDFReadError(f"XDF file not found: {xdf_path}")

    id_to_name: dict[int, str] = {}
    counts: dict[str, int] = {}
    has_footers = False

    try:
        with open(xdf_path, "rb") as f:
            magic = f.read(4)
            if magic != _XDF_MAGIC:
                raise XDFReadError(
                    f"not an XDF file — magic={magic!r}, path={xdf_path}"
                )

            while True:
                length = _read_chunk_length(f)
                if length is None:
                    break  # clean EOF or truncated before next chunk

                tag_raw = f.read(2)
                if len(tag_raw) < 2:
                    break
                tag = struct.unpack("<H", tag_raw)[0]
                payload_length = length - 2

                if tag == _TAG_STREAM_HEADER and payload_length >= 4:
                    payload = f.read(payload_length)
                    sid = struct.unpack_from("<I", payload, 0)[0]
                    xml_str = payload[4:].decode("utf-8", errors="replace")
                    try:
                        root = ET.fromstring(xml_str)
                        name_el = root.find("name")
                        if name_el is not None and name_el.text:
                            id_to_name[sid] = name_el.text
                    except ET.ParseError:
                        pass  # best-effort — keep going

                elif tag == _TAG_STREAM_FOOTER and payload_length >= 4:
                    has_footers = True
                    payload = f.read(payload_length)
                    sid = struct.unpack_from("<I", payload, 0)[0]
                    xml_str = payload[4:].decode("utf-8", errors="replace")
                    try:
                        root = ET.fromstring(xml_str)
                        count_el = root.find("sample_count")
                        if count_el is not None and count_el.text:
                            stream_name = id_to_name.get(sid, f"stream_{sid}")
                            counts[stream_name] = int(count_el.text)
                    except (ET.ParseError, ValueError):
                        pass

                else:
                    f.seek(payload_length, 1)  # skip payload

    except OSError as exc:
        raise XDFReadError(f"cannot read XDF file: {exc}") from exc

    if not has_footers:
        raise XDFTruncatedError(
            f"XDF file has no stream footers — forwarder was stopped before close(): {xdf_path}"
        )

    return counts


# ---------------------------------------------------------------------------
# DB reader
# ---------------------------------------------------------------------------


def query_db_counts(
    conn: psycopg2.extensions.connection, session_id: str
) -> dict[str, int]:
    """Return {stream_name: distinct_sample_count} from TimescaleDB.

    Uses COUNT(DISTINCT sample_index) so EEG counts match XDF:
      - EEG narrow-row: 8 DB rows per LSL sample → DISTINCT collapses to 1
      - HRV / EDA / Respiration: 1 DB row per sample → same result as COUNT(*)
    """
    counts: dict[str, int] = {}
    cur = conn.cursor()
    for stream_name, table in _STREAM_TABLES.items():
        cur.execute(
            f"SELECT COUNT(DISTINCT sample_index) FROM {table} WHERE session_id = %s",
            (session_id,),
        )
        row = cur.fetchone()
        counts[stream_name] = int(row[0]) if row else 0
    cur.close()
    return counts


# ---------------------------------------------------------------------------
# Reconciliation logic
# ---------------------------------------------------------------------------


def build_report(
    session_id: str,
    xdf_path: Path,
    xdf_counts: dict[str, int],
    db_counts: dict[str, int],
) -> ReconciliationReport:
    """Compare counts and build a ReconciliationReport."""
    all_streams = set(xdf_counts) | set(db_counts) | set(_STREAM_TABLES)
    streams: dict[str, StreamResult] = {}

    for name in sorted(all_streams):
        xdf_n = xdf_counts.get(name, 0)
        db_n = db_counts.get(name, 0)
        streams[name] = StreamResult(xdf_count=xdf_n, db_count=db_n, gap=xdf_n - db_n)

    is_reconciled = all(r.gap == 0 for r in streams.values())

    return ReconciliationReport(
        session_id=session_id,
        xdf_path=xdf_path,
        streams=streams,
        is_reconciled=is_reconciled,
        ran_at=datetime.now(timezone.utc).isoformat(),
    )


def close_session(
    conn: psycopg2.extensions.connection,
    session_id: str,
    is_reconciled: bool,
) -> None:
    """Set sessions.status and closed_at. Triggers updated_at via DB trigger.

    NOTE: The sessions audit trigger fires on INSERT only (migration 020).
    A future migration must add an AFTER UPDATE trigger that writes
    event_type='watermark_verified' to audit_events when status → 'closed',
    and event_type='watermark_failed' when status → 'failed'.
    Until then, the reconciliation log file is the durable record.
    """
    new_status = "closed" if is_reconciled else "failed"
    cur = conn.cursor()
    cur.execute(
        "UPDATE sessions SET status = %s, closed_at = NOW() WHERE id = %s",
        (new_status, session_id),
    )
    conn.commit()
    cur.close()


# ---------------------------------------------------------------------------
# XDF backfill
# ---------------------------------------------------------------------------
#
# When reconciliation finds a positive gap (xdf_count > db_count), some
# samples were written to XDF but never reached TimescaleDB. Backfill reads
# those samples from XDF and inserts them into the appropriate hypertable.
#
# CHUNK SIZE RATIONALE (1,000 rows per commit):
#   (1) Memory: pending rows are held in a list; 1,000 rows keeps the working
#       set small across all modalities.
#   (2) Audit triggers: each commit fires the lightweight audit trigger once
#       per row. Chunking gives audit_events meaningful per-batch granularity
#       rather than one massive atomic operation that is hard to inspect.
#   (3) Resumability: if the backfill is interrupted, at most 999 rows are
#       lost (not the entire session's worth). Re-running backfill is safe
#       because INSERT uses ON CONFLICT DO NOTHING via sample_index dedup.
#
# Tune BACKFILL_CHUNK_SIZE_ROWS during Phase 5 performance testing.
# For EEG at 256 Hz × 8 channels: 1,000 rows ≈ 125 LSL samples ≈ 0.5 s.
# For HRV/EDA/Respiration: 1,000 rows = 1,000 LSL samples.

BACKFILL_CHUNK_SIZE_ROWS: int = 1_000

# Log a backfill progress line every N commits.
_BACKFILL_LOG_EVERY_N_COMMITS: int = 10


@dataclass(frozen=True)
class SessionMeta:
    participant_id: str
    site_id: str
    sponsor_id: str


def fetch_session_meta(
    conn: psycopg2.extensions.connection, session_id: str
) -> SessionMeta:
    """Query the sessions table for metadata needed to reconstruct DB rows."""
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
    """Return the set of sample_index values already present in the table.

    Used to skip rows that were successfully written during the session.
    For a 4-hour EEG session (≈3.7 M samples), this set is ≈30–60 MB in
    memory — acceptable given the one-time nature of backfill.
    """
    cur = conn.cursor()
    cur.execute(
        f"SELECT DISTINCT sample_index FROM {table} WHERE session_id = %s",
        (session_id,),
    )
    result = frozenset(row[0] for row in cur.fetchall())
    cur.close()
    return result


# Per-table INSERT SQL (parameterised — no string interpolation of values).
# device_id comes from settings.DEVICE_ID; all other metadata from SessionMeta.

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
    """Reconstruct DB row dicts from XDF sample data.

    Mirrors the row-builder logic in lsl_forwarder.py. No filters are applied
    — derived fields (heart_rate_bpm, conductance_us, processed_amplitude)
    are computed the same way the forwarder computed them originally.
    """
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
            {**base, "channel_id": f"ch_{ch}", "voltage": float(v)}
            for ch, v in enumerate(vals)
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


def stream_xdf_samples(
    xdf_path: Path,
    target_stream_name: str,
) -> Iterator[tuple[int, float, list[float]]]:
    """Yield (sample_index, lsl_timestamp, channel_values) for one stream.

    Reads the XDF file sequentially. StreamHeader chunks are parsed to build
    a stream_id → (name, channel_count) map. For the target stream, Samples
    chunks are decoded and yielded with a reconstructed sample_index (the
    stream-local 0-based position, which matches what lsl_forwarder.py
    assigned). Samples chunks for other streams are skipped in O(1) time
    by seeking past them.

    The reconstructed sample_index is correct because:
      - lsl_forwarder.py increments self._sample_index once per LSL sample
        in the same order that XDFWriter.write_samples() receives them.
      - So XDF sample at stream-local position N always corresponds to
        sample_index N in the DB.
    """
    id_to_name: dict[int, str] = {}
    id_to_channels: dict[int, int] = {}
    stream_positions: dict[int, int] = {}  # sid → samples seen so far

    with open(xdf_path, "rb") as f:
        magic = f.read(4)
        if magic != _XDF_MAGIC:
            raise XDFReadError(f"not an XDF file: {xdf_path}")

        while True:
            length = _read_chunk_length(f)
            if length is None:
                break

            tag_raw = f.read(2)
            if len(tag_raw) < 2:
                break
            tag = struct.unpack("<H", tag_raw)[0]
            payload_remaining = length - 2

            if tag == _TAG_STREAM_HEADER and payload_remaining >= 4:
                sid = struct.unpack("<I", f.read(4))[0]
                xml_bytes = f.read(payload_remaining - 4)
                try:
                    root = ET.fromstring(xml_bytes.decode("utf-8", errors="replace"))
                    name_el = root.find("name")
                    ch_el = root.find("channel_count")
                    if name_el is not None and name_el.text:
                        id_to_name[sid] = name_el.text
                    if ch_el is not None and ch_el.text:
                        id_to_channels[sid] = int(ch_el.text)
                except (ET.ParseError, ValueError):
                    pass

            elif tag == _TAG_SAMPLES and payload_remaining >= 13:
                sid = struct.unpack("<I", f.read(4))[0]
                f.read(8)  # collection_time — not needed for backfill
                num_samples = _read_chunk_length(f)
                if num_samples is None:
                    break

                stream_name = id_to_name.get(sid, f"stream_{sid}")
                n_channels = id_to_channels.get(sid, 0)
                start_idx = stream_positions.get(sid, 0)

                if stream_name == target_stream_name and n_channels > 0:
                    for i in range(num_samples):
                        ts_raw = f.read(8)
                        if len(ts_raw) < 8:
                            return
                        ts = struct.unpack("<d", ts_raw)[0]
                        vraw = f.read(n_channels * 4)
                        if len(vraw) < n_channels * 4:
                            return
                        vals = list(struct.unpack(f"<{n_channels}f", vraw))
                        yield (start_idx + i, ts, vals)
                elif n_channels > 0:
                    # Skip all samples for this other stream.
                    # Each sample = 8 bytes (timestamp) + n_channels * 4 bytes (float32).
                    f.seek(num_samples * (8 + n_channels * 4), 1)
                else:
                    # Unknown channel count — can't skip safely; stop.
                    break

                stream_positions[sid] = start_idx + num_samples

            else:
                f.seek(payload_remaining, 1)


def backfill_stream(
    conn: psycopg2.extensions.connection,
    stream_name: str,
    session_id: str,
    xdf_path: Path,
    meta: SessionMeta,
    chunk_size: int = BACKFILL_CHUNK_SIZE_ROWS,
) -> int:
    """Insert rows missing from TimescaleDB by replaying samples from XDF.

    Returns the total number of DB rows inserted.

    Strategy:
      1. Fetch the set of sample_index values already present in the table.
      2. Stream samples from XDF for this stream.
      3. For each sample whose index is absent from the DB: build rows and
         add to a pending batch.
      4. Commit the batch once it reaches chunk_size rows.
      5. Repeat until the XDF stream is exhausted, then commit any remainder.

    ON CONFLICT DO NOTHING in the INSERT SQL means re-running backfill after
    an interruption is always safe — duplicate rows are silently dropped.

    chunk_size is in DB rows (not LSL samples). For EEG this means
    chunk_size // 8 LSL samples per commit at the default of 1,000.
    """
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

        rows = _build_backfill_rows(
            stream_name, session_id, sample_index, lsl_ts, vals, meta
        )
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

    # Commit any remaining rows
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
    """Run backfill for every stream that has a positive gap (xdf > db).

    Streams with gap == 0 are skipped. Streams with gap < 0 (db > xdf,
    meaning XDF write failures) are logged as warnings — those samples
    cannot be recovered from XDF and need manual review.

    Returns {stream_name: rows_inserted}.
    """
    results: dict[str, int] = {}

    for stream_name, result in report.streams.items():
        if result.gap == 0:
            continue

        if result.gap < 0:
            log.warning(
                "DB has more samples than XDF — XDF write failures occurred",
                extra={
                    "stream_name": stream_name,
                    "db_count": result.db_count,
                    "xdf_count": result.xdf_count,
                    "excess_in_db": abs(result.gap),
                },
            )
            results[stream_name] = 0
            continue

        # gap > 0: XDF has samples the DB is missing — backfill them
        log.info(
            "backfill required",
            extra={
                "stream_name": stream_name,
                "gap_samples": result.gap,
                "xdf_count": result.xdf_count,
                "db_count": result.db_count,
            },
        )
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


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Consensai XDF ↔ TimescaleDB reconciliation"
    )
    p.add_argument("--session-id", required=True)
    p.add_argument("--xdf-path", required=True, type=Path)
    p.add_argument(
        "--backfill",
        action="store_true",
        help=(
            "If gaps are found, replay missing samples from XDF into TimescaleDB, "
            f"then re-reconcile. Commits in chunks of {BACKFILL_CHUNK_SIZE_ROWS} rows."
        ),
    )
    p.add_argument(
        "--chunk-size",
        type=int,
        default=BACKFILL_CHUNK_SIZE_ROWS,
        metavar="ROWS",
        help="DB rows per commit during backfill (default: %(default)s). Tune in Phase 5.",
    )
    return p.parse_args()


def main() -> None:
    settings.validate()
    args = _parse_args()
    set_session_id(args.session_id)

    log.info(
        "reconciliation starting",
        extra={
            "session_id": args.session_id,
            "xdf_path": str(args.xdf_path),
            "backfill": args.backfill,
        },
    )

    # --- Read XDF ---
    try:
        xdf_counts = read_xdf_counts(args.xdf_path)
    except XDFTruncatedError as exc:
        log.error("XDF file truncated — footers missing", extra={"error": str(exc)})
        sys.exit(2)
    except XDFReadError as exc:
        log.error("XDF file unreadable", extra={"error": str(exc)})
        sys.exit(2)

    # --- Read DB and build initial report ---
    try:
        conn = psycopg2.connect(settings.DATABASE_URL)
        conn.autocommit = False
    except psycopg2.OperationalError as exc:
        log.error("DB connection failed", extra={"error": str(exc)})
        sys.exit(2)

    try:
        db_counts = query_db_counts(conn, args.session_id)
        report = build_report(args.session_id, args.xdf_path, xdf_counts, db_counts)

        # --- Backfill if requested and gaps exist ---
        if args.backfill and not report.is_reconciled:
            meta = fetch_session_meta(conn, args.session_id)
            backfill_results = run_backfill(
                conn, report, meta, chunk_size=args.chunk_size
            )
            log.info("backfill finished", extra={"rows_by_stream": backfill_results})

            # Re-reconcile after backfill to produce the final report
            db_counts_after = query_db_counts(conn, args.session_id)
            report = build_report(
                args.session_id, args.xdf_path, xdf_counts, db_counts_after
            )

        close_session(conn, args.session_id, report.is_reconciled)
    finally:
        conn.close()

    # --- Log final report ---
    if report.is_reconciled:
        log.info("reconciliation PASSED", extra=report.as_dict())
    else:
        gaps = {k: v.gap for k, v in report.streams.items() if v.gap != 0}
        log.error(
            "reconciliation FAILED — sample gaps detected",
            extra={**report.as_dict(), "streams_with_gaps": gaps},
        )

    sys.exit(0 if report.is_reconciled else 1)


if __name__ == "__main__":
    main()
