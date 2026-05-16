"""XDF writer lifecycle and statistics tests."""

import struct

from capture.xdf import _STREAM_IDS, _TAG_STREAM_FOOTER
from tests.capture_tests.xdf.support import _iter_chunks


class TestStatistics:
    def test_sample_counts_accumulate(self, writer):
        writer.write_samples("EEG", [[0.0] * 8] * 25, list(range(25)))
        writer.write_samples("EEG", [[0.0] * 8] * 25, list(range(25, 50)))
        assert writer.sample_counts["EEG"] == 50

    def test_sample_counts_per_stream_independent(self, writer):
        writer.write_samples("EEG", [[0.0] * 8] * 10, list(range(10)))
        writer.write_samples("HRV", [[800.0]] * 3, [1.0, 2.0, 3.0])
        counts = writer.sample_counts
        assert counts["EEG"] == 10
        assert counts["HRV"] == 3
        assert counts["EDA"] == 0

    def test_footer_xml_contains_sample_count(self, writer):
        writer.write_samples("Respiration", [[0.5]] * 7, list(range(7)))
        writer.close()
        raw = writer.path.read_bytes()
        for tag, payload in _iter_chunks(raw):
            if tag == _TAG_STREAM_FOOTER:
                sid = struct.unpack_from("<I", payload, 0)[0]
                if sid == _STREAM_IDS["Respiration"]:
                    xml = payload[4:].decode("utf-8")
                    assert "<sample_count>7</sample_count>" in xml
                    break

    def test_close_is_idempotent(self, writer):
        writer.close()
        writer.close()  # must not raise

    def test_write_after_close_is_noop(self, writer):
        writer.close()
        size_before = writer.path.stat().st_size
        writer.write_samples("EEG", [[1.0] * 8], [999.0])
        size_after = writer.path.stat().st_size
        assert size_after == size_before
