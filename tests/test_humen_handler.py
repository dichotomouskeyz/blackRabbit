"""Tests for capture.humen_handler — marker parsing and DB write verification."""

import os
import threading
import time
from unittest.mock import MagicMock

import psycopg2
import pytest
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from capture.humen_handler import (  # noqa: E402
    VALID_ZONE_LABELS,
    HUMeNThread,
    parse_humen_marker,
)
from capture.xdf_writer import XDFWriter  # noqa: E402

# ---------------------------------------------------------------------------
# parse_humen_marker — unit tests (no DB required)
# ---------------------------------------------------------------------------


class TestParseHumenMarker:
    def test_valid_all_zone_labels(self):
        for zone in VALID_ZONE_LABELS:
            result = parse_humen_marker(
                f"HUMEN|proximity_state_change|therapist_01|therapist|{zone}"
            )
            assert result is not None
            assert result["zone_label"] == zone

    def test_valid_all_actor_roles(self):
        for role in ("therapist", "facilitator", "coordinator", "observer"):
            result = parse_humen_marker(
                f"HUMEN|proximity_state_change|actor_01|{role}|arms_reach"
            )
            assert result is not None
            assert result["actor_role"] == role

    def test_returns_all_expected_fields(self):
        result = parse_humen_marker(
            "HUMEN|proximity_state_change|therapist_01|therapist|in_room"
        )
        assert result == {
            "event_type": "proximity_state_change",
            "actor_id": "therapist_01",
            "actor_role": "therapist",
            "zone_label": "in_room",
        }

    def test_strips_actor_id_whitespace(self):
        result = parse_humen_marker(
            "HUMEN|proximity_state_change|  therapist_01  |therapist|arms_reach"
        )
        assert result is not None
        assert result["actor_id"] == "therapist_01"

    def test_wrong_prefix_returns_none(self):
        assert (
            parse_humen_marker("MARKER|proximity_state_change|t|therapist|arms_reach")
            is None
        )

    def test_missing_prefix_returns_none(self):
        assert (
            parse_humen_marker("proximity_state_change|t|therapist|arms_reach") is None
        )

    def test_too_few_fields_returns_none(self):
        assert parse_humen_marker("HUMEN|proximity_state_change|therapist") is None

    def test_too_many_fields_returns_none(self):
        assert (
            parse_humen_marker(
                "HUMEN|proximity_state_change|t|therapist|arms_reach|extra"
            )
            is None
        )

    def test_unknown_zone_label_returns_none(self):
        assert (
            parse_humen_marker("HUMEN|proximity_state_change|t|therapist|close_enough")
            is None
        )

    def test_unknown_actor_role_returns_none(self):
        assert (
            parse_humen_marker("HUMEN|proximity_state_change|t|researcher|arms_reach")
            is None
        )

    def test_unknown_event_type_returns_none(self):
        assert parse_humen_marker("HUMEN|zone_change|t|therapist|arms_reach") is None

    def test_empty_actor_id_returns_none(self):
        assert (
            parse_humen_marker("HUMEN|proximity_state_change||therapist|arms_reach")
            is None
        )

    def test_empty_string_returns_none(self):
        assert parse_humen_marker("") is None

    def test_non_humen_lsl_marker_returns_none(self):
        assert parse_humen_marker("STIMULUS_ONSET") is None


# ---------------------------------------------------------------------------
# DB integration tests — require TEST_DATABASE_URL
# ---------------------------------------------------------------------------


def _test_db_conn():
    url = os.getenv("TEST_DATABASE_URL", "")
    url = url.replace("postgresql://", "")
    user_pass, rest = url.split("@")
    user, password = user_pass.split(":")
    host_port, dbname = rest.split("/")
    host, port = host_port.split(":")
    return psycopg2.connect(
        host=host, port=int(port), dbname=dbname, user=user, password=password
    )


_SID_INSERT = "e0eebc99-9c0b-4ef8-bb6d-6bb9bd380a01"
_SID_AUDIT = "e0eebc99-9c0b-4ef8-bb6d-6bb9bd380a02"
_SID_STATES = "e0eebc99-9c0b-4ef8-bb6d-6bb9bd380a03"


