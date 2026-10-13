"""ECHO marker stream thread."""

from __future__ import annotations

import threading
from typing import Any, Callable

from capture.echo_handler import db
from capture.echo_handler.inlet import resolve_inlet
from capture.echo_handler.runtime import (
    log_event,
    process_next_sample,
    run_echo_thread,
)
from capture.echo_handler.writer import ECHOWriter
from capture.logger import get_logger

log = get_logger("echo_handler")


def _default_write_failure_prompt(failure_round: int) -> str:
    if failure_round == 1:
        print("\n[ECHO] DB writes are failing. Try again? [y/n]: ", end="", flush=True)
        ans = input().strip().lower()
        return "retry" if ans == "y" else "continue"
    else:
        print(
            "\n[ECHO] Marker events are not writing to the database.\n"
            "  [c] Continue session without ECHO DB writes (XDF still recording)\n"
            "  [x] Cancel session\n"
            "Choice [c/x]: ",
            end="",
            flush=True,
        )
        ans = input().strip().lower()
        return "cancel" if ans == "x" else "continue"


class ECHOThread(threading.Thread):
    """LSL Marker Stream listener — writes proximity state events to echo_events.

    Follows the same buffer-on-drop and reconnect pattern as the biosignal
    _StreamThread in lsl_forwarder. Every marker is written to XDF first,
    then to the DB — so events are never lost even if the DB is temporarily
    unavailable. If the marker stream is not found on startup (e.g. tablet
    not connected), the thread exits after the resolve timeout and biosignal
    capture continues unaffected.
    """

    def __init__(
        self,
        cfg,
        stop_event: threading.Event,
        xdf_writer,
        on_write_failure: Callable[[int], str] | None = None,
    ) -> None:
        super().__init__(name="fwd_echo", daemon=True)
        self._cfg = cfg
        self._stop_event = stop_event
        self._xdf = xdf_writer
        self._writer = ECHOWriter()
        self._on_write_failure = on_write_failure or _default_write_failure_prompt
        self._db_disabled = False

    def handle_write_failure(self, failure_round: int):
        """Prompt the user and act on their response. Returns a new conn or None."""
        response = self._on_write_failure(failure_round)
        if response == "retry":
            log.info("ECHO write failure — user requested retry", extra={"round": failure_round})
            return db.connect_db(self._stop_event)
        elif response == "cancel":
            log.error("ECHO write failure — user cancelled session")
            self._stop_event.set()
            return None
        else:  # "continue"
            log.warning("ECHO write failure — continuing without DB writes (XDF only)")
            self._db_disabled = True
            return None

    def run(self) -> None:
        try:
            self._run()
        except Exception as exc:
            log.error(
                "ECHO thread crashed — biosignal capture unaffected",
                extra={"error": str(exc)},
            )

    def run_loop(self) -> None:
        run_echo_thread(self)

    def process_next_sample(self, inlet, conn):
        return process_next_sample(self, inlet, conn)

    def log_event(self, parsed: dict[str, str], lsl_ts: float) -> None:
        log_event(self._cfg.session_id, parsed, lsl_ts)

    def write_or_buffer(self, conn, row: dict[str, Any]):
        return self._writer.write_or_buffer(conn, row)

    def buffer_row(self, row: dict[str, Any]) -> None:
        self._writer.buffer_row(row)

    def resolve_inlet(self, pylsl):
        return resolve_inlet(pylsl)

    def connect_db(self):
        return db.connect_db(self._stop_event)

    def try_reconnect(self):
        return db.try_reconnect(len(self._writer.buffer))

    def write_row(self, conn, row: dict):
        return self._writer.write_row(conn, row)

    def flush_buffer(self, conn):
        return self._writer.flush_buffer(conn)

    @property
    def _buffer(self):
        return self._writer.buffer

    @property
    def _event_count(self) -> int:
        return self._writer.event_count

    _run = run_loop
    _process_next_sample = process_next_sample
    _log_event = log_event
    _write_or_buffer = write_or_buffer
    _buffer_row = buffer_row
    _resolve_inlet = resolve_inlet
    _connect_db = connect_db
    _try_reconnect = try_reconnect
    _write_row = write_row
    _flush_buffer = flush_buffer
