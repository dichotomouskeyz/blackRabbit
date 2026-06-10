"""Spec-driven tests for XDF binary encoding (xdf-writer.md R-001..R-004).

Phase 2 — XDF chunk/varlen encoding. All unit tests; no DB.
Assertions derive from the spec text only.
"""

import io

import pytest

from capture.xdf.binary import _encode_varlen, _write_chunk


class TestVarlenEncoding:
    """xdf-writer.md — binary encoding (varlen).

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    @pytest.mark.parametrize("n", [0, 1, 200, 255])
    def test_r001_one_byte_range(self, n):
        out = _encode_varlen(n)
        assert out[:1] == b"\x01"
        assert len(out) == 2
        assert out[1] == n

    @pytest.mark.parametrize("n", [256, 1000, 65535])
    def test_r002_two_byte_range(self, n):
        out = _encode_varlen(n)
        assert out[:1] == b"\x02"
        assert len(out) == 3
        assert out[1:] == n.to_bytes(2, "little")

    @pytest.mark.parametrize("n", [65536, 1_000_000, 4294967295])
    def test_r003_four_byte_range(self, n):
        out = _encode_varlen(n)
        assert out[:1] == b"\x04"
        assert len(out) == 5
        assert out[1:] == n.to_bytes(4, "little")


class TestWriteChunk:
    """xdf-writer.md — `_write_chunk` ordering.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    def test_r004_chunk_layout(self):
        buf = io.BytesIO()
        tag = 3
        payload = b"\xaa\xbb\xcc"
        _write_chunk(buf, tag, payload)
        tag_bytes = tag.to_bytes(2, "little")
        expected = _encode_varlen(len(tag_bytes + payload)) + tag_bytes + payload
        assert buf.getvalue() == expected