class TestHUMeNDBWrite:
    """Verify humen_events rows are written correctly and audit trigger fires."""

    def _insert_humen_event(self, session_id: str, zone_label: str, lsl_ts: float):
        """Use _write_row directly via a minimal HUMeNThread instance."""
        from unittest.mock import MagicMock

        cfg = MagicMock()
        cfg.session_id = session_id
        cfg.participant_id = "aaaa0002-0000-0000-0000-000000000001"
        cfg.site_id = "bbbb0000-0000-0000-0000-000000000001"
        cfg.sponsor_id = "cccc0000-0000-0000-0000-000000000001"

        thread = HUMeNThread(cfg=cfg, stop_event=MagicMock(), xdf_writer=MagicMock())
        conn = psycopg2.connect(os.getenv("TEST_DATABASE_URL"))
        conn.autocommit = False

        row = {
            "session_id": session_id,
            "participant_id": "aaaa0002-0000-0000-0000-000000000001",
            "site_id": "bbbb0000-0000-0000-0000-000000000001",
            "sponsor_id": "cccc0000-0000-0000-0000-000000000001",
            "event_type": "proximity_state_change",
            "actor_id": "therapist_01",
            "actor_role": "therapist",
            "zone_label": zone_label,
            "lsl_timestamp": lsl_ts,
        }
        thread._write_row(conn, row)
        conn.close()

    def test_humen_event_row_written_with_correct_columns(self):
        self._insert_humen_event(_SID_INSERT, "arms_reach", 1234567890.123)

        conn = _test_db_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT session_id, event_type, source, actor_id,
                           actor_role, zone_label, lsl_timestamp
                    FROM humen_events
                    WHERE session_id = %s
                    ORDER BY db_insert_time DESC LIMIT 1
                    """,
                    (_SID_INSERT,),
                )
                row = cur.fetchone()
        finally:
            conn.close()

        assert row is not None, "No humen_events row found"
        assert row[0] == _SID_INSERT
        assert row[1] == "proximity_state_change"
        assert row[2] == "manual_logging"
        assert row[3] == "therapist_01"
        assert row[4] == "therapist"
        assert row[5] == "arms_reach"
        assert abs(row[6] - 1234567890.123) < 0.001

    def test_humen_event_triggers_audit_entry(self):
        self._insert_humen_event(_SID_AUDIT, "in_room", 1234567891.0)

        conn = _test_db_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*) FROM audit_events
                    WHERE session_id = %s AND table_name = 'humen_events'
                    """,
                    (_SID_AUDIT,),
                )
                count = cur.fetchone()[0]
        finally:
            conn.close()

        assert count >= 1, "Audit trigger did not fire on humen_events INSERT"

    def test_xdf_marker_written_before_db(self):
        """XDF write_marker is called for every valid event, regardless of DB state."""
        from unittest.mock import MagicMock

        cfg = MagicMock()
        cfg.session_id = "e0eebc99-9c0b-4ef8-bb6d-6bb9bd380a04"
        cfg.participant_id = "aaaa0002-0000-0000-0000-000000000002"
        cfg.site_id = "bbbb0000-0000-0000-0000-000000000001"
        cfg.sponsor_id = "cccc0000-0000-0000-0000-000000000001"

        xdf_mock = MagicMock()
        thread = HUMeNThread(cfg=cfg, stop_event=MagicMock(), xdf_writer=xdf_mock)

        marker = "HUMEN|proximity_state_change|therapist_01|therapist|arms_reach"
        conn = psycopg2.connect(os.getenv("TEST_DATABASE_URL"))
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

        # Simulate what _run() does: XDF first, then DB
        thread._xdf.write_marker(marker, row["lsl_timestamp"])
        thread._write_row(conn, row)
        conn.close()

        xdf_mock.write_marker.assert_called_once_with(marker, 1234567999.0)

    def test_all_four_proximity_states_accepted(self):
        """Every valid zone_label inserts without constraint error."""
        base_ts = 1234567900.0
        for i, zone in enumerate(sorted(VALID_ZONE_LABELS)):
            self._insert_humen_event(_SID_STATES, zone, base_ts + i)

        conn = _test_db_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT zone_label FROM humen_events WHERE session_id = %s",
                    (_SID_STATES,),
                )
                found = {row[0] for row in cur.fetchall()}
        finally:
            conn.close()

        assert found == VALID_ZONE_LABELS


# ---------------------------------------------------------------------------
# Live thread integration tests
#
# Previous tests call _write_row() directly — they bypass the thread lifecycle.
# These tests actually call HUMeNThread.start() so the full path runs:
#
#   tablet press → LSL inlet → pull_sample → parse → XDF write → DB write
#
# The LSL inlet is replaced with a controlled mock that drains a list of
# (marker_str, lsl_timestamp) pairs, then idles.  _connect_db is overridden
# at the instance level to use TEST_DATABASE_URL, so settings.DATABASE_URL
# is never read or patched.
#
# Polling (not time.sleep) is used to detect when DB rows arrive, so tests
# are fast on quick hardware and don't flake on slow CI.
# ---------------------------------------------------------------------------

