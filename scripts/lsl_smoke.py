"""Run real local LSL simulators, capture, orderly shutdown and XDF reconciliation.

Uses an already-migrated isolated database, with identical DATABASE_URL and
TEST_DATABASE_URL. Creates unique synthetic sessions and stream names; it never
clears tables or changes the schema. Logs and the receipt stay under .pytest_tmp.
This short run verifies transport/lifecycle, not physiological inference.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import psycopg2

from scripts.backend_smoke import configure

ROOT = Path(__file__).resolve().parents[1]


def run_capture(output: Path, duration: float) -> dict:
    database_url = configure(output)
    suffix = uuid4().hex
    for key in ("EEG", "HRV", "EDA", "RESPIRATION", "MARKER"):
        os.environ[f"LSL_STREAM_{key}"] = f"blackRabbit_smoke_{suffix}_{key}"
    os.environ.update(
        LSL_CHUNK_EEG="100",
        LSL_CHUNK_HRV="1",
        LSL_CHUNK_EDA="4",
        LSL_CHUNK_RESPIRATION="4",
        LSL_RESOLVE_TIMEOUT="8",
    )

    # Every application import follows environment configuration.
    from batch.reconciliation.db import query_db_counts
    from batch.reconciliation.xdf import inspect_xdf, validate_xdf_identity
    from capture.control import request_stop
    from capture.session_close.workflow import run as close_capture
    from capture.session_init.workflow import create_session

    participant, site, sponsor = (str(uuid4()) for _ in range(3))
    session = create_session("psilocybin", site, sponsor, participant, capture_source="simulated")
    identity = dict(
        session_id=session, participant_id=participant, site_id=site, sponsor_id=sponsor
    )
    children: list[subprocess.Popen] = []
    log_handles = []
    forwarder = None

    def start(name: str, module: str, *args: str) -> subprocess.Popen:
        handle = (output / f"{name}.log").open("w", encoding="utf-8")
        log_handles.append(handle)
        flags = 0
        if os.name == "nt":
            flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        process = subprocess.Popen(
            [sys.executable, "-m", module, *args],
            cwd=ROOT,
            env=dict(os.environ),
            stdout=handle,
            stderr=subprocess.STDOUT,
            creationflags=flags,
        )
        children.append(process)
        return process

    start_time = time.monotonic()
    try:
        start("synthetic-board", "capture.synthetic_board")
        start(
            "markers", "capture.marker_simulator", "--min-interval", "0.3", "--max-interval", "0.5"
        )
        # Outlets start independently; the actual forwarder resolves them through LSL.
        forwarder = start(
            "forwarder",
            "capture.forwarder",
            "--session-id",
            session,
            "--participant-id",
            participant,
            "--site-id",
            site,
            "--sponsor-id",
            sponsor,
        )
        ready_deadline = time.monotonic() + 20
        with contextlib.closing(psycopg2.connect(database_url)) as conn:
            while True:
                if any(child.poll() is not None for child in children):
                    raise RuntimeError("A capture subprocess exited during startup; inspect logs")
                counts = query_db_counts(conn, session, sponsor, site_id=site)
                conn.rollback()
                if all(
                    counts.get(stream, 0) > 0
                    for stream in ("EEG", "HRV", "EDA", "Respiration", "ECHO")
                ):
                    break
                if time.monotonic() >= ready_deadline:
                    raise TimeoutError("All five live LSL streams did not reach the database")
                time.sleep(0.25)
        started_counts = counts
        ready_at = time.monotonic()
        capture_deadline = ready_at + duration
        while time.monotonic() < capture_deadline:
            if any(child.poll() is not None for child in children):
                raise RuntimeError("A capture subprocess exited before the stop request")
            time.sleep(min(0.25, max(0, capture_deadline - time.monotonic())))

        request_stop(session)
        if forwarder.wait(timeout=15) != 0:
            raise RuntimeError("Forwarder did not stop cleanly; inspect forwarder.log")
        paths = list((output / "xdf").glob(f"session_{session}_*.xdf"))
        if len(paths) != 1:
            raise RuntimeError("Expected exactly one XDF segment for this capture")
        path = paths[0]
        xdf_counts = validate_xdf_identity(path, session, sponsor, participant, site)
        if inspect_xdf(path).format != "xdf-1.0":
            raise RuntimeError("Capture did not produce standard XDF")
        with contextlib.closing(psycopg2.connect(database_url)) as conn:
            captured_counts = query_db_counts(conn, session, sponsor, site_id=site)
        if captured_counts != xdf_counts:
            raise RuntimeError("Clean forwarder shutdown left DB/XDF counts unequal")
        if close_capture(session, sponsor, path) != 0:
            raise RuntimeError("Session reconciliation did not verify the capture")
        with contextlib.closing(psycopg2.connect(database_url)) as conn:
            final_counts = query_db_counts(conn, session, sponsor, site_id=site)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT status::text FROM sessions WHERE id=%s AND sponsor_id=%s "
                    "AND site_id=%s",
                    (session, sponsor, site),
                )
                status_row = cur.fetchone()
                if status_row is None:
                    raise RuntimeError("Captured session is missing from its expected tenant")
                status = status_row[0]
                cur.execute(
                    "SELECT event_type FROM audit_events WHERE session_id=%s "
                    "AND event_type IN ('watermark_verified','watermark_failed')",
                    (session,),
                )
                watermark_events = [row[0] for row in cur.fetchall()]
        if status != "closed" or watermark_events != ["watermark_verified"]:
            raise RuntimeError("Close did not persist one verified terminal watermark")
        if final_counts != xdf_counts:
            raise RuntimeError("Post-close DB counts differ from XDF")
        return dict(
            passed=True,
            identity=identity,
            xdf_path=str(path),
            xdf_format="xdf-1.0",
            capture_duration_s=duration,
            elapsed_s=round(time.monotonic() - start_time, 2),
            counts_after_startup=started_counts,
            final_counts=final_counts,
            xdf_counts=xdf_counts,
            session_status=status,
            watermark_events=watermark_events,
            forwarder_exit_code=forwarder.returncode,
            stop_method="capture.control.request_stop",
            evidence="real local LSL simulators and forwarder subprocess; synthetic data only",
        )
    finally:
        if forwarder is not None and forwarder.poll() is None:
            request_stop(session)
            try:
                forwarder.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass
        # These handles identify only processes this script created.
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=3)
        for handle in log_handles:
            handle.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=float, default=12.0)
    parser.add_argument(
        "--output", type=Path, default=ROOT / ".pytest_tmp" / f"lsl-smoke-{uuid4().hex[:8]}"
    )
    args = parser.parse_args()
    if not 10 <= args.duration <= 20:
        parser.error("duration must be between 10 and 20 seconds")
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / ".pytest_tmp"):
        parser.error("output must be inside the repository .pytest_tmp directory")
    output.mkdir(parents=True, exist_ok=False)
    receipt = output / "receipt.json"
    try:
        with (output / "orchestrator.log").open("w", encoding="utf-8") as log_file:
            with contextlib.redirect_stdout(log_file), contextlib.redirect_stderr(log_file):
                result = run_capture(output, args.duration)
    except Exception as error:
        result = dict(passed=False, error=type(error).__name__, message=str(error))
        receipt.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(dict(passed=False, receipt=str(receipt), error=str(error))), flush=True)
        raise SystemExit(1) from error
    receipt.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(dict(passed=True, receipt=str(receipt), counts=result["final_counts"])),
        flush=True,
    )


if __name__ == "__main__":
    main()
