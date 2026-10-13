"""Exercise the local backend with fictional signals in an isolated test database.

Run from the repository root with identical DATABASE_URL and TEST_DATABASE_URL:
    uv run --frozen python -m scripts.backend_smoke

The selected database name must contain 'test' or 'audit'. This script creates
new pseudonymous sessions and retains their artifacts; it never clears tables.
It verifies the real capture writers and database pipeline with offline input.
It does not establish live LSL, hardware, or clinical performance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from uuid import uuid4

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import parse_dsn


def configure(output: Path) -> str:
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url or database_url != os.environ.get("TEST_DATABASE_URL"):
        raise RuntimeError(
            "Set DATABASE_URL and TEST_DATABASE_URL to the same isolated test database"
        )
    database_name = parse_dsn(database_url).get("dbname", "")
    if not any(marker in database_name.lower() for marker in ("test", "audit")):
        raise RuntimeError("Smoke database name must explicitly contain 'test' or 'audit'")
    # These controls precede all application imports and describe synthetic data.
    os.environ.update(
        PYTHON_DOTENV_DISABLED="1",
        CAPTURE_SOURCE="simulated",
        EEG_CHANNEL_COUNT="1",
        EEG_CHANNEL_NAMES="Fz",
        SAMPLE_RATE_EEG="100",
        SAMPLE_RATE_HRV="1",
        SAMPLE_RATE_EDA="4",
        SAMPLE_RATE_RESPIRATION="4",
        XDF_BACKUP_DIR=str(output / "xdf"),
        LOG_DIR=str(output / "logs"),
    )
    with psycopg2.connect(database_url, connect_timeout=5) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT current_database(), version_num FROM alembic_version")
            actual, revision = cur.fetchone()
            if actual != database_name or revision != "030_arc_failure_alert_type":
                raise RuntimeError("Isolated database must be migrated to the current head")
    return database_url


def signal_value(stream: str, elapsed: float) -> list[float]:
    response = 1.0 if 400 <= elapsed < 520 else 0.0
    if stream == "EEG":
        alpha = (10 + 2 * math.sin(elapsed * 0.17) + 8 * response) * math.sin(
            2 * math.pi * 10 * elapsed
        )
        theta = (4 + math.sin(elapsed * 0.09)) * math.sin(2 * math.pi * 6 * elapsed)
        beta = (3 + 0.7 * math.cos(elapsed * 0.23)) * math.sin(2 * math.pi * 21 * elapsed)
        return [alpha + theta + beta]
    if stream == "HRV":
        return [
            1000 + 40 * math.sin(elapsed * 0.71) + 25 * math.sin(elapsed * 0.19) + 100 * response
        ]
    if stream == "EDA":
        return [2 + 0.08 * math.sin(elapsed * 0.06) + 0.03 * math.cos(elapsed * 0.31) + response]
    return [
        (0.7 + 0.08 * math.sin(elapsed * 0.047) + 0.4 * response)
        * math.sin(2 * math.pi * 0.24 * elapsed)
    ]


def capture(database_url: str, output: Path) -> dict:
    from capture.echo_handler.runtime import process_next_sample
    from capture.forwarder.models import SessionConfig
    from capture.forwarder.preflight import run_preflight
    from capture.forwarder.stream_thread.stream_chunks import process_chunk
    from capture.forwarder.stream_thread.streams import build_stream_threads
    from capture.session_init.workflow import create_session
    from capture.xdf.writer import XDFWriter

    participant, site, sponsor = (str(uuid4()) for _ in range(3))
    session = create_session("psilocybin", site, sponsor, participant, capture_source="simulated")
    cfg = run_preflight(SessionConfig(session, participant, site, sponsor))
    writer = XDFWriter(session, participant, site, sponsor, eeg_channel_names=cfg.eeg_channel_names)
    threads = build_stream_threads(cfg, threading.Event(), writer)
    expected = {}
    calls = 0
    capture_start = time.monotonic()
    try:
        for thread in threads[:-1]:
            stream = thread.stream_type
            rate = 100 if stream == "EEG" else 1 if stream == "HRV" else 4
            total = 900 * rate
            thread.conn = psycopg2.connect(database_url, connect_timeout=5)
            for start in range(0, total, 1000):
                stop = min(start + 1000, total)
                samples = [signal_value(stream, i / rate) for i in range(start, stop)]
                timestamps = [10000.0 + i / rate for i in range(start, stop)]
                # Leave the final EDA chunk in the real recovery buffer. This
                # reproduces uncommitted capture at shutdown without deleting
                # or changing any raw row, so close must recover from XDF.
                if stream == "EDA" and stop == total:
                    thread.conn.close()
                    thread.conn = None
                process_chunk(thread, samples, timestamps)
                calls += 1
            expected[stream] = total
            if thread.conn is not None:
                thread.conn.close()
                thread.conn = None
            print(json.dumps({"stage": "captured", "stream": stream, "samples": total}), flush=True)
        echo = threads[-1]
        marker = "ECHO|manual_marker|synthetic_operator|therapist|dose_administration"

        class OfflineMarker:
            def pull_sample(self, timeout=1.0):
                return [marker], 10400.0

        connection = psycopg2.connect(database_url, connect_timeout=5)
        try:
            returned = process_next_sample(echo, OfflineMarker(), connection)
            if returned is None:
                raise RuntimeError("ECHO synthetic marker was not persisted")
        finally:
            connection.close()
        expected["ECHO"] = 1
    finally:
        for thread in threads[:-1]:
            if thread.conn is not None:
                thread.conn.close()
        writer.close()
    identity = dict(
        session_id=session, participant_id=participant, site_id=site, sponsor_id=sponsor
    )
    return dict(
        identity=identity,
        xdf_path=str(writer.path),
        expected_counts=expected,
        capture_chunk_calls=calls,
        capture_seconds=time.monotonic() - capture_start,
    )


def query_checks(database_url: str, capture_result: dict) -> dict:
    from batch.reconciliation.db import fetch_session_meta, query_db_counts
    from batch.reconciliation.xdf import validate_xdf_identity

    identity = capture_result["identity"]
    session = identity["session_id"]
    with psycopg2.connect(database_url) as conn:
        metadata = fetch_session_meta(conn, session, sponsor_id=identity["sponsor_id"])
        counts = query_db_counts(conn, session, sponsor_id=identity["sponsor_id"])
        if counts != capture_result["expected_counts"]:
            raise RuntimeError(f"Reconciled DB counts differ: {counts}")
        xdf_counts = validate_xdf_identity(capture_result["xdf_path"], **identity)
        if xdf_counts != counts:
            raise RuntimeError("XDF and database counts differ after close")
        with conn.cursor() as cur:
            cur.execute("SELECT status::text FROM sessions WHERE id=%s", (session,))
            status = cur.fetchone()[0]
            cur.execute(
                "SELECT COUNT(*) FROM audit_events WHERE session_id=%s "
                "AND event_type='watermark_verified'",
                (session,),
            )
            watermark_count = cur.fetchone()[0]
            cur.execute(
                "SELECT COUNT(*) FROM biosignal_integrity_log WHERE session_id=%s "
                "AND log_type='xdf_reconciliation'",
                (session,),
            )
            reconciliation_logs = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM analysis_runs WHERE session_id=%s", (session,))
            analysis_runs = cur.fetchone()[0]
            row_counts = {}
            for table in ("eeg_samples", "hrv_samples", "eda_samples", "respiration_samples"):
                cur.execute(
                    sql.SQL("SELECT COUNT(*) FROM {} WHERE session_id=%s").format(
                        sql.Identifier(table)
                    ),
                    (session,),
                )
                row_counts[table] = cur.fetchone()[0]
        if status != "closed" or watermark_count != 1 or reconciliation_logs != 1:
            raise RuntimeError(
                "Capture terminal state, watermark, or reconciliation persistence failed"
            )
    return dict(
        status=status,
        watermark_count=watermark_count,
        reconciliation_logs=reconciliation_logs,
        analysis_runs=analysis_runs,
        db_counts=counts,
        raw_row_counts=row_counts,
        canonical_channel_names=list(metadata.eeg_channel_names or ()),
    )


def arc_command(
    identity: dict, artifact: Path, *, sponsor_id: str | None = None, site_id: str | None = None
):
    command = [
        sys.executable,
        "-m",
        "batch.arc",
        "--session-id",
        identity["session_id"],
        "--sponsor-id",
        sponsor_id or identity["sponsor_id"],
        "--site-id",
        site_id or identity["site_id"],
        "--output",
        str(artifact),
    ]
    return subprocess.run(command, capture_output=True, text=True, timeout=180, check=False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("data/backend_smoke") / str(uuid4()))
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    database_url = configure(output)
    from capture.session_close.workflow import run as close_capture

    result = capture(database_url, output)
    identity = result["identity"]
    # Before watermark verification the public batch command must refuse to run.
    early = arc_command(identity, output / "premature.json")
    if early.returncode == 0:
        raise RuntimeError("ARC accepted an unverified capture")
    close_status = close_capture(identity["session_id"], identity["sponsor_id"], result["xdf_path"])
    if close_status != 0:
        raise RuntimeError(f"Capture close failed with exit code {close_status}")
    before = query_checks(database_url, result)
    if before["analysis_runs"] != 0:
        raise RuntimeError("Capture close unexpectedly ran ARC")
    artifacts = [output / "analysis-first.json", output / "analysis-replay.json"]
    for artifact in artifacts:
        completed = arc_command(identity, artifact)
        if completed.returncode:
            raise RuntimeError(
                f"ARC command failed: {completed.stdout[-1500:]} {completed.stderr[-1500:]}"
            )
    if artifacts[0].read_bytes() != artifacts[1].read_bytes():
        raise RuntimeError("Replaying identical capture/config changed the analysis artifact")
    artifact = json.loads(artifacts[0].read_text(encoding="utf-8"))
    denied_sponsor = arc_command(identity, output / "wrong-sponsor.json", sponsor_id=str(uuid4()))
    denied_site = arc_command(identity, output / "wrong-site.json", site_id=str(uuid4()))
    if denied_sponsor.returncode == 0 or denied_site.returncode == 0:
        raise RuntimeError("ARC accepted a foreign sponsor or site")
    after = query_checks(database_url, result)
    if after["analysis_runs"] != 1 or after["raw_row_counts"] != before["raw_row_counts"]:
        raise RuntimeError("Analysis replay duplicated runs or modified raw capture")
    result.update(
        after,
        analysis_id=artifact["analysis_id"],
        event_count=len(artifact["events"]),
        artifact_sha256=hashlib.sha256(artifacts[0].read_bytes()).hexdigest(),
        premature_arc_rejected=True,
        wrong_sponsor_rejected=True,
        wrong_site_rejected=True,
        deterministic_replay=True,
        total_seconds=time.monotonic() - started,
        scope="Offline synthetic input through real capture, XDF, DB, close, and ARC CLI",
    )
    receipt = output / "receipt.json"
    receipt.write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
    print(
        json.dumps(
            {
                "result": "passed",
                "receipt": str(receipt),
                "session_id": identity["session_id"],
                "analysis_id": result["analysis_id"],
                "seconds": round(result["total_seconds"], 2),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
