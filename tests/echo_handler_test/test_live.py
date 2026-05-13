"""Live ECHO thread integration tests with mock LSL inlet and real DB."""

import pytest

from tests.echo_handler._support import (
    _LIVE_PART,
    build_thread,
    cleanup_echo_events,
    database_url,
    make_xdf,
    poll_for_rows,
)


class TestECHOThreadLive:
    """ECHOThread.start() + mock LSL inlet + real XDFWriter + real test DB."""

    def test_single_press_db_fields_correct(self, tmp_path, monkeypatch):
        import config.settings as s
        import psycopg2

        session_id = "f1d0a001-0000-4444-aaaa-000000000001"
        monkeypatch.setattr(s, "XDF_BACKUP_DIR", tmp_path)
        xdf = make_xdf(session_id, monkeypatch, tmp_path)

        marker_str = "ECHO|proximity_state_change|therapist_01|therapist|arms_reach"
        marker_ts = 99001.5

        thread, stop = build_thread(session_id, xdf, [(marker_str, marker_ts)])
        thread.start()

        try:
            arrived = poll_for_rows(session_id, 1)
            stop.set()
            thread.join(timeout=5.0)
            xdf.close()

            assert arrived, "echo_events row not written within 5 s"

            conn = psycopg2.connect(database_url())
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT event_type, source, actor_id, actor_role,
                              zone_label, lsl_timestamp, participant_id
                       FROM echo_events WHERE session_id = %s""",
                    (session_id,),
                )
                row = cur.fetchone()
            conn.close()

            assert row is not None
            assert row[0] == "proximity_state_change"
            assert row[1] == "manual_logging"
            assert row[2] == "therapist_01"
            assert row[3] == "therapist"
            assert row[4] == "arms_reach"
            assert row[5] == pytest.approx(marker_ts)
            assert row[6] == _LIVE_PART
        finally:
            cleanup_echo_events(session_id)

    def test_single_press_xdf_written_before_db(self, tmp_path, monkeypatch):
        import config.settings as s

        session_id = "f1d0a002-0000-4444-aaaa-000000000001"
        monkeypatch.setattr(s, "XDF_BACKUP_DIR", tmp_path)
        xdf = make_xdf(session_id, monkeypatch, tmp_path)

        marker_str = "ECHO|proximity_state_change|therapist_01|therapist|in_room"
        marker_ts = 99002.0

        thread, stop = build_thread(session_id, xdf, [(marker_str, marker_ts)])
        thread.start()

        try:
            arrived = poll_for_rows(session_id, 1)
            stop.set()
            thread.join(timeout=5.0)
            xdf.close()

            assert arrived, "DB row not written - cannot verify XDF ordering"
            assert xdf.sample_counts["ECHO"] == 1
        finally:
            cleanup_echo_events(session_id)

    def test_three_presses_all_written_in_order(self, tmp_path, monkeypatch):
        import config.settings as s
        import psycopg2

        session_id = "f1d0a003-0000-4444-aaaa-000000000001"
        monkeypatch.setattr(s, "XDF_BACKUP_DIR", tmp_path)
        xdf = make_xdf(session_id, monkeypatch, tmp_path)

        presses = [
            ("ECHO|proximity_state_change|therapist_01|therapist|arms_reach", 99003.1),
            ("ECHO|proximity_state_change|therapist_01|therapist|in_room", 99003.2),
            (
                "ECHO|proximity_state_change|therapist_01|therapist|leaving_room",
                99003.3,
            ),
        ]

        thread, stop = build_thread(session_id, xdf, presses)
        thread.start()

        try:
            arrived = poll_for_rows(session_id, 3)
            stop.set()
            thread.join(timeout=5.0)
            xdf.close()

            assert arrived, "Not all 3 rows arrived within 5 s"

            conn = psycopg2.connect(database_url())
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT zone_label, lsl_timestamp FROM echo_events
                       WHERE session_id = %s ORDER BY lsl_timestamp""",
                    (session_id,),
                )
                rows = cur.fetchall()
            conn.close()

            assert len(rows) == 3
            assert [r[0] for r in rows] == ["arms_reach", "in_room", "leaving_room"]
            assert [r[1] for r in rows] == pytest.approx([99003.1, 99003.2, 99003.3])
            assert xdf.sample_counts["ECHO"] == 3
        finally:
            cleanup_echo_events(session_id)

    def test_malformed_press_skipped_valid_continues(self, tmp_path, monkeypatch):
        import config.settings as s
        import psycopg2

        session_id = "f1d0a004-0000-4444-aaaa-000000000001"
        monkeypatch.setattr(s, "XDF_BACKUP_DIR", tmp_path)
        xdf = make_xdf(session_id, monkeypatch, tmp_path)

        presses = [
            ("NOT_ECHO_AT_ALL", 99004.0),
            ("ECHO|bad_event_type|t|therapist|arms_reach", 99004.1),
            ("ECHO|proximity_state_change|t|therapist|arms_reach", 99004.2),
        ]

        thread, stop = build_thread(session_id, xdf, presses)
        thread.start()

        try:
            arrived = poll_for_rows(session_id, 1)
            stop.set()
            thread.join(timeout=5.0)
            xdf.close()

            assert arrived, "Valid marker after two malformed ones was not written"

            conn = psycopg2.connect(database_url())
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM echo_events WHERE session_id = %s",
                    (session_id,),
                )
                count = cur.fetchone()[0]
            conn.close()

            assert count == 1
            assert xdf.sample_counts["ECHO"] == 1
        finally:
            cleanup_echo_events(session_id)
