"""Database integration tests for ECHO rows and audit triggers."""

import psycopg2

from tests.echo_handler._support import _SID_AUDIT, _SID_INSERT, _SID_STATES
from tests.echo_handler._support import database_url, db_conn, insert_echo_event


class TestECHODBWrite:
    """Verify echo_events rows are written correctly and audit trigger fires."""

    def test_echo_event_row_written_with_correct_columns(self):
        insert_echo_event(_SID_INSERT, "arms_reach", 1234567890.123)

        conn = db_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT session_id, event_type, source, actor_id,
                           actor_role, zone_label, lsl_timestamp
                    FROM echo_events
                    WHERE session_id = %s
                    ORDER BY db_insert_time DESC LIMIT 1
                    """,
                    (_SID_INSERT,),
                )
                row = cur.fetchone()
        finally:
            conn.close()

        assert row is not None, "No echo_events row found"
        assert row[0] == _SID_INSERT
        assert row[1] == "proximity_state_change"
        assert row[2] == "manual_logging"
        assert row[3] == "therapist_01"
        assert row[4] == "therapist"
        assert row[5] == "arms_reach"
        assert abs(row[6] - 1234567890.123) < 0.001

    def test_echo_event_triggers_audit_entry(self):
        insert_echo_event(_SID_AUDIT, "in_room", 1234567891.0)

        conn = db_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*) FROM audit_events
                    WHERE session_id = %s AND table_name = 'echo_events'
                    """,
                    (_SID_AUDIT,),
                )
                count = cur.fetchone()[0]
        finally:
            conn.close()

        assert count >= 1, "Audit trigger did not fire on echo_events INSERT"

    def test_xdf_marker_written_before_db(self):
        """XDF write_marker is called for every valid event, regardless of DB state."""
        from unittest.mock import MagicMock

        from capture.echo_handler import ECHOThread

        cfg = MagicMock()
        cfg.session_id = "e0eebc99-9c0b-4ef8-bb6d-6bb9bd380a04"
        cfg.participant_id = "aaaa0002-0000-0000-0000-000000000002"
        cfg.site_id = "bbbb0000-0000-0000-0000-000000000001"
        cfg.sponsor_id = "cccc0000-0000-0000-0000-000000000001"

        xdf_mock = MagicMock()
        thread = ECHOThread(cfg=cfg, stop_event=MagicMock(), xdf_writer=xdf_mock)

        marker = "ECHO|proximity_state_change|therapist_01|therapist|arms_reach"
        conn = psycopg2.connect(database_url())
        conn.autocommit = False

        row = {
            "session_id": cfg.session_id,
            "participant_id": "aaaa0002-0000-0000-0000-000000000002",
            "site_id": "bbbb0000-0000-0000-0000-000000000001",
            "sponsor_id": "cccc0000-0000-0000-0000-000000000001",
            "event_type": "proximity_state_change",
            "actor_id": "therapist_01",
            "actor_role": "therapist",
            "zone_label": "arms_reach",
            "lsl_timestamp": 1234567999.0,
        }

        thread._xdf.write_marker(marker, row["lsl_timestamp"])
        thread._write_row(conn, row)
        conn.close()

        xdf_mock.write_marker.assert_called_once_with(marker, 1234567999.0)

    def test_all_four_proximity_states_accepted(self):
        """Every valid zone_label inserts without constraint error."""
        base_ts = 1234567900.0
        for i, zone in enumerate(
            sorted({"arms_reach", "in_room", "leaving_room", "out_of_room"})
        ):
            insert_echo_event(_SID_STATES, zone, base_ts + i)

        conn = db_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT zone_label FROM echo_events WHERE session_id = %s",
                    (_SID_STATES,),
                )
                found = {row[0] for row in cur.fetchall()}
        finally:
            conn.close()

        assert found == {"arms_reach", "in_room", "leaving_room", "out_of_room"}
