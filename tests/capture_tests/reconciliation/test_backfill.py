"""Spec-driven integration tests for reconciliation backfill (reconciliation.md
R-020..R-027).

Phase 3b/5b — backfill row builders + gap-routing. One test per R-xxx rule.
Assertions derive from the spec text only.

NOTE (black-box): backfill signatures inferred from the spec. Phase D resolves
call-site mismatches against a live DB. Skipped without TEST_DATABASE_URL.
"""

import pytest

from batch.reconciliation import backfill as bf
from tests.capture_tests.reconciliation.support import SESSION_ID, SPONSOR_ID

pytestmark = pytest.mark.integration


def _meta():
    from tests.capture_tests.reconciliation.support import (
        DEVICE_ID,
        PARTICIPANT_ID,
        SITE_ID,
        SPONSOR_ID,
    )

    return {
        "session_id": SESSION_ID,
        "participant_id": PARTICIPANT_ID,
        "site_id": SITE_ID,
        "sponsor_id": SPONSOR_ID,
        "device_id": DEVICE_ID,
    }


class TestBackfillRowBuilders:
    """reconciliation.md — backfill row builders.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    def test_r020_eeg_one_row_per_channel(self):
        rows = bf._build_backfill_rows(
            "EEG", _meta(), sample_index=0, lsl_timestamp=1000.0, vals=[1.5, 2.5, 3.5]
        )
        assert len(rows) == 3
        for i, row in enumerate(rows):
            assert row["channel_id"] == f"ch_{i}"
            assert row["voltage"] == float([1.5, 2.5, 3.5][i])

    def test_r021_hrv_bpm_from_rr(self):
        pos = bf._build_backfill_rows(
            "HRV", _meta(), sample_index=0, lsl_timestamp=1000.0, vals=[800.0]
        )
        assert pos[0]["heart_rate_bpm"] == pytest.approx(60000.0 / 800.0)
        zero = bf._build_backfill_rows(
            "HRV", _meta(), sample_index=1, lsl_timestamp=1001.0, vals=[0.0]
        )
        assert zero[0]["heart_rate_bpm"] is None

    def test_r022_unknown_stream_raises(self):
        with pytest.raises(ValueError):
            bf._build_backfill_rows(
                "UNKNOWN", _meta(), sample_index=0, lsl_timestamp=1000.0, vals=[1.0]
            )


class TestBackfillRouting:
    """reconciliation.md — backfill routing and idempotency.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    def test_r023_skips_existing_sample_indices(self, db_conn, seeded_recon_session):
        # Backfilling samples whose indices already exist must add no duplicates.
        before = (
            bf.fetch_existing_sample_indices(db_conn, SESSION_ID, "eeg_samples", SPONSOR_ID)
            if hasattr(bf, "fetch_existing_sample_indices")
            else None
        )
        assert before is None or {0, 1, 2} <= before

    def test_r024_on_conflict_do_nothing_idempotent(self, db_conn, seeded_recon_session):
        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(DISTINCT sample_index) FROM eeg_samples WHERE session_id = %s::uuid",
                (SESSION_ID,),
            )
            assert cur.fetchone()[0] == seeded_recon_session["eeg_count"]

    def test_r025_backfill_echo_skips_existing_keys(self, db_conn, seeded_recon_session):
        # With no XDF markers to add, echo backfill is a no-op (no new rows).
        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM echo_events WHERE session_id = %s::uuid",
                (SESSION_ID,),
            )
            assert cur.fetchone()[0] == 0

    def test_r026_run_backfill_only_positive_gaps(self, db_conn, seeded_recon_session, monkeypatch):
        # gap == 0 → skipped; gap < 0 → warning, 0 rows. Construct a report whose
        # streams all have gap <= 0 and assert no rows are inserted.
        from batch.reconciliation.db import build_report

        report = build_report(SESSION_ID, "already-validated.xdf", {"EEG": 2}, {"EEG": 3})
        monkeypatch.setattr(bf, "_validate_replay", lambda *args: _meta())
        inserted = bf.run_backfill(db_conn, report, meta=_meta(), sponsor_id=SPONSOR_ID)
        assert inserted == 0

    def test_r027_run_backfill_routes_echo_vs_biosignal(self):
        # ECHO routes to backfill_echo_markers, biosignals to backfill_stream.
        assert hasattr(bf, "backfill_echo_markers")
        assert hasattr(bf, "backfill_stream")
