"""Local process control helpers for capture subprocesses."""

from pathlib import Path

from config import settings


def stop_request_path(session_id: str) -> Path:
    return settings.LOG_DIR / "control" / f"stop_{session_id}.signal"


def clear_stop_request(session_id: str) -> None:
    path = stop_request_path(session_id)
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def request_stop(session_id: str) -> Path:
    path = stop_request_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("stop\n", encoding="utf-8")
    return path


def stop_requested(session_id: str) -> bool:
    return stop_request_path(session_id).exists()
