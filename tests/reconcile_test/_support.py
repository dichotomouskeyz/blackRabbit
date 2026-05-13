"""Shared fixtures and constants for reconciliation tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from capture.xdf_writer import XDFWriter

SESSION_ID = "ccccdddd-0000-0000-0000-000000000001"
SITE_ID = "SITE-REC-01"
SPONSOR_ID = "SPONSOR-REC-01"
_ALL_STREAMS = ("EEG", "HRV", "EDA", "Respiration")

_REC_SESSION = "eeee0000-0000-0000-0000-000000000002"
_REC_PARTICIPANT = "eeee0000-aaaa-4444-0000-000000000002"
_REC_SITE = "eeee0001-0000-4444-0000-000000000002"
_REC_SPONSOR = "eeee0002-0000-4444-0000-000000000002"
_REC_DEVICE = "eeee0003-0000-4444-0000-000000000002"
_REC_LSL = 99999.123456

_BF_SESSION = "cccc3333-bbbb-4444-aaaa-000000000099"
_BF_PARTICIPANT = "ffffffff-aaaa-4444-bbbb-000000000001"
_BF_SITE = "cccc3333-1111-4444-aaaa-000000000099"
_BF_SPONSOR = "cccc3333-2222-4444-aaaa-000000000099"
_BF_DEVICE = "cccc3333-3333-4444-aaaa-000000000099"


@pytest.fixture()
def xdf_file(tmp_path, monkeypatch):
    import config.settings as s

    monkeypatch.setattr(s, "XDF_BACKUP_DIR", tmp_path)

    w = XDFWriter(SESSION_ID, SITE_ID, SPONSOR_ID)
    w.write_samples("EEG", [[float(i)] * 8 for i in range(50)], list(range(50)))
    w.write_samples("HRV", [[800.0 + i] for i in range(10)], list(range(10)))
    w.write_samples("EDA", [[5.0 + i * 0.1] for i in range(20)], list(range(20)))
    w.write_samples("Respiration", [[0.5 + i * 0.01] for i in range(15)], list(range(15)))
    w.write_marker(
        "ECHO|proximity_state_change|therapist_01|therapist|arms_reach", 100.0
    )
    w.write_marker(
        "ECHO|proximity_state_change|therapist_01|therapist|in_room", 105.0
    )
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
