"""Spec-driven integration tests for session_close.run (session-close.md R-009..R-021).

Phase 2 — end-of-session reconciliation + close exit codes against a live DB.
One test per R-xxx rule. Assertions derive from the spec text only.

NOTE (black-box): `run()` and collaborator signatures are inferred from the
spec. Phase D resolves call-site mismatches when wiring against a live DB.
These tests are skipped without TEST_DATABASE_URL.
"""

import pytest

import capture.session_close.workflow as workflow
from tests.capture_tests.session_close.support import SESSION_ID, SPONSOR_ID

pytestmark = pytest.mark.integration


def _run(xdf_path="missing.xdf", session_id=SESSION_ID):
    return workflow.run(session_id, SPONSOR_ID, xdf_path)


class TestExitCodes:
    """session-close.md — run() exit codes.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    def test_r009_unreadable_xdf_returns_2(self, tmp_path):
        assert _run(xdf_path=str(tmp_path / "nope.xdf")) == 2

    def test_r010_unknown_session_returns_2(self, tmp_path, sc_valid_xdf):
        assert (
            workflow.run("00000000-0000-4000-8000-0000000000ff", SPONSOR_ID, str(sc_valid_xdf)) == 2
        )

    def test_r011_non_closeable_state_returns_2(self, sc_session_closed, sc_valid_xdf):
        assert _run(xdf_path=str(sc_valid_xdf)) == 2

    def test_r012_active_session_transitions_to_closing(
        self, sc_session_active, sc_valid_xdf, caplog
    ):
        _run(xdf_path=str(sc_valid_xdf))
        # status moved off 'active' (to closing/closed/failed) during the run.
        assert sc_session_active["status_after"]() != "active"


class TestReconciliation:
    """session-close.md — reconciliation paths.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    def test_r013_counts_match_closes_reconciled(self, sc_reconciled_session):
        assert _run(xdf_path=str(sc_reconciled_session["xdf_path"])) == 0
        assert sc_reconciled_session["status_after"]() == "closed"

    def test_r014_backfill_only_for_positive_gap(self, sc_negative_gap_session):
        # DB > XDF (negative gap) must not trigger backfill.
        _run(xdf_path=str(sc_negative_gap_session["xdf_path"]))
        assert sc_negative_gap_session["backfill_calls"]() == 0

    def test_r015_reconciliation_rerun_after_backfill(self, sc_gap_session):
        _run(xdf_path=str(sc_gap_session["xdf_path"]))
        assert sc_gap_session["reconcile_calls"]() >= 2

    def test_r016_unbackfillable_gap_returns_1_failed(self, sc_unfillable_gap_session):
        assert _run(xdf_path=str(sc_unfillable_gap_session["xdf_path"])) == 1
        assert sc_unfillable_gap_session["status_after"]() == "failed"

    def test_r017_reconciliation_log_always_written(self, sc_reconciled_session):
        _run(xdf_path=str(sc_reconciled_session["xdf_path"]))
        assert sc_reconciled_session["log_written"]() is True


class TestArcFailure:
    """session-close.md — ARC failure handling.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    def test_r018_arc_config_failure_closes_failed_returns_1(self, sc_arc_config_broken):
        assert _run(xdf_path=str(sc_arc_config_broken["xdf_path"])) == 1
        assert sc_arc_config_broken["alert_written"]("arc_failure") is True

    def test_r019_arc_postsession_error_closes_failed_returns_1(self, sc_arc_raises):
        assert _run(xdf_path=str(sc_arc_raises["xdf_path"])) == 1
        assert sc_arc_raises["alert_written"]("arc_failure") is True

    def test_r020_alert_uses_independent_connection(self, sc_arc_raises):
        _run(xdf_path=str(sc_arc_raises["xdf_path"]))
        assert sc_arc_raises["alert_used_own_conn"]() is True


class TestResourceCleanup:
    """session-close.md — resource cleanup.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    def test_r021_main_connection_always_closed(self, sc_reconciled_session):
        _run(xdf_path=str(sc_reconciled_session["xdf_path"]))
        assert sc_reconciled_session["conn_closed"]() is True
