"""Shared structured logging helper for all blackRabbit 1a processes.

Every process that runs during a session — lsl_forwarder, safety_monitor,
sqi_monitor, batch jobs — imports this module and calls get_logger() once
at startup. All log output is JSON, one object per line, written to both
stdout and a rotating file under LOG_DIR.

Usage:
    from capture.logger import get_logger, set_session_id

    log = get_logger("lsl_forwarder")

    # Call once the session UUID is known (nullable until then)
    set_session_id("a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11")

    log.info("EEG stream connected")
    log.warning("clock drift exceeded threshold", extra={"offset_ms": 42.1})
    log.error("watchdog timeout on EDA stream")

Every line written to disk or stdout has exactly this shape:
    {
        "timestamp": "2026-05-05T14:32:01.123456+00:00",
        "process":   "lsl_forwarder",
        "level":     "INFO",
        "session_id": "a0eebc99-...",   # null until set_session_id() is called
        "message":   "EEG stream connected",
        ... any extra fields passed via extra={}
    }
"""

import json
import logging
import logging.handlers
import sys
from datetime import datetime, timezone
from pathlib import Path

from config import settings

# ---------------------------------------------------------------------------
# Module-level session_id — shared across all loggers in this process.
# Set once via set_session_id() when the session UUID is known.
# ---------------------------------------------------------------------------
_session_id: str | None = None


def set_session_id(sid: str | None) -> None:
    """Set the session_id injected into every subsequent log record."""
    global _session_id
    _session_id = sid


# ---------------------------------------------------------------------------
# JSON formatter
# ---------------------------------------------------------------------------
# Standard LogRecord fields that are never forwarded as extra payload.
_RECORD_BUILTINS = frozenset(
    {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "taskName",
        "process",
        "processName",
        "message",
        "asctime",
    }
)


class _JsonFormatter(logging.Formatter):
    def __init__(self, process_name: str) -> None:
        super().__init__()
        self._process_name = process_name

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "process_name": self._process_name,
            "level": record.levelname,
            "session_id": _session_id,
            "message": record.getMessage(),
        }

        # Forward only caller-supplied extra fields, not internal LogRecord attrs
        for key, val in record.__dict__.items():
            if key not in _RECORD_BUILTINS and not key.startswith("_"):
                payload[key] = val

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload)


# ---------------------------------------------------------------------------
# Logger registry — one logger per process name, created once
# ---------------------------------------------------------------------------
_loggers: dict[str, logging.Logger] = {}


def get_logger(process_name: str) -> logging.Logger:
    """Return a JSON-structured logger for the given process name.

    Safe to call multiple times with the same name — returns the same
    logger instance without adding duplicate handlers.
    """
    if process_name in _loggers:
        return _loggers[process_name]

    logger = logging.getLogger(f"consensai.{process_name}")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    formatter = _JsonFormatter(process_name)

    # stderr handler — logs go to stderr so stdout stays clean for program output
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(formatter)
    logger.addHandler(stderr_handler)

    try:
        log_dir: Path = settings.LOG_DIR
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"{process_name}.log"
        file_handler = logging.handlers.RotatingFileHandler(
            log_path,
            maxBytes=10 * 1024 * 1024,  # 10 MB per file
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except AttributeError:
        pass  # settings not fully initialized — stdout only

    _loggers[process_name] = logger
    return logger
