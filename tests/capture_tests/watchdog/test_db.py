"""Spec-driven integration tests for watchdog DB writes (watchdog.md R-011..R-015).

Phase 2 — `log_restart`, `mark_session_closing`, `mark_session_failed`.
One test per R-xxx rule. Assertions derive from the spec text only.

NOTE (black-box): db-helper signatures inferred from the spec. Phase D resolves
call-site mismatches against a live DB. Skipped without TEST_DATABASE_URL.
"""

import pytest

from capture.watchdog import db as wdb
from tests.capture_tests.watchdog.support import SESSION_ID, SPONSOR_ID

pytestmark = pytest.mark.integration


class TestWatchdogDB:
    """watchdog.md — database writes.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    def test_r011_log_restart_writes_alert_row(self, db_conn, seeded_active_session):
        wdb.log_restart(
            seeded_active_session["session_id"],
            seeded_active_session["participant_id"],
            seeded_active_session["site_id"],
            seeded_active_session["sponsor_id"],
            exit_code=1,
            restart_count=1,
            uptime_s=12.5,
        )
        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT alert_type, severity, algorithm_parameters "
                "FROM alert_events WHERE session_id = %s::uuid",
                (SESSION_ID,),
            )
            rows = cur.fetchall()
        assert len(rows) == 1
        alert_type, severity, params = rows[0]
        assert alert_type == "process_restart"
        assert severity == "warning"
        assert params["exit_code"] == 1
        assert params["restart_count"] == 1
        assert params["uptime_s"] == 12.5

    def test_r012_alert_carries_tenancy(self, db_conn, seeded_active_session):
        wdb.log_restart(
            seeded_active_session["session_id"],
            seeded_active_session["participant_id"],
            seeded_active_session["site_id"],
            seeded_active_session["sponsor_id"],
            exit_code=1,
            restart_count=1,
            uptime_s=1.0,
        )
        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT participant_id, site_id, sponsor_id "
                "FROM alert_events WHERE session_id = %s::uuid",
                (SESSION_ID,),
            )
            participant_id, site_id, sponsor_id = cur.fetchone()
        assert str(participant_id) == seeded_active_session["participant_id"]
        assert str(site_id) == seeded_active_session["site_id"]
        assert str(sponsor_id) == seeded_active_session["sponsor_id"]

    def test_r013_mark_closing_idempotent(self, db_conn, seeded_active_session):
        wdb.mark_session_closing(SESSION_ID, SPONSOR_ID)
        with db_conn.cursor() as cur:
            cur.execute("SELECT status FROM sessions WHERE id = %s::uuid", (SESSION_ID,))
            assert cur.fetchone()[0] == "closing"
        # Second call affects 0 rows and does not raise.
        wdb.mark_session_closing(SESSION_ID, SPONSOR_ID)

    def test_r014_mark_failed_sets_status_and_closed_at(self, db_conn, seeded_active_session):
        wdb.mark_session_failed(SESSION_ID, SPONSOR_ID)
        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT status, closed_at FROM sessions WHERE id = %s::uuid",
                (SESSION_ID,),
            )
            status, closed_at = cur.fetchone()
        assert status == "failed"
        assert closed_at is not None

    def test_r015_log_restart_failure_is_nonfatal(self, seeded_active_session):
        # Missing session / bad tenancy should not crash the caller.
        # (Spec notes this currently fails due to BUG-003.)
        try:
            wdb.log_restart(
                "00000000-0000-4000-8000-0000000000ff",
                seeded_active_session["participant_id"],
                seeded_active_session["site_id"],
                seeded_active_session["sponsor_id"],
                exit_code=1,
                restart_count=1,
                uptime_s=1.0,
            )
        except Exception as exc:  # noqa: BLE001 - documenting BUG-003
            pytest.fail(f"log_restart raised instead of being non-fatal: {exc!r}")
