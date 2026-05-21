"""Row builder unit tests — no DB, no LSL required.

Verifies three regulatory properties:
  a) lsl_timestamp equals the float passed in — never derived from wall clock.
  b) db_insert_time absent from every row — must always be set by DEFAULT NOW().
  c) participant_id is the pseudonymous token unchanged.
"""

import pytest

from capture.forwarder.models import SessionConfig
from capture.forwarder.rows import (
    build_eda_rows,
    build_eeg_rows,
    build_hrv_rows,
    build_respiration_rows,
)
from tests.capture_tests.forwarder.support import _UNIT_CFG, _UNIT_LSL_TS

_CFG = _UNIT_CFG
_LSL_TS = _UNIT_LSL_TS


class TestRowBuildersAllModalities:
    # EEG ------------------------------------------------------------------

    def test_eeg_one_row_per_channel(self):
        rows = build_eeg_rows([1.0] * 8, _CFG, _LSL_TS, 0)
        assert len(rows) == 8

    def test_eeg_lsl_timestamp_propagated(self):
        rows = build_eeg_rows([0.0] * 8, _CFG, _LSL_TS, 0)
        assert all(r["lsl_timestamp"] == pytest.approx(_LSL_TS) for r in rows)

    def test_eeg_db_insert_time_not_in_row(self):
        rows = build_eeg_rows([0.0] * 8, _CFG, _LSL_TS, 0)
        assert all("db_insert_time" not in r for r in rows)

    def test_eeg_participant_id_is_pseudonymous_token(self):
        rows = build_eeg_rows([0.0] * 8, _CFG, _LSL_TS, 0)
        assert all(r["participant_id"] == _CFG.participant_id for r in rows)

    def test_eeg_channel_ids_are_sequential(self):
        rows = build_eeg_rows([1.0] * 8, _CFG, _LSL_TS, 0)
        assert [r["channel_id"] for r in rows] == [f"ch_{i}" for i in range(8)]

    def test_eeg_channel_ids_use_metadata_when_present(self):
        cfg = SessionConfig(
            session_id=_CFG.session_id,
            participant_id=_CFG.participant_id,
            site_id=_CFG.site_id,
            sponsor_id=_CFG.sponsor_id,
            eeg_channel_names=tuple(f"Fp{i}" for i in range(8)),
        )
        rows = build_eeg_rows([1.0] * 8, cfg, _LSL_TS, 0)
        assert [r["channel_id"] for r in rows] == [f"Fp{i}" for i in range(8)]

    def test_eeg_channel_name_count_mismatch_raises(self):
        cfg = SessionConfig(
            session_id=_CFG.session_id,
            participant_id=_CFG.participant_id,
            site_id=_CFG.site_id,
            sponsor_id=_CFG.sponsor_id,
            eeg_channel_names=("Fp1", "Fp2"),
        )
        with pytest.raises(ValueError, match="channel name count"):
            build_eeg_rows([1.0] * 8, cfg, _LSL_TS, 0)

    def test_eeg_voltages_match_sample(self):
        sample = [float(i) * 1.1 for i in range(8)]
        rows = build_eeg_rows(sample, _CFG, _LSL_TS, 0)
        assert [r["voltage"] for r in rows] == pytest.approx(sample)

    # HRV ------------------------------------------------------------------

    def test_hrv_one_row(self):
        assert len(build_hrv_rows([860.0], _CFG, _LSL_TS, 0)) == 1

    def test_hrv_lsl_timestamp_propagated(self):
        r = build_hrv_rows([860.0], _CFG, _LSL_TS, 0)[0]
        assert r["lsl_timestamp"] == pytest.approx(_LSL_TS)

    def test_hrv_db_insert_time_not_in_row(self):
        assert "db_insert_time" not in build_hrv_rows([860.0], _CFG, _LSL_TS, 0)[0]

    def test_hrv_derives_bpm_from_rr(self):
        r = build_hrv_rows([600.0], _CFG, _LSL_TS, 0)[0]
        assert r["heart_rate_bpm"] == pytest.approx(100.0)

    def test_hrv_zero_rr_gives_none_bpm(self):
        assert build_hrv_rows([0.0], _CFG, _LSL_TS, 0)[0]["heart_rate_bpm"] is None

    def test_hrv_participant_id_is_pseudonymous_token(self):
        r = build_hrv_rows([860.0], _CFG, _LSL_TS, 0)[0]
        assert r["participant_id"] == _CFG.participant_id

    # EDA ------------------------------------------------------------------

    def test_eda_one_row(self):
        assert len(build_eda_rows([5.2], _CFG, _LSL_TS, 0)) == 1

    def test_eda_lsl_timestamp_propagated(self):
        r = build_eda_rows([5.2], _CFG, _LSL_TS, 0)[0]
        assert r["lsl_timestamp"] == pytest.approx(_LSL_TS)

    def test_eda_db_insert_time_not_in_row(self):
        assert "db_insert_time" not in build_eda_rows([5.2], _CFG, _LSL_TS, 0)[0]

    def test_eda_conductance_us_equals_raw(self):
        r = build_eda_rows([5.2], _CFG, _LSL_TS, 0)[0]
        assert r["conductance_us"] == pytest.approx(r["raw_conductance_us"])

    def test_eda_participant_id_is_pseudonymous_token(self):
        r = build_eda_rows([5.2], _CFG, _LSL_TS, 0)[0]
        assert r["participant_id"] == _CFG.participant_id

    # Respiration ----------------------------------------------------------

    def test_respiration_one_row(self):
        assert len(build_respiration_rows([0.45], _CFG, _LSL_TS, 0)) == 1

    def test_respiration_lsl_timestamp_propagated(self):
        r = build_respiration_rows([0.45], _CFG, _LSL_TS, 0)[0]
        assert r["lsl_timestamp"] == pytest.approx(_LSL_TS)

    def test_respiration_db_insert_time_not_in_row(self):
        assert "db_insert_time" not in build_respiration_rows([0.45], _CFG, _LSL_TS, 0)[0]

    def test_respiration_processed_equals_raw(self):
        r = build_respiration_rows([0.45], _CFG, _LSL_TS, 0)[0]
        assert r["processed_amplitude"] == pytest.approx(r["raw_amplitude"])

    def test_respiration_participant_id_is_pseudonymous_token(self):
        r = build_respiration_rows([0.45], _CFG, _LSL_TS, 0)[0]
        assert r["participant_id"] == _CFG.participant_id

    # Cross-modality -------------------------------------------------------

    def test_all_biosignal_builders_carry_session_site_sponsor(self):
        all_rows = (
            build_eeg_rows([0.0] * 8, _CFG, _LSL_TS, 0)
            + build_hrv_rows([860.0], _CFG, _LSL_TS, 0)
            + build_eda_rows([5.0], _CFG, _LSL_TS, 0)
            + build_respiration_rows([0.4], _CFG, _LSL_TS, 0)
        )
        for r in all_rows:
            assert r["session_id"] == _CFG.session_id
            assert r["site_id"] == _CFG.site_id
            assert r["sponsor_id"] == _CFG.sponsor_id

    def test_all_biosignal_builders_propagate_sample_index(self):
        idx = 42
        all_rows = (
            build_eeg_rows([0.0] * 8, _CFG, _LSL_TS, idx)
            + build_hrv_rows([860.0], _CFG, _LSL_TS, idx)
            + build_eda_rows([5.0], _CFG, _LSL_TS, idx)
            + build_respiration_rows([0.4], _CFG, _LSL_TS, idx)
        )
        assert all(r["sample_index"] == idx for r in all_rows)
