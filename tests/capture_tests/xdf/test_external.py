"""Independent parser acceptance for approved XDF release rule R-030."""

import pytest

from batch.reconciliation.xdf import inspect_xdf
from capture.xdf.constants import CHANNEL_COUNTS
from capture.xdf.writer import XDFWriter
from config import settings
from tests.capture_tests.xdf.support import (
    DEVICE_ID,
    PARTICIPANT_ID,
    SESSION_ID,
    SITE_ID,
    SPONSOR_ID,
)


def test_r030_r032_pyxdf_reads_all_modalities_and_markers(tmp_path, monkeypatch):
    pyxdf = pytest.importorskip("pyxdf", reason="independent XDF release check requires pyxdf")
    monkeypatch.setattr(settings, "XDF_BACKUP_DIR", str(tmp_path))
    names = tuple(f"electrode_{index}" for index in range(CHANNEL_COUNTS["EEG"]))
    writer = XDFWriter(
        SESSION_ID,
        PARTICIPANT_ID,
        SITE_ID,
        SPONSOR_ID,
        eeg_channel_names=names,
        device_id=DEVICE_ID,
    )
    expected = {}
    for name in ("EEG", "HRV", "EDA", "Respiration"):
        values = [[float(i + channel) for channel in range(CHANNEL_COUNTS[name])] for i in range(3)]
        expected[name] = values
        writer.write_samples(name, values, [1.0, 1.25, 1.5])
    writer.write_marker("ECHO|manual_marker|operator|therapist|dose_administration", 1.1)
    writer.write_marker("marker \u03b1", 1.4)
    writer.close()
    streams, _ = pyxdf.load_xdf(
        str(writer.path), synchronize_clocks=False, dejitter_timestamps=False
    )
    by_name = {stream["info"]["name"][0]: stream for stream in streams}
    assert set(by_name) == {"EEG", "HRV", "EDA", "Respiration", "ECHO"}
    for name, values in expected.items():
        assert by_name[name]["time_series"].tolist() == values
        assert by_name[name]["time_stamps"].tolist() == [1.0, 1.25, 1.5]
        assert by_name[name]["info"]["session_id"] == [SESSION_ID]
    assert by_name["ECHO"]["time_stamps"].tolist() == [1.1, 1.4]
    assert by_name["ECHO"]["time_series"][1] == ["marker \u03b1"]
    metadata = inspect_xdf(writer.path)
    assert metadata.stream_metadata["EEG"]["device_id"] == DEVICE_ID
    import json

    assert json.loads(metadata.stream_metadata["EEG"]["eeg_channel_names"]) == list(names)
