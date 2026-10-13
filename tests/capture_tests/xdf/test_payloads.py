"""Spec-driven tests for XDF payload builders (xdf-writer.md R-005..R-009).

Phase 2 — biosignal and marker payload encoding. All unit tests; no DB.
Assertions derive from the spec text only.

NOTE (black-box): builder signatures are inferred from the spec's field
ordering. Phase D resolves any signature mismatch in the call sites only.
"""

import struct

from capture.xdf.binary import _encode_varlen
from capture.xdf.samples import _build_biosignal_payload, _build_marker_payload

_STREAM_ID = 1
_TIMESTAMPS = [10.0, 11.0]
_SAMPLES = [[1.0, 2.0], [3.0, 4.0]]


class TestBiosignalPayload:
    """xdf-writer.md — `_build_biosignal_payload`.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    def test_r005_stream_id_first_four_bytes(self):
        payload = _build_biosignal_payload(_STREAM_ID, _TIMESTAMPS, _SAMPLES)
        assert payload[:4] == struct.pack("<I", _STREAM_ID)

    def test_r006_sample_count_varlen_after_wallclock(self):
        payload = _build_biosignal_payload(_STREAM_ID, _TIMESTAMPS, _SAMPLES)
        # 4-byte stream_id + 8-byte wall clock, then varlen sample count.
        assert payload[12:].startswith(_encode_varlen(len(_TIMESTAMPS)))

    def test_r007_timestamps_float64_values_float32(self):
        payload = _build_biosignal_payload(_STREAM_ID, _TIMESTAMPS, _SAMPLES)
        assert struct.pack("<d", 10.0) in payload
        assert struct.pack("<d", 11.0) in payload
        assert struct.pack("<f", 1.0) in payload
        assert struct.pack("<f", 4.0) in payload


class TestMarkerPayload:
    """xdf-writer.md — `_build_marker_payload`.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    def test_r008_sample_count_is_one(self):
        payload = _build_marker_payload(5, 100.0, "ECHO|manual_marker|a|therapist|z")
        # stream_id (4) + wall clock (8) then varlen sample count == 1.
        assert payload[12:].startswith(_encode_varlen(1))

    def test_r009_marker_string_utf8_with_varlen_prefix(self):
        text = "ECHO|manual_marker|a|therapist|z"
        payload = _build_marker_payload(5, 100.0, text)
        text_bytes = text.encode("utf-8")
        assert _encode_varlen(len(text_bytes)) + text_bytes in payload
