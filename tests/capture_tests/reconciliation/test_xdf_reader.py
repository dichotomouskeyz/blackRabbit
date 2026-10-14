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


# Approved 2026-10-13 release reader rules. These fixtures intentionally corrupt
# complete files, exercising validation independently of writer success paths.


def test_standard_reader_rejects_width_two():
    with pytest.raises(XDFReadError, match="legacy"):
        _read_chunk_length(io.BytesIO(b"\x02\x00\x01"))
    assert _read_chunk_length(io.BytesIO(b"\x02\x00\x01"), legacy=True) == 256


def test_truncated_length_is_not_clean_eof():
    with pytest.raises(XDFTruncatedError):
        _read_chunk_length(io.BytesIO(b"\x04\x01"))


def test_every_stream_needs_a_footer(valid_xdf):
    path, _ = valid_xdf
    data = path.read_bytes()
    # Cut the final footer. Four intact footers must not establish closure.
    pos, last = 4, 4
    while pos < len(data):
        last = pos
        width = data[pos]
        length = int.from_bytes(data[pos + 1 : pos + 1 + width], "little")
        pos += 1 + width + length
    path.write_bytes(data[:last])
    with pytest.raises(XDFTruncatedError, match="footers"):
        read_xdf_counts(path)


def test_footer_counts_must_equal_decoded_samples(valid_xdf):
    path, _ = valid_xdf
    path.write_bytes(path.read_bytes().replace(b"<sample_count>4</", b"<sample_count>5</", 1))
    with pytest.raises(XDFReadError, match="count"):
        read_xdf_counts(path)


def test_malformed_footer_is_rejected(valid_xdf):
    path, _ = valid_xdf
    path.write_bytes(path.read_bytes().replace(b"<sample_count>4</", b"<sample_count>x</", 1))
    with pytest.raises(XDFReadError):
        read_xdf_counts(path)


def test_trailing_partial_chunk_is_rejected(valid_xdf):
    path, _ = valid_xdf
    path.write_bytes(path.read_bytes() + b"\x04\x00")
    with pytest.raises(XDFTruncatedError):
        read_xdf_counts(path)


def test_identity_validates_all_expected_fields(valid_xdf):
    from batch.reconciliation.xdf import inspect_xdf, validate_xdf_identity

    path, _ = valid_xdf
    counts = validate_xdf_identity(path, SESSION_ID, SPONSOR_ID, PARTICIPANT_ID, SITE_ID)
    assert counts["EEG"] == 4
    metadata = inspect_xdf(path)
    assert metadata.identity["sponsor_id"] == SPONSOR_ID
    assert metadata.format == "xdf-1.0"
    for field in ("session_id", "sponsor_id", "participant_id", "site_id"):
        expected = dict(
            session_id=SESSION_ID,
            sponsor_id=SPONSOR_ID,
            participant_id=PARTICIPANT_ID,
            site_id=SITE_ID,
        )
        expected[field] = "00000000-0000-4000-8000-000000000099"
        with pytest.raises(XDFReadError, match=field):
            validate_xdf_identity(path, **expected)


def test_cross_stream_identity_disagreement_is_rejected(valid_xdf):
    path, _ = valid_xdf
    path.write_bytes(
        path.read_bytes().replace(SPONSOR_ID.encode(), b"00000000-0000-4000-8000-000000000099", 1)
    )
    with pytest.raises(XDFReadError, match="identity"):
        read_xdf_counts(path)


def test_standard_file_cannot_be_labeled_legacy(valid_xdf):
    path, _ = valid_xdf
    with pytest.raises(XDFReadError, match="standard"):
        read_xdf_counts(path, legacy=True)


def test_explicit_legacy_recovery_preserves_original_file(tmp_path):
    import struct

    from batch.reconciliation.xdf import inspect_xdf

    # Historical writer layout, constructed independently of new encoder.
    def old_varlen(number):
        return b"\x01" + bytes([number]) if number <= 255 else b"\x02" + struct.pack("<H", number)

    def chunk(tag, content):
        body = struct.pack("<H", tag) + content
        return old_varlen(len(body)) + body

    header = (
        "<info><name>EEG</name><channel_count>1</channel_count>"
        "<nominal_srate>256</nominal_srate><channel_format>float32</channel_format>"
        f"<session_id>{SESSION_ID}</session_id><participant_id>{PARTICIPANT_ID}</participant_id>"
        f"<site_id>{SITE_ID}</site_id><sponsor_id>{SPONSOR_ID}</sponsor_id></info>"
    ).encode()
    original = b"XDF:" + chunk(1, b"<info><version>1.0</version></info>")
    original += chunk(2, struct.pack("<I", 1) + header)
    original += chunk(
        3, struct.pack("<Id", 1, 1000000.0) + b"\x01\x01" + struct.pack("<df", 12.5, 7.0)
    )
    original += chunk(6, struct.pack("<I", 1) + b"<info><sample_count>1</sample_count></info>")
    path = tmp_path / "legacy.xdf"
    path.write_bytes(original)
    with pytest.raises(XDFReadError):
        read_xdf_counts(path)
    assert read_xdf_counts(path, legacy=True) == {"EEG": 1}
    assert list(stream_xdf_samples(path, "EEG", legacy=True)) == [(0, 12.5, [7.0])]
    assert inspect_xdf(path, legacy=True).format == "blackrabbit-legacy"
    assert path.read_bytes() == original
