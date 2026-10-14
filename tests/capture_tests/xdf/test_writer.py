"""Approved XDF release-contract tests, regenerated 2026-10-13."""

import threading

import pytest

import capture.xdf.writer as writer_mod
from batch.reconciliation.xdf import read_xdf_counts
from capture.xdf.constants import CHANNEL_COUNTS, STREAM_IDS
from capture.xdf.writer import XDFWriteError, XDFWriter
from tests.capture_tests.xdf.support import PARTICIPANT_ID, SESSION_ID, SITE_ID, SPONSOR_ID


@pytest.fixture
def make_writer(tmp_path, monkeypatch):
    monkeypatch.setattr(writer_mod.settings, "XDF_BACKUP_DIR", str(tmp_path))
    writers = []

    def create(**kwargs):
        writer = XDFWriter(SESSION_ID, PARTICIPANT_ID, SITE_ID, SPONSOR_ID, **kwargs)
        writers.append(writer)
        return writer

    yield create
    for writer in writers:
        try:
            writer.close()
        except XDFWriteError:
            pass


def eeg(value):
    return [value] * CHANNEL_COUNTS["EEG"]


def chunk_tags(data):
    i = 4
    while i < len(data):
        width = data[i]
        assert width in (1, 4, 8)
        length = int.from_bytes(data[i + 1 : i + 1 + width], "little")
        i += 1 + width
        yield int.from_bytes(data[i : i + 2], "little")
        i += length
    assert i == len(data)


def test_r014_r015_headers_and_magic(make_writer):
    writer = make_writer()
    data = writer.path.read_bytes()
    assert data[:4] == b"XDF:"
    assert list(chunk_tags(data)).count(2) == len(STREAM_IDS) == 5


def test_r016_empty_paired_input_is_noop(make_writer):
    writer = make_writer()
    before = writer.path.read_bytes()
    writer.write_samples("EEG", [], [])
    assert writer.path.read_bytes() == before
    assert writer.sample_counts["EEG"] == 0


def test_r017_r018_counts_and_timestamps(make_writer):
    writer = make_writer()
    writer.write_samples("EEG", [eeg(1), eeg(2)], [0.0, 1.0])
    writer.write_samples("EEG", [eeg(3)], [2.0])
    assert writer.sample_counts["EEG"] == 3
    assert writer._first_ts["EEG"] == 0.0
    assert writer._last_ts["EEG"] == 2.0


@pytest.mark.parametrize("failure_point", ["write", "fsync", "flush"])
def test_r019_failure_is_fatal_and_count_does_not_advance(make_writer, monkeypatch, failure_point):
    writer = make_writer()

    def fail(*args, **kwargs):
        raise OSError("injected storage failure")

    if failure_point == "write":
        monkeypatch.setattr(writer_mod, "write_chunk", fail)
    elif failure_point == "fsync":
        monkeypatch.setattr(writer_mod.os, "fsync", fail)
    else:
        monkeypatch.setattr(writer, "_sync", fail)
    with pytest.raises(XDFWriteError):
        writer.write_samples("EEG", [eeg(1)], [1.0])
    assert writer.sample_counts["EEG"] == 0
    assert writer._f.closed
    with pytest.raises(XDFWriteError):
        writer.write_marker("marker", 2.0)
    with pytest.raises(XDFWriteError):
        writer.close()
    assert not writer.is_closed


def test_r020_marker_count(make_writer):
    writer = make_writer()
    writer.write_marker("marker", 100.0)
    assert writer.sample_counts["ECHO"] == 1


def test_r021_closed_writes_fail(make_writer):
    writer = make_writer()
    writer.close()
    before = writer.path.read_bytes()
    for operation in (
        lambda: writer.write_samples("EEG", [eeg(1)], [1.0]),
        lambda: writer.write_samples("EEG", [], []),
        lambda: writer.write_marker("marker", 1.0),
    ):
        with pytest.raises(XDFWriteError):
            operation()
    assert writer.path.read_bytes() == before


