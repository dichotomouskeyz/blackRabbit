"""Approved standard XDF sample-layout contract, regenerated 2026-10-13."""

import struct

from capture.xdf.samples import _build_biosignal_payload, _build_marker_payload


def test_r005_r006_r007_exact_standard_numeric_payload():
    payload = _build_biosignal_payload(1, [10.0, 11.0], [[1.0, 2.0], [3.0, 4.0]])
    expected = (
        struct.pack("<I", 1)
        + b"\x01\x02"
        + b"\x08"
        + struct.pack("<dff", 10.0, 1.0, 2.0)
        + b"\x08"
        + struct.pack("<dff", 11.0, 3.0, 4.0)
    )
    assert payload == expected


def test_r008_r009_exact_standard_marker_payload():
    text = "marker \u03b1"
    raw = text.encode("utf-8")
    payload = _build_marker_payload(5, 100.0, text)
    expected = struct.pack("<I", 5) + b"\x01\x01\x08" + struct.pack("<d", 100.0)
    expected += bytes((1, len(raw))) + raw
    assert payload == expected
