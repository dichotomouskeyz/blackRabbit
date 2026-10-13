"""Spec-driven tests for batch/arc/preflight.py (arc-preflight.md).

Phase 5b — ARC temporal alignment gate. Unit tests cover the pure
report/stream value objects and threshold validation; integration tests
exercise the DB-backed `validate_arc_temporal_alignment` entry point.
One test per R-xxx rule. Assertions derive from the spec text only.
"""

import math

import pytest

from batch.arc.preflight import (
    APEXStreamAlignment,
    ARCTemporalAlignmentReport,
    assert_arc_temporal_alignment,
    validate_arc_temporal_alignment,
)
from tests.capture_tests.arc.support import SESSION_ID, SPONSOR_ID


def _stream(name="eeg", sample_count=500, delta=0.1, threshold=1.0):
    return APEXStreamAlignment(
        stream_name=name,
        table_name=f"{name}_samples",
        sample_count=sample_count,
        first_lsl_timestamp=1000.0 if sample_count else None,
        last_lsl_timestamp=1100.0 if sample_count else None,
        max_nearest_echo_delta_s=delta,
        threshold_s=threshold,
    )


def _report(echo_event_count=3, streams=None, threshold=1.0):
    if streams is None:
        streams = (_stream(),)
    return ARCTemporalAlignmentReport(
        session_id=SESSION_ID,
        threshold_s=threshold,
        echo_event_count=echo_event_count,
        first_echo_lsl_timestamp=1000.0 if echo_event_count else None,
        last_echo_lsl_timestamp=1200.0 if echo_event_count else None,
        streams={s.stream_name: s for s in streams},
    )


class TestThresholdValidation:
    """arc-preflight.md — input validation.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    @pytest.mark.parametrize("bad", [0.0, -0.5, 1.0001, 2.0])
    def test_r001_threshold_out_of_range_raises(self, bad):
        with pytest.raises(ValueError):
            validate_arc_temporal_alignment(None, SESSION_ID, threshold_s=bad)


class TestStreamAlignment:
    """arc-preflight.md — `APEXStreamAlignment.is_aligned`.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    def test_r002_zero_samples_not_aligned(self):
        assert _stream(sample_count=0, delta=0.1).is_aligned is False

    def test_r003_none_delta_not_aligned(self):
        assert _stream(sample_count=500, delta=None).is_aligned is False

    def test_r004_delta_at_or_above_threshold_not_aligned(self):
        assert _stream(sample_count=500, delta=1.0, threshold=1.0).is_aligned is False
        assert _stream(sample_count=500, delta=1.5, threshold=1.0).is_aligned is False

    def test_r005_finite_below_threshold_aligned(self):
        assert _stream(sample_count=500, delta=0.5, threshold=1.0).is_aligned is True


class TestAlignmentReport:
    """arc-preflight.md — `ARCTemporalAlignmentReport`.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    def test_r006_no_echo_events_not_aligned(self):
        report = _report(echo_event_count=0, streams=(_stream(delta=0.1),))
        assert report.is_aligned is False

    def test_r007_one_failed_stream_not_aligned(self):
        streams = (_stream(name="eeg", delta=0.1), _stream(name="hrv", delta=2.0))
        assert _report(echo_event_count=3, streams=streams).is_aligned is False

    def test_r008_failed_streams_sorted(self):
        streams = (
            _stream(name="respiration", delta=2.0),
            _stream(name="eeg", delta=0.1),
            _stream(name="eda", delta=2.0),
        )
        report = _report(echo_event_count=3, streams=streams)
        assert report.failed_streams == ("eda", "respiration")

    def test_r009_raise_for_unaligned_no_echo(self):
        report = _report(echo_event_count=0, streams=(_stream(delta=0.1),))
        with pytest.raises(RuntimeError, match="no ECHO anchor events found"):
            report.raise_for_unaligned()

    def test_r010_raise_for_unaligned_lists_failed_streams(self):
        streams = (_stream(name="eeg", delta=0.1), _stream(name="hrv", delta=2.0))
        report = _report(echo_event_count=3, streams=streams)
        with pytest.raises(RuntimeError, match="hrv"):
            report.raise_for_unaligned()

    def test_r011_raise_for_unaligned_noop_when_aligned(self):
        report = _report(echo_event_count=3, streams=(_stream(delta=0.1),))
        assert report.raise_for_unaligned() is None


@pytest.mark.integration
class TestPreflightIntegration:
    """arc-preflight.md — DB-backed alignment integration.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    def test_r012_echo_event_count_matches_db(self, db_conn, arc_seeded_session):
        report = validate_arc_temporal_alignment(db_conn, SESSION_ID, SPONSOR_ID, threshold_s=1.0)
        assert report.echo_event_count == arc_seeded_session["echo_count"]

    def test_r013_anchor_filters_restrict_count(self, db_conn, arc_seeded_session):
        report = validate_arc_temporal_alignment(
            db_conn,
            SESSION_ID,
            SPONSOR_ID,
            threshold_s=1.0,
            anchor_filters=arc_seeded_session["matching_filters"],
        )
        assert report.echo_event_count == arc_seeded_session["matching_count"]

    def test_r014_stream_aligned_when_below_threshold(self, db_conn, arc_seeded_session):
        report = validate_arc_temporal_alignment(db_conn, SESSION_ID, SPONSOR_ID, threshold_s=1.0)
        aligned = {s.stream_name: s.is_aligned for s in report.streams}
        assert aligned.get(arc_seeded_session["aligned_stream"]) is True

    def test_r015_assert_returns_or_raises(self, db_conn, arc_seeded_session):
        report = validate_arc_temporal_alignment(db_conn, SESSION_ID, SPONSOR_ID, threshold_s=1.0)
        if report.is_aligned:
            assert (
                assert_arc_temporal_alignment(db_conn, SESSION_ID, SPONSOR_ID, threshold_s=1.0)
                is not None
            )
        else:
            with pytest.raises(RuntimeError):
                assert_arc_temporal_alignment(db_conn, SESSION_ID, SPONSOR_ID, threshold_s=1.0)

    def test_r004_above_threshold_blocks(self, db_conn, arc_seeded_session):
        # A sub-microsecond threshold forces every stream above the gate.
        with pytest.raises(RuntimeError):
            assert_arc_temporal_alignment(
                db_conn, SESSION_ID, SPONSOR_ID, threshold_s=math.ulp(1.0)
            )
