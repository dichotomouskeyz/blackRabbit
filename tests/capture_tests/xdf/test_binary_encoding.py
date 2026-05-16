"""_encode_varlen unit tests."""

import struct

from capture.xdf import _encode_varlen


class TestEncodeVarlen:
    def test_small(self):
        assert _encode_varlen(5) == b"\x01\x05"

    def test_255(self):
        assert _encode_varlen(255) == b"\x01\xff"

    def test_256(self):
        assert _encode_varlen(256) == b"\x02\x00\x01"

    def test_65535(self):
        assert _encode_varlen(65535) == b"\x02\xff\xff"

    def test_65536(self):
        result = _encode_varlen(65536)
        assert result[0:1] == b"\x04"
        assert struct.unpack_from("<I", result, 1)[0] == 65536
