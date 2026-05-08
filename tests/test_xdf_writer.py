"""Tests for capture/xdf_writer.py.

Verifies XDF binary structure, thread safety, and session lifecycle without
requiring pyxdf — all checks are done against the raw bytes on disk.
"""

import struct
import threading

import pytest

from capture.xdf_writer import (
    XDFWriter,
    _TAG_FILE_HEADER,
    _TAG_SAMPLES,
    _TAG_STREAM_FOOTER,
    _TAG_STREAM_HEADER,
    _XDF_MAGIC,
    _encode_varlen,
    _STREAM_IDS,
)

# ---------------------------------------------------------------------------
# Helpers for parsing XDF bytes
# ---------------------------------------------------------------------------


def _read_varlen(data: bytes, offset: int) -> tuple[int, int]:
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


def _iter_chunks(data: bytes):
    """Yield (tag, payload_bytes) for every chunk in an XDF byte string."""
    offset = len(_XDF_MAGIC)  # skip magic
    while offset < len(data):
        length, offset = _read_varlen(data, offset)
        chunk = data[offset : offset + length]
        offset += length
        tag = struct.unpack_from("<H", chunk, 0)[0]
        payload = chunk[2:]
        yield tag, payload


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SESSION_ID = "aaaabbbb-0000-0000-0000-000000000001"
SITE_ID = "SITE-TEST-01"
SPONSOR_ID = "SPONSOR-TEST-01"


@pytest.fixture()
def writer(tmp_path, monkeypatch):
    """XDFWriter that writes to a temp directory."""
    import config.settings as s

    monkeypatch.setattr(s, "XDF_BACKUP_DIR", tmp_path)
    w = XDFWriter(SESSION_ID, SITE_ID, SPONSOR_ID)
    yield w
    if not w._closed:
        w.close()


@pytest.fixture()
def closed_writer(writer):
    writer.close()
    return writer


# ---------------------------------------------------------------------------
# _encode_varlen unit tests
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# File structure tests
# ---------------------------------------------------------------------------


class TestFileStructure:
    def test_starts_with_magic(self, writer):
        writer.close()
        raw = writer.path.read_bytes()
        assert raw[:4] == _XDF_MAGIC

    def test_has_file_header_chunk(self, writer):
        writer.close()
        raw = writer.path.read_bytes()
        tags = [tag for tag, _ in _iter_chunks(raw)]
        assert _TAG_FILE_HEADER in tags

    def test_has_four_stream_headers(self, writer):
        writer.close()
        raw = writer.path.read_bytes()
        stream_header_count = sum(
            1 for t, _ in _iter_chunks(raw) if t == _TAG_STREAM_HEADER
        )
        assert stream_header_count == 5

    def test_stream_header_ids_are_correct(self, writer):
        writer.close()
        raw = writer.path.read_bytes()
        found_ids = set()
        for tag, payload in _iter_chunks(raw):
            if tag == _TAG_STREAM_HEADER:
                stream_id = struct.unpack_from("<I", payload, 0)[0]
                found_ids.add(stream_id)
        assert found_ids == set(_STREAM_IDS.values())

    def test_stream_header_xml_contains_session_id(self, writer):
        writer.close()
        raw = writer.path.read_bytes()
        for tag, payload in _iter_chunks(raw):
            if tag == _TAG_STREAM_HEADER:
                xml = payload[4:].decode("utf-8")
                assert SESSION_ID in xml

    def test_stream_header_xml_contains_site_and_sponsor(self, writer):
        writer.close()
        raw = writer.path.read_bytes()
        for tag, payload in _iter_chunks(raw):
            if tag == _TAG_STREAM_HEADER:
                xml = payload[4:].decode("utf-8")
                assert SITE_ID in xml
                assert SPONSOR_ID in xml

    def test_has_four_stream_footers_on_close(self, writer):
        writer.close()
        raw = writer.path.read_bytes()
        footer_count = sum(1 for t, _ in _iter_chunks(raw) if t == _TAG_STREAM_FOOTER)
        assert footer_count == 5

    def test_file_grows_after_write_samples(self, writer):
        size_before = writer.path.stat().st_size
        writer.write_samples("EEG", [[1.0] * 8, [2.0] * 8], [100.0, 100.004])
        size_after = writer.path.stat().st_size
        assert size_after > size_before


# ---------------------------------------------------------------------------
# Samples chunk tests
# ---------------------------------------------------------------------------


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
                # payload: stream_id(4) + collection_time(8) + varlen(num_samples)
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
                # After stream_id(4) + collection_time(8):
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
                _, offset = _read_varlen(payload, offset)  # num_samples
                offset += 8  # skip timestamp
                recovered = list(struct.unpack_from("<8f", payload, offset))
                assert recovered == pytest.approx(ch_values, abs=1e-5)
                break


# ---------------------------------------------------------------------------
# Statistics and lifecycle tests
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Thread safety test
# ---------------------------------------------------------------------------


class TestThreadSafety:
    def test_concurrent_writes_produce_valid_file(self, writer):
        def write_eeg():
            for i in range(20):
                writer.write_samples("EEG", [[float(i)] * 8], [float(i)])

        def write_hrv():
            for i in range(5):
                writer.write_samples("HRV", [[float(800 + i)]], [float(i)])

        def write_eda():
            for i in range(10):
                writer.write_samples("EDA", [[float(5 + i * 0.1)]], [float(i)])

        threads = [
            threading.Thread(target=write_eeg),
            threading.Thread(target=write_hrv),
            threading.Thread(target=write_eda),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        writer.close()

        # File should be parseable and contain the right counts
        assert writer.sample_counts["EEG"] == 20
        assert writer.sample_counts["HRV"] == 5
        assert writer.sample_counts["EDA"] == 10

        # File should be parseable — every chunk length must be consistent
        raw = writer.path.read_bytes()
        chunk_count = sum(1 for _ in _iter_chunks(raw))
        # magic(skip) + FileHeader + 4×StreamHeader + ≥1 Samples + 4×StreamFooter
        assert chunk_count >= 10