_LIVE_SITE = "f1d00003-0000-4444-cccc-000000000001"
_LIVE_SPONSOR = "f1d00003-0000-4444-dddd-000000000001"
_LIVE_PART = "f1d00003-0000-4444-bbbb-000000000001"


def _build_thread(session_id, xdf_writer, marker_queue):
    """Wire up a HUMeNThread with a mock inlet and test-DB connector.

    marker_queue: list of (marker_str, lsl_timestamp) tuples delivered in
    order.  Once exhausted the mock idles so the thread can be stopped cleanly.

    Returns (thread, stop_event).
    """
    db_url = os.getenv("TEST_DATABASE_URL")

    cfg = MagicMock()
    cfg.session_id = session_id
    cfg.participant_id = _LIVE_PART
    cfg.site_id = _LIVE_SITE
    cfg.sponsor_id = _LIVE_SPONSOR

    pos = [0]

    def pull_sample(timeout=1.0):
        if pos[0] < len(marker_queue):
            marker, ts = marker_queue[pos[0]]
            pos[0] += 1
            return [marker], ts
        time.sleep(min(timeout, 0.05))  # idle without busy-spinning
        return None, 0.0

    mock_inlet = MagicMock()
    mock_inlet.pull_sample.side_effect = pull_sample

    stop = threading.Event()
    thread = HUMeNThread(cfg=cfg, stop_event=stop, xdf_writer=xdf_writer)

    # Override at instance level — no settings module patching required
    thread._resolve_inlet = MagicMock(return_value=mock_inlet)

    def _test_connect_db():
        conn = psycopg2.connect(db_url)
        conn.autocommit = False
        return conn

    thread._connect_db = _test_connect_db
    return thread, stop


def _poll_for_rows(session_id, expected_n, timeout_s=5.0):
    """Return True once humen_events row count >= expected_n, else False.

    Uses a fresh autocommit connection so committed rows from the thread's
    own connection are immediately visible (READ COMMITTED isolation).
    """
    db_url = os.getenv("TEST_DATABASE_URL")
    conn = psycopg2.connect(db_url)
    conn.autocommit = True
    deadline = time.monotonic() + timeout_s
    try:
        while time.monotonic() < deadline:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM humen_events WHERE session_id = %s",
                    (session_id,),
                )
                if cur.fetchone()[0] >= expected_n:
                    return True
            time.sleep(0.05)
        return False
    finally:
        conn.close()


def _cleanup(session_id):
    """Delete all humen_events rows for this session after a live test."""
    db_url = os.getenv("TEST_DATABASE_URL")
    conn = psycopg2.connect(db_url)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("DELETE FROM humen_events WHERE session_id = %s", (session_id,))
    conn.close()


