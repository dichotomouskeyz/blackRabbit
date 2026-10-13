"""Spec-driven integration tests for reconciliation DB helpers (reconciliation.md
R-014..R-019).

Phase 3b/5b — DB counts, report building, existing-key fetches, close, log.
One test per R-xxx rule. Assertions derive from the spec text only.

NOTE (black-box): helper signatures inferred from the spec. Phase D resolves
call-site mismatches against a live DB. Skipped without TEST_DATABASE_URL.
"""

import pytest

from batch.reconciliation import db as rdb
from tests.capture_tests.reconciliation.support import SESSION_ID, SPONSOR_ID

pytestmark = pytest.mark.integration


class TestReconciliationDB:
    """reconciliation.md — DB helpers.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    def test_r014_query_db_counts_distinct_sample_index(self, db_conn, seeded_recon_session):
        counts = rdb.query_db_counts(db_conn, SESSION_ID)
        assert counts["EEG"] == seeded_recon_session["eeg_count"]

    def test_r015_build_report_reconciled_only_when_all_gaps_zero(
        self, db_conn, seeded_recon_session
    ):
        xdf_counts = {"EEG": seeded_recon_session["eeg_count"]}
        db_counts = rdb.query_db_counts(db_conn, SESSION_ID)
        report = rdb.build_report(SESSION_ID, "x.xdf", xdf_counts, db_counts, 0.0)
        assert report.is_reconciled is True

        report2 = rdb.build_report(
            SESSION_ID, "x.xdf", {"EEG": xdf_counts["EEG"] + 1}, db_counts, 0.0
        )
        assert report2.is_reconciled is False

    def test_r016_fetch_existing_sample_indices_frozenset(self, db_conn, seeded_recon_session):
        indices = rdb.fetch_existing_sample_indices(db_conn, SESSION_ID, "eeg_samples")
        assert isinstance(indices, frozenset)
        assert {0, 1, 2} <= indices

    def test_r017_fetch_existing_echo_keys_5tuples(self, db_conn, seeded_recon_session):
        keys = rdb.fetch_existing_echo_keys(db_conn, SESSION_ID)
        assert isinstance(keys, frozenset)
        for key in keys:
            assert len(key) == 5

    def test_r018_close_session_status_by_reconciled(self, db_conn, seeded_recon_session):
        rdb.close_session(db_conn, SESSION_ID, SPONSOR_ID, is_reconciled=True)
        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT status, closed_at FROM sessions WHERE id = %s::uuid",
                (SESSION_ID,),
            )
            status, closed_at = cur.fetchone()
        assert status == "closed"
        assert closed_at is not None

    def test_r019_write_reconciliation_log_one_jsonb_row(self, db_conn, seeded_recon_session):
        report = rdb.build_report(SESSION_ID, "x.xdf", {"EEG": 3}, {"EEG": 3}, 0.0)
        rdb.write_reconciliation_log(db_conn, report)
        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM biosignal_integrity_log "
                "WHERE session_id = %s::uuid AND log_type = 'xdf_reconciliation'",
                (SESSION_ID,),
            )
            assert cur.fetchone()[0] == 1
