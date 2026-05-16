"""Forwarder process runtime."""

import signal
import threading
import time

from capture.control import clear_stop_request, stop_requested
from capture.forwarder.models import PAYLOAD_SCHEMA_VERSION, SessionConfig
from capture.forwarder.preflight import _verify_session_ready
from capture.forwarder.stream_thread import _build_stream_threads
from capture.logger import get_logger, set_session_id
from capture.xdf import XDFWriter
from config import settings

log = get_logger("lsl_forwarder")


def run_forwarder(cfg: SessionConfig) -> None:
    set_session_id(cfg.session_id)
    clear_stop_request(cfg.session_id)
    _verify_session_ready(cfg)

    log.info(
        "forwarder starting",
        extra={
            "schema_version": PAYLOAD_SCHEMA_VERSION,
            "session_id": cfg.session_id,
            "participant_id": cfg.participant_id,
            "site_id": cfg.site_id,
            "sponsor_id": cfg.sponsor_id,
            "device_id": settings.DEVICE_ID,
            "simulation_mode": settings.SIMULATION_MODE,
        },
    )

    xdf = XDFWriter(
        session_id=cfg.session_id,
        site_id=cfg.site_id,
        sponsor_id=cfg.sponsor_id,
    )

    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda sig, frame: stop.set())
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, lambda sig, frame: stop.set())

    threads = _build_stream_threads(cfg, stop, xdf)
    for thread in threads:
        thread.start()

    log.info("all forwarder threads started - press Ctrl+C to stop")
    _wait_for_stop(cfg.session_id, stop)

    for thread in threads:
        thread.join(timeout=10.0)

    xdf.close()
    log.info("forwarder stopped")


def _wait_for_stop(session_id: str, stop: threading.Event) -> None:
    try:
        while not stop.is_set():
            if stop_requested(session_id):
                log.info("stop request file detected - flushing buffers")
                stop.set()
                break
            time.sleep(1)
    except KeyboardInterrupt:
        log.info("shutdown requested - flushing buffers")
        stop.set()
