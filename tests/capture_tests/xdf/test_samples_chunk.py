"""XDF samples chunk encoding tests."""

import struct

import pytest

from capture.xdf import _STREAM_IDS, _TAG_SAMPLES
from tests.capture_tests.xdf.support import _iter_chunks, _read_varlen


class TestSamplesChunk:
    def test_samples_chunk_tag(self, writer):
        writer.write_samples("HRV", [[857.0]], [200.0])
        writer.close()
        raw = writer.path.read_bytes()
        tags = [t for t, _ in _iter_chunks(raw)]
        assert _TAG_SAMPLES in tags

    def test_samples_chunk_stream_id(self, writer):
        writer.write_samples("EDA", [[5.0]], [300.0])
        writer.close()
        raw = writer.path.read_bytes()
        for tag, payload in _iter_chunks(raw):
            if tag == _TAG_SAMPLES:
                sid = struct.unpack_from("<I", payload, 0)[0]
                assert sid == _STREAM_IDS["EDA"]
                break

    def test_samples_chunk_num_samples_encoded(self, writer):
        samples = [[1.0] * 8, [2.0] * 8, [3.0] * 8]
        timestamps = [100.0, 100.004, 100.008]
        writer.write_samples("EEG", samples, timestamps)
        writer.close()
        raw = writer.path.read_bytes()
        for tag, payload in _iter_chunks(raw):
            if tag == _TAG_SAMPLES:
                offset = 4 + 8
                num_samples, _ = _read_varlen(payload, offset)
                assert num_samples == 3
                break

    def test_samples_chunk_timestamps_recoverable(self, writer):
        ts_in = [100.0, 100.004]
        writer.write_samples("HRV", [[857.0], [860.0]], ts_in)
        writer.close()
        raw = writer.path.read_bytes()
        for tag, payload in _iter_chunks(raw):
            if tag == _TAG_SAMPLES:
                sid = struct.unpack_from("<I", payload, 0)[0]
                if sid != _STREAM_IDS["HRV"]:
                    continue
                offset = 4 + 8
                num_samples, offset = _read_varlen(payload, offset)
                ts_out = []
                for _ in range(num_samples):
                    ts = struct.unpack_from("<d", payload, offset)[0]
                    ts_out.append(ts)
                    offset += 8 + 4  # timestamp + 1 float32 channel
                assert ts_out == pytest.approx(ts_in)
                break

    def test_eeg_float32_values_recoverable(self, writer):
        ch_values = [1.5, 2.5, 3.5, 4.5, 5.5, 6.5, 7.5, 8.5]
        writer.write_samples("EEG", [ch_values], [50.0])
        writer.close()
        raw = writer.path.read_bytes()
        for tag, payload in _iter_chunks(raw):
            if tag == _TAG_SAMPLES:
                sid = struct.unpack_from("<I", payload, 0)[0]
                if sid != _STREAM_IDS["EEG"]:
                    continue
                offset = 4 + 8
                _, offset = _read_varlen(payload, offset)
                offset += 8  # skip timestamp
                recovered = list(struct.unpack_from("<8f", payload, offset))
                assert recovered == pytest.approx(ch_values, abs=1e-5)
                break
