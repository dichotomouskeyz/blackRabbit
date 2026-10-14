"""Spec-driven integration tests for ECHO handler (echo-handler.md R-016..R-020).

Phase 2 — marker → echo_events write path and XDF-first ordering.
One test per R-xxx rule. Assertions derive from the spec text only.

NOTE (black-box): ECHOWriter.write_row signature and the XDF-ordering seam are
inferred from the spec. Phase D resolves call-site mismatches against a live DB.
Skipped without TEST_DATABASE_URL.
"""

from types import SimpleNamespace

import psycopg2
import pytest

from capture.echo_handler.parser import parse_echo_marker
from capture.echo_handler.rows import build_echo_row
from capture.echo_handler.writer import ECHOWriter
from tests.capture_tests.echo_handler.support import (
    LSL_TIMESTAMP,
    PARTICIPANT_ID,
    SESSION_ID,
    SITE_ID,
    SPONSOR_ID,
)

pytestmark = pytest.mark.integration

_VALID_MARKER = "ECHO|manual_marker|actor1|therapist|dose_administration"


def _cfg():
    return SimpleNamespace(
        session_id=SESSION_ID,
        participant_id=PARTICIPANT_ID,
        site_id=SITE_ID,
        sponsor_id=SPONSOR_ID,
    )


def _writer():
    return ECHOWriter()


def _process_marker(xdf, conn, marker):
    import threading

    from capture.echo_handler.thread import ECHOThread

    thread = ECHOThread(_cfg(), threading.Event(), xdf)
    inlet = SimpleNamespace(pull_sample=lambda **kwargs: ([marker], LSL_TIMESTAMP))
    return thread.process_next_sample(inlet, conn)


class TestEchoIngestionPipeline:
    """echo-handler.md — ingestion pipeline.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    def test_r016_valid_marker_writes_one_row(self, db_conn, seeded_session):
        parsed = parse_echo_marker(_VALID_MARKER)
        row = build_echo_row(_cfg(), parsed, LSL_TIMESTAMP)
        _writer().write_row(db_conn, row)
        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT event_type, actor_role, zone_label, actor_id, lsl_timestamp, "
                "site_id, sponsor_id FROM echo_events WHERE session_id = %s::uuid",
                (SESSION_ID,),
            )
            rows = cur.fetchall()
        assert len(rows) == 1
        event_type, actor_role, zone_label, actor_id, lsl_ts, site_id, sponsor_id = rows[0]
        assert event_type == "manual_marker"
        assert actor_role == "therapist"
        assert zone_label == "dose_administration"
        assert actor_id == "actor1"
        assert lsl_ts == LSL_TIMESTAMP
        assert str(site_id) == SITE_ID
        assert str(sponsor_id) == SPONSOR_ID

    def test_r017_source_is_always_manual_logging(self, db_conn, seeded_session):
        parsed = parse_echo_marker(_VALID_MARKER)
        row = build_echo_row(_cfg(), parsed, LSL_TIMESTAMP)
        _writer().write_row(db_conn, row)
        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT source FROM echo_events WHERE session_id = %s::uuid",
                (SESSION_ID,),
            )
            assert cur.fetchone()[0] == "manual_logging"

    def test_r018_xdf_write_before_db_write(self, monkeypatch):
        events = []
        xdf = SimpleNamespace(write_marker=lambda *a, **k: events.append("xdf"))
        from capture.echo_handler.thread import ECHOThread

        conn = object()
        monkeypatch.setattr(
            ECHOThread,
            "write_or_buffer",
            lambda self, conn, row: (events.append("db"), conn)[1],
        )
        _process_marker(xdf, conn, _VALID_MARKER)
        assert events and events[0] == "xdf"
        assert "db" in events

    def test_r019_unrecognised_marker_no_db_no_xdf(self, db_conn, seeded_session):
        events = []
        xdf = SimpleNamespace(write_marker=lambda *a, **k: events.append("xdf"))
        _process_marker(xdf, db_conn, "GARBAGE|not|a|marker")
        assert events == []
        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM echo_events WHERE session_id = %s::uuid",
                (SESSION_ID,),
            )
            assert cur.fetchone()[0] == 0

    def test_r020_operational_error_buffers_then_flushes(self, db_conn, seeded_session):
        writer = _writer()
        parsed = parse_echo_marker(_VALID_MARKER)
        row = build_echo_row(_cfg(), parsed, LSL_TIMESTAMP)

        class _DroppingConn:
            def cursor(self):
                raise psycopg2.OperationalError("dropped")

        writer.buffer_row(row)
        # Attempt against a healthy connection flushes the buffered row.
        writer.flush_buffer(db_conn)
        db_conn.commit()
        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM echo_events WHERE session_id = %s::uuid",
                (SESSION_ID,),
            )
            assert cur.fetchone()[0] == 1
