"""Forwarder process runtime.

`ForwarderEngine` owns the capture lifecycle as four explicit phases so an
external manager (CLI today; watchdog/UI supervisor later) can drive them
separately:

    engine = ForwarderEngine(cfg)
    engine.prepare()            # preflight + session config (no streams yet)
    engine.start()              # XDF init, signal handlers, thread spawn
    engine.run_until_stopped()  # block until stop is requested
    engine.stop()               # join threads, close XDF, surface fatal errors

`run_forwarder` remains the thin one-call wrapper used by the CLI.
"""

import signal
import threading
import time

import psycopg2

from capture.control import clear_stop_request, stop_requested
from capture.forwarder.models import PAYLOAD_SCHEMA_VERSION, SessionConfig
from capture.forwarder.preflight import load_session_config, verify_session_ready
from capture.forwarder.stream_thread.streams import build_stream_threads
from capture.logger import get_logger, set_session_id
from capture.session_lock import acquire_session_lock
from capture.xdf.writer import XDFWriter
from config import settings

log = get_logger("lsl_forwarder")


class ForwarderEngine:
    """State-managed capture lifecycle for one session."""

    def __init__(self, cfg: SessionConfig) -> None:
        self.cfg = cfg
        self.stop_event = threading.Event()
        self.xdf: XDFWriter | None = None
        self.threads: list[threading.Thread] = []
        self.session_conn = None

    def prepare(self) -> None:
        """Validate the session and load config — no streams are touched."""
        set_session_id(self.cfg.session_id)
        self.session_conn = psycopg2.connect(settings.DATABASE_URL)
        acquire_session_lock(self.session_conn, self.cfg.session_id)
        verify_session_ready(self.cfg, self.session_conn)
        self.cfg = load_session_config(self.cfg, self.session_conn)
        clear_stop_request(self.cfg.session_id)

        log.info(
            "forwarder starting",
            extra={
                "schema_version": PAYLOAD_SCHEMA_VERSION,
                "session_id": self.cfg.session_id,
                "participant_id": self.cfg.participant_id,
                "site_id": self.cfg.site_id,
                "sponsor_id": self.cfg.sponsor_id,
                "device_id": settings.DEVICE_ID,
                "simulation_mode": settings.SIMULATION_MODE,
            },
        )

    def start(self) -> None:
        """Open the XDF backup, register stop signals, and spawn stream threads."""
        self.xdf = XDFWriter(
            session_id=self.cfg.session_id,
            participant_id=self.cfg.participant_id,
            site_id=self.cfg.site_id,
            sponsor_id=self.cfg.sponsor_id,
            eeg_channel_names=self.cfg.eeg_channel_names,
        )

        signal.signal(signal.SIGTERM, lambda sig, frame: self.stop_event.set())
        if hasattr(signal, "SIGBREAK"):
            signal.signal(signal.SIGBREAK, lambda sig, frame: self.stop_event.set())

        self.threads = build_stream_threads(self.cfg, self.stop_event, self.xdf)
        for thread in self.threads:
            thread.start()
        log.info("all forwarder threads started - press Ctrl+C to stop")

    def run_until_stopped(self) -> None:
        """Block until SIGTERM/Ctrl+C or a stop-request file appears."""
        try:
            while not self.stop_event.is_set():
                if stop_requested(self.cfg.session_id):
                    log.info("stop request file detected - flushing buffers")
                    self.stop_event.set()
                    break
                time.sleep(1)
        except KeyboardInterrupt:
            log.info("shutdown requested - flushing buffers")
            self.stop_event.set()

    def stop(self) -> None:
        """Join threads, close the XDF file, and surface any fatal thread error."""
        self.stop_event.set()
        try:
            join_threads(self.threads)
        finally:
            try:
                if self.xdf is not None:
                    self.xdf.close()
            finally:
                if self.session_conn is not None:
                    self.session_conn.close()
                    self.session_conn = None
        raise_if_thread_failed(self.threads)
        log.info("forwarder stopped")


def run_forwarder(cfg: SessionConfig) -> None:
    engine = ForwarderEngine(cfg)
    try:
        engine.prepare()
        engine.start()
        engine.run_until_stopped()
    finally:
        engine.stop()


def join_threads(threads: list[threading.Thread], timeout_s: float = 10.0) -> None:
    for thread in threads:
        thread.join(timeout=timeout_s)
        if thread.is_alive():
            log.error(
                "forwarder thread did not stop after join timeout",
                extra={
                    "thread_name": thread.name,
                    "join_timeout_s": timeout_s,
                },
            )


def raise_if_thread_failed(threads: list[threading.Thread]) -> None:
    fatal_threads = [
        thread for thread in threads if getattr(thread, "fatal_error", None) is not None
    ]
    if not fatal_threads:
        return

    first = fatal_threads[0]
    error = getattr(first, "fatal_error")
    log.critical(
        "forwarder stopped after fatal stream thread error",
        extra={
            "thread_name": first.name,
            "fatal_thread_count": len(fatal_threads),
            "error": str(error),
        },
    )
    raise RuntimeError(f"forwarder failed after fatal stream thread error: {error}") from error
