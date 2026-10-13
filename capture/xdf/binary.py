import struct
from typing import IO


def _encode_varlen(n: int) -> bytes:
    """XDF variable-length integer: 1-byte prefix gives number of data bytes."""
    if not isinstance(n, int) or isinstance(n, bool) or not 0 <= n <= 0xFFFFFFFFFFFFFFFF:
        raise ValueError("XDF lengths must be unsigned 64-bit integers")
    if n <= 0xFF:
        return b"\x01" + struct.pack("<B", n)
    elif n <= 0xFFFFFFFF:
        return b"\x04" + struct.pack("<I", n)
    else:
        return b"\x08" + struct.pack("<Q", n)


def _write_chunk(f: IO[bytes], tag: int, payload: bytes) -> None:
    """Serialize one XDF chunk to an open binary file handle."""
    tag_bytes = struct.pack("<H", tag)
    full = tag_bytes + payload
    for part in (_encode_varlen(len(full)), full):
        if f.write(part) != len(part):
            raise OSError("short XDF chunk write")


encode_varlen = _encode_varlen
write_chunk = _write_chunk