def test_r022_r023_r024_successful_close_is_idempotent(make_writer):
    writer = make_writer()
    assert not writer.is_closed
    writer.close()
    writer.close()
    assert writer.is_closed
    assert list(chunk_tags(writer.path.read_bytes())).count(6) == 5


def test_r025_counts_are_a_copy(make_writer):
    writer = make_writer()
    counts = writer.sample_counts
    counts["EEG"] = 999
    assert writer.sample_counts["EEG"] == 0


def test_r026_concurrent_stream_writes_remain_readable(make_writer):
    writer = make_writer()
    failures = []

    def write(stream):
        try:
            for i in range(8):
                writer.write_samples(stream, [[float(i)] * CHANNEL_COUNTS[stream]], [float(i)])
        except Exception as exc:
            failures.append(exc)

    workers = [threading.Thread(target=write, args=(s,)) for s in CHANNEL_COUNTS if s != "ECHO"]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    assert not failures
    writer.close()
    assert read_xdf_counts(writer.path) == {
        "EEG": 8,
        "HRV": 8,
        "EDA": 8,
        "Respiration": 8,
        "ECHO": 0,
    }


@pytest.mark.parametrize(
    "samples,timestamps",
    [
        ([eeg(1)], []),
        ([], [1.0]),
        ([[1.0] * (CHANNEL_COUNTS["EEG"] + 1)], [1.0]),
        ([eeg(1)], [float("nan")]),
        ([eeg(1)], [float("inf")]),
        ([eeg(float("nan"))], [1.0]),
        ([eeg(float("inf"))], [1.0]),
        ([eeg(1e100)], [1.0]),
    ],
)
def test_r027_invalid_payload_leaves_file_unchanged(make_writer, samples, timestamps):
    writer = make_writer()
    before = writer.path.read_bytes()
    with pytest.raises(ValueError):
        writer.write_samples("EEG", samples, timestamps)
    assert writer.path.read_bytes() == before
    assert writer.sample_counts["EEG"] == 0


@pytest.mark.parametrize("timestamp", [float("nan"), float("inf"), -float("inf")])
def test_r027_invalid_marker_timestamp(make_writer, timestamp):
    writer = make_writer()
    before = writer.path.read_bytes()
    with pytest.raises(ValueError):
        writer.write_marker("marker", timestamp)
    assert writer.path.read_bytes() == before


@pytest.mark.parametrize("failure_point", ["write", "fsync"])
def test_r028_failed_finalization_is_not_closed(make_writer, monkeypatch, failure_point):
    writer = make_writer()

    def fail(*args, **kwargs):
        raise OSError("injected footer failure")

    monkeypatch.setattr(
        writer_mod if failure_point == "write" else writer_mod.os,
        "write_chunk" if failure_point == "write" else "fsync",
        fail,
    )
    with pytest.raises(XDFWriteError):
        writer.close()
    assert not writer.is_closed
    assert writer._f.closed
    with pytest.raises(XDFWriteError):
        writer.close()


def test_r029_recordings_never_overwrite(make_writer):
    first, second = make_writer(), make_writer()
    first.write_samples("EEG", [eeg(12)], [1.0])
    first.close()
    before = first.path.read_bytes()
    second.close()
    assert first.path != second.path
    assert first.path.read_bytes() == before


def test_successful_chunk_is_fsynced_before_return(make_writer, monkeypatch):
    writer = make_writer()
    sync_counts = []
    original = writer_mod.os.fsync

    def sync(fd):
        sync_counts.append(writer._sample_counts["EEG"])
        return original(fd)

    monkeypatch.setattr(writer_mod.os, "fsync", sync)
    writer.write_samples("EEG", [eeg(1)], [1.0])
    assert sync_counts == [0]
    assert writer.sample_counts["EEG"] == 1
