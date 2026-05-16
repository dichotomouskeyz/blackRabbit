"""XDF reading tests for batch.reconcile."""

import pytest

from batch.reconcile import (
    _XDF_MAGIC,
    XDFReadError,
    XDFTruncatedError,
    read_xdf_counts,
    stream_xdf_markers,
    stream_xdf_samples,
)
from capture.xdf import XDFWriter
from tests.capture_tests.reconciliation.support import (
    _ALL_STREAMS,
    SESSION_ID,
    SITE_ID,
    SPONSOR_ID,
)


class TestReadXDFCountsHappyPath:
    def test_returns_counts_for_all_streams(self, xdf_file):
        path, expected = xdf_file
        counts = read_xdf_counts(path)
        assert set(counts.keys()) == set(expected.keys())

    def test_eeg_count_correct(self, xdf_file):
        path, expected = xdf_file
        assert read_xdf_counts(path)["EEG"] == expected["EEG"]

    def test_hrv_count_correct(self, xdf_file):
        path, expected = xdf_file
        assert read_xdf_counts(path)["HRV"] == expected["HRV"]

    def test_eda_count_correct(self, xdf_file):
        path, expected = xdf_file
        assert read_xdf_counts(path)["EDA"] == expected["EDA"]

    def test_respiration_count_correct(self, xdf_file):
        path, expected = xdf_file
        assert read_xdf_counts(path)["Respiration"] == expected["Respiration"]

    def test_echo_count_correct(self, xdf_file):
        path, expected = xdf_file
        assert read_xdf_counts(path)["ECHO"] == expected["ECHO"]

    def test_echo_markers_decode_from_xdf(self, xdf_file):
        path, _ = xdf_file
        markers = list(stream_xdf_markers(path))

        assert markers == [
            (
                0,
                pytest.approx(100.0),
                "ECHO|proximity_state_change|therapist_01|therapist|arms_reach",
            ),
            (
                1,
                pytest.approx(105.0),
                "ECHO|proximity_state_change|therapist_01|therapist|in_room",
            ),
        ]

    def test_empty_file_returns_zero_counts(self, xdf_file_empty):
        counts = read_xdf_counts(xdf_file_empty)
        for name in _ALL_STREAMS:
            assert counts[name] == 0

    def test_multi_chunk_same_stream_accumulates(self, tmp_path, monkeypatch):
        import config.settings as s

        monkeypatch.setattr(s, "XDF_BACKUP_DIR", tmp_path)
        w = XDFWriter(SESSION_ID, SITE_ID, SPONSOR_ID)
        w.write_samples("EEG", [[1.0] * 8] * 25, list(range(25)))
        w.write_samples("EEG", [[2.0] * 8] * 25, list(range(25, 50)))
        w.write_samples("EEG", [[3.0] * 8] * 10, list(range(50, 60)))
        w.close()
        counts = read_xdf_counts(w.path)
        assert counts["EEG"] == 60


class TestReadXDFCountsErrors:
    def test_missing_file_raises_read_error(self, tmp_path):
        with pytest.raises(XDFReadError):
            read_xdf_counts(tmp_path / "nonexistent.xdf")

    def test_wrong_magic_raises_read_error(self, tmp_path):
        bad_file = tmp_path / "bad.xdf"
        bad_file.write_bytes(b"NOTXDF:garbage")
        with pytest.raises(XDFReadError, match="magic"):
            read_xdf_counts(bad_file)

    def test_truncated_file_raises_truncated_error(self, xdf_file_truncated):
        with pytest.raises(XDFTruncatedError):
            read_xdf_counts(xdf_file_truncated)

    def test_empty_file_raises_read_error(self, tmp_path):
        empty = tmp_path / "empty.xdf"
        empty.write_bytes(b"")
        with pytest.raises(XDFReadError):
            read_xdf_counts(empty)

    def test_just_magic_no_chunks_raises_truncated(self, tmp_path):
        f = tmp_path / "magic_only.xdf"
        f.write_bytes(_XDF_MAGIC)
        with pytest.raises(XDFTruncatedError):
            read_xdf_counts(f)


class TestStreamXDFSamples:
    def test_yields_correct_sample_count_eeg(self, xdf_file):
        path, expected = xdf_file
        samples = list(stream_xdf_samples(path, "EEG"))
        assert len(samples) == expected["EEG"]

    def test_yields_correct_sample_count_hrv(self, xdf_file):
        path, expected = xdf_file
        samples = list(stream_xdf_samples(path, "HRV"))
        assert len(samples) == expected["HRV"]

    def test_sample_index_is_sequential_from_zero(self, xdf_file):
        path, _ = xdf_file
        indices = [idx for idx, _, _ in stream_xdf_samples(path, "HRV")]
        assert indices == list(range(len(indices)))

    def test_timestamps_are_floats(self, xdf_file):
        path, _ = xdf_file
        for _, ts, _ in stream_xdf_samples(path, "EDA"):
            assert isinstance(ts, float)

    def test_eeg_channel_values_are_8_per_sample(self, xdf_file):
        path, _ = xdf_file
        for _, _, vals in stream_xdf_samples(path, "EEG"):
            assert len(vals) == 8

    def test_hrv_has_one_channel(self, xdf_file):
        path, _ = xdf_file
        for _, _, vals in stream_xdf_samples(path, "HRV"):
            assert len(vals) == 1

    def test_skips_other_streams(self, xdf_file):
        path, expected = xdf_file
        eeg_samples = list(stream_xdf_samples(path, "EEG"))
        hrv_samples = list(stream_xdf_samples(path, "HRV"))
        assert len(eeg_samples) == expected["EEG"]
        assert len(hrv_samples) == expected["HRV"]

    def test_values_recoverable_for_known_write(self, tmp_path, monkeypatch):
        import config.settings as s

        monkeypatch.setattr(s, "XDF_BACKUP_DIR", tmp_path)
        w = XDFWriter(SESSION_ID, SITE_ID, SPONSOR_ID)
        known_vals = [1.1, 2.2, 3.3, 4.4, 5.5, 6.6, 7.7, 8.8]
        w.write_samples("EEG", [known_vals], [42.0])
        w.close()
        samples = list(stream_xdf_samples(w.path, "EEG"))
        assert len(samples) == 1
        _, ts, vals = samples[0]
        assert ts == pytest.approx(42.0)
        assert vals == pytest.approx(known_vals, abs=1e-5)

    def test_empty_stream_yields_nothing(self, xdf_file_empty):
        samples = list(stream_xdf_samples(xdf_file_empty, "EEG"))
        assert samples == []

    def test_wrong_magic_raises(self, tmp_path):
        bad = tmp_path / "bad.xdf"
        bad.write_bytes(b"NOTXDF")
        with pytest.raises(XDFReadError):
            list(stream_xdf_samples(bad, "EEG"))

    def test_multi_chunk_indices_are_contiguous(self, tmp_path, monkeypatch):
        import config.settings as s

        monkeypatch.setattr(s, "XDF_BACKUP_DIR", tmp_path)
        w = XDFWriter(SESSION_ID, SITE_ID, SPONSOR_ID)
        w.write_samples("HRV", [[800.0]] * 5, list(range(5)))
        w.write_samples("HRV", [[810.0]] * 3, list(range(5, 8)))
        w.write_samples("HRV", [[820.0]] * 2, list(range(8, 10)))
        w.close()
        indices = [i for i, _, _ in stream_xdf_samples(w.path, "HRV")]
        assert indices == list(range(10))
