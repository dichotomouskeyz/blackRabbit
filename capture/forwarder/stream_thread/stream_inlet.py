"""LSL inlet resolution for forwarder streams."""

import pylsl

from capture.logger import get_logger
from config import settings

log = get_logger("lsl_forwarder")


def resolve_inlet(thread) -> pylsl.StreamInlet | None:
    log.info(
        f"{thread._stream_type} resolving stream",
        extra={
            "stream_name": thread._stream_name,
            "timeout_s": settings.LSL_RESOLVE_TIMEOUT,
        },
    )
    streams = pylsl.resolve_byprop(
        "name", thread._stream_name, timeout=settings.LSL_RESOLVE_TIMEOUT
    )
    if not streams:
        return None
    inlet = pylsl.StreamInlet(streams[0], max_buflen=int(settings.LSL_MAX_BUFSIZE))
    info = inlet.info()
    log.info(
        f"{thread._stream_type} inlet connected",
        extra={
            "stream_name": info.name(),
            "stream_type": info.type(),
            "channels": info.channel_count(),
            "nominal_rate_hz": info.nominal_srate(),
            "source_id": info.source_id(),
            "simulation_mode": settings.SIMULATION_MODE,
        },
    )
    return inlet
