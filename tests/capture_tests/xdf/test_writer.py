"""Spec-driven tests for XDFWriter lifecycle (xdf-writer.md R-014..R-026).

Phase 2 — XDFWriter lifecycle and thread safety. Unit tests with a temp file.
Assertions derive from the spec text only.

NOTE (black-box): the XDFWriter constructor and method signatures below are
inferred from the spec. Phase D resolves any mismatch in the `_writer` /
call-site helpers only — assertion values are never adjusted.
"""

import threading

import pytest

import capture.xdf.writer as writer_mod
from capture.xdf.constants import STREAM_IDS
from capture.xdf.writer import XDFWriter
from tests.capture_tests.xdf.support import (
    PARTICIPANT_ID,
    SESSION_ID,
    SITE_ID,
    SPONSOR_ID,
)

_TAG_STREAM_HEADER = 2
_TAG_SAMPLES = 3
_TAG_STREAM_FOOTER = 6


@pytest.fixture(autouse=True)
def _xdf_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(writer_mod.settings, "XDF_BACKUP_DIR", str(tmp_path), raising=False)
    return tmp_path


def _writer(tmp_path, name=None):
    # XDFWriter derives its own output path under settings.XDF_BACKUP_DIR
    # (patched to tmp_path by the autouse fixture); the path is exposed as ._path.
    writer = XDFWriter(SESSION_ID, PARTICIPANT_ID, SITE_ID, SPONSOR_ID)
    return writer, writer._path


def _iter_chunk_tags(data):
    """Yield each chunk's 2-byte tag, skipping the 4-byte 'XDF:' magic.

    Chunk layout per R-004: [numlenbytes][length][tag(2)][payload],
    where length counts the tag bytes plus the payload.
    """
    i = 4  # skip magic
    n = len(data)
    while i < n:
        prefix = data[i]
        i += 1
        length = int.from_bytes(data[i : i + prefix], "little")
        i += prefix
        chunk = data[i : i + length]
        i += length
        yield int.from_bytes(chunk[:2], "little")


def _tag_counts(path):
    data = path.read_bytes()
    counts = {}
    for tag in _iter_chunk_tags(data):
        counts[tag] = counts.get(tag, 0) + 1
    return counts


class TestXDFWriterLifecycle:
    """xdf-writer.md — XDFWriter lifecycle.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    def test_r014_file_starts_with_magic(self, tmp_path):
        _, path = _writer(tmp_path)
        assert path.read_bytes()[:4] == b"XDF:"

    def test_r015_five_stream_header_chunks_after_init(self, tmp_path):
        _, path = _writer(tmp_path)
        assert _tag_counts(path).get(_TAG_STREAM_HEADER) == 5
        assert len(STREAM_IDS) == 5

    def test_r016_empty_samples_is_noop(self, tmp_path):
        writer, path = _writer(tmp_path)
        before_size = path.stat().st_size
        before_counts = dict(writer.sample_counts)
        writer.write_samples("EEG", [], [])
        assert path.stat().st_size == before_size
        assert dict(writer.sample_counts) == before_counts

    def test_r017_sample_counts_increase(self, tmp_path):
        writer, _ = _writer(tmp_path)
        before = writer.sample_counts.get("EEG", 0)
        writer.write_samples("EEG", [[1.0], [2.0]], [1.0, 2.0])
        assert writer.sample_counts["EEG"] == before + 2

    def test_r018_first_and_last_ts_tracking(self, tmp_path):
        writer, _ = _writer(tmp_path)
        writer.write_samples("EEG", [[1.0], [2.0]], [1.0, 2.0])
        writer.write_samples("EEG", [[3.0], [4.0]], [3.0, 4.0])
        assert writer._first_ts["EEG"] == 1.0
        assert writer._last_ts["EEG"] == 4.0

    def test_r019_oserror_during_write_does_not_increment(self, tmp_path, monkeypatch):
        writer, _ = _writer(tmp_path)
        before = writer.sample_counts.get("EEG", 0)

        def _boom(*args, **kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(writer_mod, "write_chunk", _boom)
        # Spec: write failures are logged and silently dropped, not raised.
        writer.write_samples("EEG", [[1.0]], [1.0])
        assert writer.sample_counts.get("EEG", 0) == before

    def test_r020_write_marker_increments_echo(self, tmp_path):
        writer, _ = _writer(tmp_path)
        before = writer.sample_counts.get("ECHO", 0)
        writer.write_marker("ECHO|manual_marker|a|therapist|z", 100.0)
        assert writer.sample_counts["ECHO"] == before + 1

    def test_r021_writes_are_noop_after_close(self, tmp_path):
        writer, path = _writer(tmp_path)
        writer.close()
        size_after_close = path.stat().st_size
        counts_after_close = dict(writer.sample_counts)
        writer.write_samples("EEG", [[1.0]], [1.0])
        writer.write_marker("ECHO|manual_marker|a|therapist|z", 100.0)
        assert path.stat().st_size == size_after_close
        assert dict(writer.sample_counts) == counts_after_close

    def test_r022_five_footer_chunks_after_close(self, tmp_path):
        writer, path = _writer(tmp_path)
        writer.close()
        assert _tag_counts(path).get(_TAG_STREAM_FOOTER) == 5

    def test_r023_close_is_idempotent(self, tmp_path):
        writer, path = _writer(tmp_path)
        writer.close()
        writer.close()
        assert _tag_counts(path).get(_TAG_STREAM_FOOTER) == 5

    def test_r024_is_closed_flag(self, tmp_path):
        writer, _ = _writer(tmp_path)
        assert writer.is_closed is False
        writer.close()
        assert writer.is_closed is True

    def test_r025_sample_counts_returns_copy(self, tmp_path):
        writer, _ = _writer(tmp_path)
        returned = writer.sample_counts
        returned["EEG"] = 999999
        assert writer.sample_counts.get("EEG", 0) != 999999


class TestThreadSafety:
    """xdf-writer.md — thread safety.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    def test_r026_concurrent_writes_non_interleaved(self, tmp_path):
        writer, path = _writer(tmp_path)
        n_per_thread = 20
        streams = ["EEG", "HRV", "EDA", "Respiration"]

        def _work(stream):
            for i in range(n_per_thread):
                writer.write_samples(stream, [[float(i)]], [float(i)])

        threads = [threading.Thread(target=_work, args=(s,)) for s in streams]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        writer.close()

        # If any chunk's bytes interleaved, the length-prefixed walk would
        # desync and the Samples-chunk count would not match the writes.
        counts = _tag_counts(path)
        assert counts.get(_TAG_SAMPLES) == len(streams) * n_per_thread
