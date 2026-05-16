import struct
from typing import IO


def _encode_varlen(n: int) -> bytes:
    """XDF variable-length integer: 1-byte prefix gives number of data bytes."""
    if n <= 0xFF:
        return b"\x01" + struct.pack("<B", n)
    elif n <= 0xFFFF:
        return b"\x02" + struct.pack("<H", n)
    elif n <= 0xFFFFFFFF:
        return b"\x04" + struct.pack("<I", n)
    else:
        return b"\x08" + struct.pack("<Q", n)


def _write_chunk(f: IO[bytes], tag: int, payload: bytes) -> None:
    """Serialize one XDF chunk to an open binary file handle."""
    tag_bytes = struct.pack("<H", tag)
    full = tag_bytes + payload
    f.write(_encode_varlen(len(full)))
    f.write(full)
