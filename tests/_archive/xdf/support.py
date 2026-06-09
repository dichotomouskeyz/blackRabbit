"""Binary parsing helpers and fixtures shared across XDF test modules."""

import struct

from capture.xdf.constants import XDF_MAGIC

SESSION_ID = "aaaabbbb-0000-0000-0000-000000000001"
PARTICIPANT_ID = "PARTICIPANT-TEST-01"
SITE_ID = "SITE-TEST-01"
SPONSOR_ID = "SPONSOR-TEST-01"


def read_varlen(data: bytes, offset: int) -> tuple[int, int]:
    """Read an XDF variable-length integer. Returns (value, new_offset)."""
    num_bytes = data[offset]
    offset += 1
    if num_bytes == 1:
        val = struct.unpack_from("<B", data, offset)[0]
    elif num_bytes == 2:
        val = struct.unpack_from("<H", data, offset)[0]
    elif num_bytes == 4:
        val = struct.unpack_from("<I", data, offset)[0]
    elif num_bytes == 8:
        val = struct.unpack_from("<Q", data, offset)[0]
    else:
        raise ValueError(f"unexpected NumLengthBytes: {num_bytes}")
    return val, offset + num_bytes


def iter_chunks(data: bytes):
    """Yield (tag, payload_bytes) for every chunk in an XDF byte string."""
    offset = len(XDF_MAGIC)
    while offset < len(data):
        length, offset = read_varlen(data, offset)
        chunk = data[offset : offset + length]
        offset += length
        tag = struct.unpack_from("<H", chunk, 0)[0]
        payload = chunk[2:]
        yield tag, payload