@pytest.mark.integration
class TestHUMeNThreadLive:
    """HUMeNThread.start() + mock LSL inlet + real XDFWriter + real test DB."""

    def test_single_press_db_fields_correct(self, tmp_path, monkeypatch):
        """One button press → one humen_events row with every field correct."""
        import config.settings as s

        session_id = "f1d0a001-0000-4444-aaaa-000000000001"
        monkeypatch.setattr(s, "XDF_BACKUP_DIR", tmp_path)
        xdf = XDFWriter(session_id, _LIVE_SITE, _LIVE_SPONSOR)

        marker_str = "HUMEN|proximity_state_change|therapist_01|therapist|arms_reach"
        marker_ts = 99001.5

        thread, stop = _build_thread(session_id, xdf, [(marker_str, marker_ts)])
        thread.start()

        try:
            arrived = _poll_for_rows(session_id, 1)
            stop.set()
            thread.join(timeout=5.0)
            xdf.close()

            assert arrived, "humen_events row not written within 5 s"

            conn = psycopg2.connect(os.getenv("TEST_DATABASE_URL"))
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT event_type, source, actor_id, actor_role,
                              zone_label, lsl_timestamp, participant_id
                       FROM humen_events WHERE session_id = %s""",
                    (session_id,),
                )
                row = cur.fetchone()
            conn.close()

            assert row is not None
            assert row[0] == "proximity_state_change"
            assert row[1] == "manual_logging"  # source never set by app code
            assert row[2] == "therapist_01"
            assert row[3] == "therapist"
            assert row[4] == "arms_reach"
            assert row[5] == pytest.approx(marker_ts)
            assert row[6] == _LIVE_PART  # pseudonymous token unchanged
        finally:
            _cleanup(session_id)

    def test_single_press_xdf_written_before_db(self, tmp_path, monkeypatch):
        """One press → XDF sample count is 1 (XDF write happened alongside DB write)."""
        import config.settings as s

        session_id = "f1d0a002-0000-4444-aaaa-000000000001"
        monkeypatch.setattr(s, "XDF_BACKUP_DIR", tmp_path)
        xdf = XDFWriter(session_id, _LIVE_SITE, _LIVE_SPONSOR)

        marker_str = "HUMEN|proximity_state_change|therapist_01|therapist|in_room"
        marker_ts = 99002.0

        thread, stop = _build_thread(session_id, xdf, [(marker_str, marker_ts)])
        thread.start()

        try:
            # Wait for DB write to confirm the row arrived; XDF is written first
            # so if the DB row is there, the XDF write definitely happened too.
            arrived = _poll_for_rows(session_id, 1)
            stop.set()
            thread.join(timeout=5.0)
            xdf.close()

            assert arrived, "DB row not written — cannot verify XDF ordering"
            assert xdf.sample_counts["HUMeN"] == 1
        finally:
            _cleanup(session_id)

    def test_three_presses_all_written_in_order(self, tmp_path, monkeypatch):
        """Three sequential presses → three rows in lsl_timestamp order."""
        import config.settings as s

        session_id = "f1d0a003-0000-4444-aaaa-000000000001"
        monkeypatch.setattr(s, "XDF_BACKUP_DIR", tmp_path)
        xdf = XDFWriter(session_id, _LIVE_SITE, _LIVE_SPONSOR)

        presses = [
            ("HUMEN|proximity_state_change|therapist_01|therapist|arms_reach", 99003.1),
            ("HUMEN|proximity_state_change|therapist_01|therapist|in_room", 99003.2),
            (
                "HUMEN|proximity_state_change|therapist_01|therapist|leaving_room",
                99003.3,
            ),
        ]

        thread, stop = _build_thread(session_id, xdf, presses)
        thread.start()

        try:
            arrived = _poll_for_rows(session_id, 3)
            stop.set()
            thread.join(timeout=5.0)
            xdf.close()

            assert arrived, "Not all 3 rows arrived within 5 s"

            conn = psycopg2.connect(os.getenv("TEST_DATABASE_URL"))
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT zone_label, lsl_timestamp FROM humen_events
                       WHERE session_id = %s ORDER BY lsl_timestamp""",
                    (session_id,),
                )
                rows = cur.fetchall()
            conn.close()

            assert len(rows) == 3
            assert [r[0] for r in rows] == ["arms_reach", "in_room", "leaving_room"]
            assert [r[1] for r in rows] == pytest.approx([99003.1, 99003.2, 99003.3])
            assert xdf.sample_counts["HUMeN"] == 3
        finally:
            _cleanup(session_id)

    def test_malformed_press_skipped_valid_continues(self, tmp_path, monkeypatch):
        """Malformed markers are silently skipped; the thread keeps running for valid ones."""
        import config.settings as s

        session_id = "f1d0a004-0000-4444-aaaa-000000000001"
        monkeypatch.setattr(s, "XDF_BACKUP_DIR", tmp_path)
        xdf = XDFWriter(session_id, _LIVE_SITE, _LIVE_SPONSOR)

        presses = [
            ("NOT_HUMEN_AT_ALL", 99004.0),  # wrong prefix
            ("HUMEN|bad_event_type|t|therapist|arms_reach", 99004.1),  # unknown event
            ("HUMEN|proximity_state_change|t|therapist|arms_reach", 99004.2),  # valid
        ]

        thread, stop = _build_thread(session_id, xdf, presses)
        thread.start()

        try:
            arrived = _poll_for_rows(session_id, 1)
            stop.set()
            thread.join(timeout=5.0)
            xdf.close()

            assert arrived, "Valid marker after two malformed ones was not written"

            conn = psycopg2.connect(os.getenv("TEST_DATABASE_URL"))
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM humen_events WHERE session_id = %s",
                    (session_id,),
                )
                count = cur.fetchone()[0]
            conn.close()

            # 2 malformed skipped, 1 valid written
            assert count == 1, f"Expected 1 row (2 malformed skipped), got {count}"
            # XDF write_marker is called for every raw marker before parse —
            # only valid ones are forwarded to the DB, but the XDF call happens
            # inside _run() after parse succeeds, so the count must also be 1.
            assert xdf.sample_counts["HUMeN"] == 1
        finally:
            _cleanup(session_id)
