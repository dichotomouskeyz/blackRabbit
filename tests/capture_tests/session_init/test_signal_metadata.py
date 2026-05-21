"""Integration tests for session_signal_metadata rows created by create_session."""

import json

import psycopg2
import pytest

from config import settings
from tests.capture_tests.session_init.support import (
    _PART,
    _SITE,
    _SPONSOR,
    _call,
    _cleanup,
    _query_metadata,
)


@pytest.mark.integration
class TestSignalMetadataDB:
    def test_four_metadata_rows_created(self, db_url):
        sid = _call(db_url)
        try:
            rows = _query_metadata(db_url, sid)
            assert len(rows) == 4
        finally:
            _cleanup(db_url, sid)

    def test_modalities_in_canonical_order(self, db_url):
        sid = _call(db_url)
        try:
            rows = _query_metadata(db_url, sid)
            modalities = [r["modality"] for r in rows]
            assert modalities == ["eeg", "hrv", "eda", "respiration"]
        finally:
            _cleanup(db_url, sid)

    def test_tenancy_columns_match_session(self, db_url):
        sid = _call(db_url)
        try:
            rows = _query_metadata(db_url, sid)
            for row in rows:
                assert str(row["site_id"]) == _SITE
                assert str(row["sponsor_id"]) == _SPONSOR
                assert str(row["participant_id"]) == _PART
        finally:
            _cleanup(db_url, sid)

    def test_eeg_row_fields(self, db_url):
        sid = _call(db_url)
        try:
            eeg = _query_metadata(db_url, sid)[0]
            names = eeg["eeg_channel_names"]
            if isinstance(names, str):
                names = json.loads(names)
            assert eeg["modality"] == "eeg"
            assert eeg["eeg_reference"] == settings.EEG_REFERENCE
            assert eeg["sampling_frequency"] == pytest.approx(
                float(settings.SAMPLE_RATE_EEG)
            )
            assert eeg["eeg_channel_count"] == settings.EEG_CHANNEL_COUNT
            assert names is None
            assert eeg["power_line_frequency"] == pytest.approx(
                settings.POWER_LINE_FREQUENCY
            )
        finally:
            _cleanup(db_url, sid)

    def test_eeg_channel_names_stored_when_configured(self, db_url, monkeypatch):
        monkeypatch.setattr(
            settings,
            "EEG_CHANNEL_NAMES",
            tuple(f"Fp{i}" for i in range(settings.EEG_CHANNEL_COUNT)),
        )
        sid = _call(db_url)
        try:
            eeg = _query_metadata(db_url, sid)[0]
            names = eeg["eeg_channel_names"]
            if isinstance(names, str):
                names = json.loads(names)
            assert names == [f"Fp{i}" for i in range(settings.EEG_CHANNEL_COUNT)]
        finally:
            _cleanup(db_url, sid)

    def test_hrv_row_fields(self, db_url):
        sid = _call(db_url)
        try:
            hrv = _query_metadata(db_url, sid)[1]
            assert hrv["modality"] == "hrv"
            assert hrv["hrv_signal_source"] == settings.HRV_SIGNAL_SOURCE
            assert hrv["sample_rate_hz"] == pytest.approx(
                float(settings.SAMPLE_RATE_HRV)
            )
        finally:
            _cleanup(db_url, sid)

    def test_eda_row_fields(self, db_url):
        sid = _call(db_url)
        try:
            eda = _query_metadata(db_url, sid)[2]
            assert eda["modality"] == "eda"
            assert eda["eda_signal_source"] == settings.EDA_SIGNAL_SOURCE
            assert eda["sample_rate_hz"] == pytest.approx(
                float(settings.SAMPLE_RATE_EDA)
            )
        finally:
            _cleanup(db_url, sid)

    def test_respiration_row_fields(self, db_url):
        sid = _call(db_url)
        try:
            resp = _query_metadata(db_url, sid)[3]
            assert resp["modality"] == "respiration"
            assert resp["respiration_source"] == settings.RESPIRATION_SOURCE
            assert resp["is_derived"] == (settings.RESPIRATION_SOURCE in {"rsa_derived"})
            assert resp["sample_rate_hz"] == pytest.approx(
                float(settings.SAMPLE_RATE_RESPIRATION)
            )
        finally:
            _cleanup(db_url, sid)

    def test_eda_electrode_args_stored(self, db_url):
        sid = _call(
            db_url,
            electrode_placement="palmar",
            electrode_type="ag_agcl",
            skin_prep="cleaned",
        )
        try:
            eda = _query_metadata(db_url, sid)[2]
            assert eda["electrode_placement"] == "palmar"
            assert eda["electrode_type"] == "ag_agcl"
            assert eda["skin_prep"] == "cleaned"
        finally:
            _cleanup(db_url, sid)

    def test_eda_electrode_args_null_by_default(self, db_url):
        sid = _call(db_url)
        try:
            eda = _query_metadata(db_url, sid)[2]
            assert eda["electrode_placement"] is None
            assert eda["electrode_type"] is None
            assert eda["skin_prep"] is None
        finally:
            _cleanup(db_url, sid)

    def test_metadata_rolled_back_with_session_on_failure(self):
        from unittest.mock import MagicMock, patch

        from capture.session_init.workflow import create_session

        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur
        mock_cur.execute.side_effect = [
            None,
            None,
            None,
            psycopg2.IntegrityError("hrv constraint"),
        ]

        with patch("capture.session_init.workflow.psycopg2.connect", return_value=mock_conn):
            with pytest.raises(psycopg2.IntegrityError):
                create_session("psilocybin", _SITE, _SPONSOR, _PART)

        mock_conn.rollback.assert_called_once()
        mock_conn.commit.assert_not_called()
