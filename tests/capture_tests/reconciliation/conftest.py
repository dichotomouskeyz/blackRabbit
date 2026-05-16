import pytest

from capture.xdf import XDFWriter
from tests.capture_tests.reconciliation.support import SESSION_ID, SITE_ID, SPONSOR_ID


@pytest.fixture()
def xdf_file(tmp_path, monkeypatch):
    import config.settings as s

    monkeypatch.setattr(s, "XDF_BACKUP_DIR", tmp_path)

    w = XDFWriter(SESSION_ID, SITE_ID, SPONSOR_ID)
    w.write_samples("EEG", [[float(i)] * 8 for i in range(50)], list(range(50)))
    w.write_samples("HRV", [[800.0 + i] for i in range(10)], list(range(10)))
    w.write_samples("EDA", [[5.0 + i * 0.1] for i in range(20)], list(range(20)))
    w.write_samples("Respiration", [[0.5 + i * 0.01] for i in range(15)], list(range(15)))
    w.write_marker("ECHO|proximity_state_change|therapist_01|therapist|arms_reach", 100.0)
    w.write_marker("ECHO|proximity_state_change|therapist_01|therapist|in_room", 105.0)
    w.close()

    expected = {"EEG": 50, "HRV": 10, "EDA": 20, "Respiration": 15, "ECHO": 2}
    return w.path, expected


@pytest.fixture()
def xdf_file_empty(tmp_path, monkeypatch):
    import config.settings as s

    monkeypatch.setattr(s, "XDF_BACKUP_DIR", tmp_path)
    w = XDFWriter(SESSION_ID, SITE_ID, SPONSOR_ID)
    w.close()
    return w.path


@pytest.fixture()
def xdf_file_truncated(tmp_path, monkeypatch):
    import config.settings as s

    monkeypatch.setattr(s, "XDF_BACKUP_DIR", tmp_path)
    w = XDFWriter(SESSION_ID, SITE_ID, SPONSOR_ID)
    w.write_samples("EEG", [[1.0] * 8], [1.0])
    return w.path
