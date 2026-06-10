"""Spec-driven tests for reconciliation XDF reader (reconciliation.md R-004..R-013).

Phase 3b/5b — `read_xdf_counts`, `_read_chunk_length`, `stream_xdf_samples`,
`stream_xdf_markers`. Unit tests; valid fixtures are produced by round-tripping
through `XDFWriter` (the documented writer), invalid ones are hand-crafted.
Assertions derive from the spec text only.

NOTE (black-box): reader signatures are inferred from the spec. Phase D
resolves any mismatch in the call sites only.
"""

import io

import pytest

import capture.xdf.writer as writer_mod
from batch.reconciliation.xdf import (
    XDFReadError,
    XDFTruncatedError,
    _read_chunk_length,
    read_xdf_counts,
    stream_xdf_markers,
    stream_xdf_samples,
)
from capture.xdf.constants import CHANNEL_COUNTS
from capture.xdf.writer import XDFWriter
from tests.capture_tests.reconciliation.support import (
    PARTICIPANT_ID,
    SESSION_ID,
    SITE_ID,
    SPONSOR_ID,
)

_EEG_CH = CHANNEL_COUNTS["EEG"]


def _eeg_sample(value):
    """One EEG sample with the channel width the stream header declares."""
    return [float(value)] * _EEG_CH


@pytest.fixture
def valid_xdf(tmp_path, monkeypatch):
    """A closed XDF file: EEG samples across two chunks + one ECHO marker."""
    monkeypatch.setattr(writer_mod.settings, "XDF_BACKUP_DIR", str(tmp_path), raising=False)
    writer = XDFWriter(SESSION_ID, PARTICIPANT_ID, SITE_ID, SPONSOR_ID)
    writer.write_samples("EEG", [_eeg_sample(1), _eeg_sample(2)], [1.0, 2.0])
    writer.write_samples("EEG", [_eeg_sample(3), _eeg_sample(4)], [3.0, 4.0])
    writer.write_marker("ECHO|manual_marker|a|therapist|dose_administration", 2.5)
    writer.close()
    return writer._path, {"EEG": 4, "ECHO": 1}


class TestReadXdfCounts:
    """reconciliation.md — `read_xdf_counts`.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    def test_r004_missing_file_raises(self, tmp_path):
        with pytest.raises(XDFReadError):
            read_xdf_counts(tmp_path / "does_not_exist.xdf")

    def test_r005_bad_magic_raises(self, tmp_path):
        bad = tmp_path / "bad.xdf"
        bad.write_bytes(b"BAD:rest of the bytes that are not a real header")
        with pytest.raises(XDFReadError):
            read_xdf_counts(bad)

    def test_r006_no_footer_raises_truncated(self, tmp_path, monkeypatch):
        monkeypatch.setattr(writer_mod.settings, "XDF_BACKUP_DIR", str(tmp_path), raising=False)
        writer = XDFWriter(SESSION_ID, PARTICIPANT_ID, SITE_ID, SPONSOR_ID)
        writer.write_samples("EEG", [_eeg_sample(1)], [1.0])
        # Intentionally NOT closed → no StreamFooter chunks.
        with pytest.raises(XDFTruncatedError):
            read_xdf_counts(writer._path)

    def test_r007_returns_stream_counts(self, valid_xdf):
        path, expected = valid_xdf
        counts = read_xdf_counts(path)
        assert counts["EEG"] == expected["EEG"]
        assert counts["ECHO"] == expected["ECHO"]


class TestReadChunkLength:
    """reconciliation.md — `_read_chunk_length`.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    def test_r008_eof_returns_none(self):
        assert _read_chunk_length(io.BytesIO(b"")) is None

    def test_r009_bad_prefix_raises(self):
        with pytest.raises(XDFReadError):
            _read_chunk_length(io.BytesIO(b"\x03\x00\x00\x00"))


class TestStreamXdfSamples:
    """reconciliation.md — `stream_xdf_samples` / `stream_xdf_markers`.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    def test_r010_yields_only_target_stream(self, valid_xdf):
        path, expected = valid_xdf
        rows = list(stream_xdf_samples(path, "EEG"))
        assert len(rows) == expected["EEG"]
        for sample_index, lsl_ts, channel_values in rows:
            assert isinstance(channel_values, (list, tuple))

    def test_r011_skips_echo_marker_samples(self, valid_xdf):
        path, expected = valid_xdf
        # Targeting a biosignal stream must not yield the ECHO marker.
        rows = list(stream_xdf_samples(path, "EEG"))
        assert len(rows) == expected["EEG"]

    def test_r012_markers_only_for_echo(self, valid_xdf):
        path, expected = valid_xdf
        markers = list(stream_xdf_markers(path))
        assert len(markers) == expected["ECHO"]
        _, _, text = markers[0]
        assert text.startswith("ECHO|")

    def test_r013_sample_index_contiguous_across_chunks(self, valid_xdf):
        path, _ = valid_xdf
        rows = list(stream_xdf_samples(path, "EEG"))
        indices = [sample_index for sample_index, _, _ in rows]
        assert indices == [0, 1, 2, 3]
