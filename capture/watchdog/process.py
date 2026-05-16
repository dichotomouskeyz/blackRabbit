"""Forwarder process management for the watchdog."""

import os
import signal
import subprocess  # nosec B404
import time

from capture.control import clear_stop_request, request_stop
from capture.logger import get_logger
from capture.watchdog import models

log = get_logger("watchdog")


def start_forwarder(forwarder_cmd: list[str]) -> subprocess.Popen:
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    return subprocess.Popen(forwarder_cmd, creationflags=creationflags)  # nosec B603


def stop_forwarder(process: subprocess.Popen, session_id: str) -> None:
    if process.poll() is not None:
        return

    stop_path = request_stop(session_id)
    log.info(
        "forwarder stop requested",
        extra={"session_id": session_id, "stop_request_path": str(stop_path)},
    )
    try:
        process.wait(timeout=models.GRACEFUL_SHUTDOWN_TIMEOUT_S)
        clear_stop_request(session_id)
        return
    except subprocess.TimeoutExpired:
        log.warning(
            "forwarder did not stop from stop request; sending OS signal",
            extra={"timeout_s": models.GRACEFUL_SHUTDOWN_TIMEOUT_S, "pid": process.pid},
        )

    if os.name == "nt":
        ctrl_break = getattr(signal, "CTRL_BREAK_EVENT", None)
        if ctrl_break is not None:
            try:
                os.kill(process.pid, ctrl_break)
            except OSError as exc:
                log.warning(
                    "failed to send CTRL_BREAK_EVENT to forwarder",
                    extra={"error": str(exc), "pid": process.pid},
                )
        else:
            process.terminate()
    else:
        process.terminate()

    try:
        process.wait(timeout=models.GRACEFUL_SHUTDOWN_TIMEOUT_S)
        clear_stop_request(session_id)
    except subprocess.TimeoutExpired:
        log.error(
            "forwarder did not stop gracefully; killing process",
            extra={"timeout_s": models.GRACEFUL_SHUTDOWN_TIMEOUT_S, "pid": process.pid},
        )
        process.kill()
        process.wait()
        clear_stop_request(session_id)


def wait_for_forwarder(process: subprocess.Popen) -> int:
    while process.poll() is None:
        time.sleep(models.PROCESS_POLL_INTERVAL_S)
    return int(process.returncode or 0)
