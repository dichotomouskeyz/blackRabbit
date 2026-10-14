"""Standard XDF 1.0 sample encoders with pre-write validation."""

import math
import struct

from .binary import encode_varlen


def _timestamp(value: float) -> bytes:
    try:
        finite = math.isfinite(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("XDF timestamps must be finite numbers") from exc
    if not finite:
        raise ValueError("XDF timestamps must be finite")
    return b"\x08" + struct.pack("<d", value)


def _build_marker_payload(stream_id: int, lsl_timestamp: float, marker: str) -> bytes:
    if not isinstance(marker, str):
        raise ValueError("XDF marker must be a string")
    marker_bytes = marker.encode("utf-8")
    return (
        struct.pack("<I", stream_id)
        + encode_varlen(1)
        + _timestamp(lsl_timestamp)
        + encode_varlen(len(marker_bytes))
        + marker_bytes
    )


def _build_biosignal_payload(
    stream_id: int,
    timestamps: list[float],
    samples: list[list[float]],
    *,
    channel_count: int | None = None,
) -> bytes:
    if len(timestamps) != len(samples):
        raise ValueError("XDF sample and timestamp counts must match")
    width = channel_count if channel_count is not None else (len(samples[0]) if samples else 0)
    if samples and width <= 0:
        raise ValueError("XDF samples must have at least one channel")
    buf = bytearray(struct.pack("<I", stream_id) + encode_varlen(len(samples)))
    for ts, sample in zip(timestamps, samples):
        if len(sample) != width:
            raise ValueError(f"XDF sample has {len(sample)} channels; expected {width}")
        buf += _timestamp(ts)
        for value in sample:
            try:
                finite = math.isfinite(value)
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError("XDF signal values must be finite numbers") from exc
            if not finite:
                raise ValueError("XDF signal values must be finite")
            try:
                buf += struct.pack("<f", value)
            except (OverflowError, struct.error) as exc:
                raise ValueError("XDF signal value is outside float32 range") from exc
    return bytes(buf)
