import struct
import time

from .binary import _encode_varlen


def _build_marker_payload(stream_id: int, lsl_timestamp: float, marker: str) -> bytes:
    """Encode one ECHO proximity marker into an XDF samples chunk payload."""
    marker_bytes = marker.encode("utf-8")
    buf = bytearray()
    buf += struct.pack("<I", stream_id)
    buf += struct.pack("<d", time.time())
    buf += _encode_varlen(1)  # one sample
    buf += struct.pack("<d", lsl_timestamp)
    buf += _encode_varlen(len(marker_bytes))
    buf += marker_bytes
    return bytes(buf)


def _build_biosignal_payload(
    stream_id: int,
    timestamps: list[float],
    samples: list[list[float]],
) -> bytes:
    """Encode one chunk of biosignal samples into an XDF samples chunk payload."""
    buf = bytearray()
    buf += struct.pack("<I", stream_id)
    buf += struct.pack("<d", time.time())
    buf += _encode_varlen(len(timestamps))
    for ts, sample in zip(timestamps, samples):
        buf += struct.pack("<d", ts)
        for val in sample:
            buf += struct.pack("<f", float(val))
    return bytes(buf)
