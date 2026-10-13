"""Spec-driven tests for forwarder row builders (forwarder.md R-001..R-009).

Phase 2 — per-modality row construction. All unit tests; no DB.
Assertions derive from the spec text only.
"""

from types import SimpleNamespace

import pytest

from capture.forwarder.models import SessionConfig
from capture.forwarder.rows import (
    build_eda_rows,
    build_eeg_rows,
    build_hrv_rows,
    build_respiration_rows,
)
from capture.forwarder.stream_thread.stream_chunks import build_rows
from tests.capture_tests.forwarder.support import (
    LSL_TIMESTAMP,
    PARTICIPANT_ID,
    SESSION_ID,
    SITE_ID,
    SPONSOR_ID,
)


def _cfg(**over):
    kwargs = dict(
        session_id=SESSION_ID,
        participant_id=PARTICIPANT_ID,
        site_id=SITE_ID,
        sponsor_id=SPONSOR_ID,
        eeg_channel_names=None,
    )
    kwargs.update(over)
    return SessionConfig(**kwargs)


_TENANCY = {
    "session_id": SESSION_ID,
    "participant_id": PARTICIPANT_ID,
    "site_id": SITE_ID,
    "sponsor_id": SPONSOR_ID,
}


class TestEEGRowBuilder:
    """forwarder.md — EEG row builder.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    def test_r001_one_row_per_channel(self):
        sample = [1.0, 2.0, 3.0, 4.0]
        rows = build_eeg_rows(sample, _cfg(), LSL_TIMESTAMP, 0)
        assert len(rows) == len(sample)

    def test_r002_channel_name_length_mismatch_raises(self):
        cfg = _cfg(eeg_channel_names=("Fz", "Cz"))
        with pytest.raises(ValueError):
            build_eeg_rows([1.0, 2.0, 3.0], cfg, LSL_TIMESTAMP, 0)

    def test_r003_fallback_channel_names(self):
        rows = build_eeg_rows([1.0, 2.0], _cfg(eeg_channel_names=None), LSL_TIMESTAMP, 0)
        channel_ids = [r["channel_id"] for r in rows]
        assert channel_ids == ["ch_0", "ch_1"]

    def test_r004_lsl_timestamp_is_passed_in_float(self):
        rows = build_eeg_rows([1.0, 2.0], _cfg(), LSL_TIMESTAMP, 0)
        assert all(r["lsl_timestamp"] == LSL_TIMESTAMP for r in rows)


class TestHRVRowBuilder:
    """forwarder.md — HRV row builder.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    @pytest.mark.parametrize("rr_ms", [0.0, -1.0, -500.0])
    def test_r005_nonpositive_rr_gives_none_bpm(self, rr_ms):
        rows = build_hrv_rows([rr_ms], _cfg(), LSL_TIMESTAMP, 0)
        assert rows[0]["heart_rate_bpm"] is None

    def test_r006_positive_rr_computes_bpm(self):
        rows = build_hrv_rows([800.0], _cfg(), LSL_TIMESTAMP, 0)
        assert rows[0]["heart_rate_bpm"] == pytest.approx(60000.0 / 800.0)


class TestAllBuildersTenancyAndTimestamp:
    """forwarder.md — shared tenancy/timestamp invariants.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    def _all_rows(self):
        cfg = _cfg()
        return [
            *build_eeg_rows([1.0, 2.0], cfg, LSL_TIMESTAMP, 0),
            *build_hrv_rows([800.0], cfg, LSL_TIMESTAMP, 0),
            *build_eda_rows([5.0], cfg, LSL_TIMESTAMP, 0),
            *build_respiration_rows([0.5], cfg, LSL_TIMESTAMP, 0),
        ]

    def test_r007_tenancy_fields_unchanged(self):
        for row in self._all_rows():
            for key, value in _TENANCY.items():
                assert row[key] == value

    def test_r008_lsl_timestamp_on_every_row(self):
        for row in self._all_rows():
            assert row["lsl_timestamp"] == LSL_TIMESTAMP


class TestBuildRowsSampleIndex:
    """forwarder.md — `build_rows` sample-index increment.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    def test_r009_sample_index_increments_once_per_sample(self):
        # EEG expands each sample to N channel rows, but sample_index must
        # advance exactly once per sample.
        thread = SimpleNamespace(
            _row_builder=build_eeg_rows,
            _cfg=_cfg(),
            _sample_index=0,
        )
        samples = [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0], [7.0, 8.0, 9.0]]
        timestamps = [10.0, 11.0, 12.0]
        build_rows(thread, samples, timestamps)
        assert thread._sample_index == 3
