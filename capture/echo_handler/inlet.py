"""LSL inlet resolution for ECHO marker streams."""

from capture.logger import get_logger
from config import settings

log = get_logger("echo_handler")


def resolve_inlet(pylsl):
    log.info(
        "ECHO resolving marker stream",
        extra={
            "stream_name": settings.LSL_STREAM_MARKER,
            "timeout_s": settings.LSL_RESOLVE_TIMEOUT,
        },
    )
    streams = pylsl.resolve_byprop(
        "name", settings.LSL_STREAM_MARKER, timeout=settings.LSL_RESOLVE_TIMEOUT
    )
    if not streams:
        return None
    inlet = pylsl.StreamInlet(streams[0])
    info = inlet.info()
    log.info(
        "ECHO inlet connected",
        extra={
            "stream_name": info.name(),
            "stream_type": info.type(),
            "simulation_mode": settings.SIMULATION_MODE,
        },
    )
    return inlet
