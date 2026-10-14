"""Approved session-close fixtures: complete channel frames, real connections."""

import pytest

import capture.session_close.workflow as workflow
import capture.xdf.writer as writer_mod
from capture.xdf.constants import CHANNEL_COUNTS
from capture.xdf.writer import XDFWriter
from tests.capture_tests.session_close.support import (
    PARTICIPANT_ID,
    SESSION_ID,
    SITE_ID,
    SPONSOR_ID,
)


def _seed_session(cursor, status):
    cursor.execute(
        "INSERT INTO sessions (id, site_id, sponsor_id, participant_id, capture_source, "
        "compound, status, started_at) VALUES (%s,%s,%s,%s,'simulated','psilocybin',%s,NOW())",
        (SESSION_ID, SITE_ID, SPONSOR_ID, PARTICIPANT_ID, status),
    )


def _seed_eeg(cursor, count):
    for i in range(count):
        for channel in range(CHANNEL_COUNTS["EEG"]):
            cursor.execute(
                "INSERT INTO eeg_samples (session_id,participant_id,site_id,sponsor_id,"
                "device_id,lsl_timestamp,sample_index,channel_id,voltage) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    SESSION_ID,
                    PARTICIPANT_ID,
                    SITE_ID,
                    SPONSOR_ID,
                    "00000000-0000-4000-8000-000000000099",
                    1000.0 + i,
                    i,
                    f"ch_{channel}",
                    float(i),
                ),
            )


def _make_xdf(tmp_path, monkeypatch, count):
    monkeypatch.setattr(writer_mod.settings, "XDF_BACKUP_DIR", str(tmp_path))
    writer = XDFWriter(
        SESSION_ID,
        PARTICIPANT_ID,
        SITE_ID,
        SPONSOR_ID,
        eeg_channel_names=tuple(f"ch_{i}" for i in range(CHANNEL_COUNTS["EEG"])),
    )
    if count:
        writer.write_samples(
            "EEG",
            [[float(i)] * CHANNEL_COUNTS["EEG"] for i in range(count)],
            [1000.0 + i for i in range(count)],
        )
    writer.close()
    return writer._path


def _status(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT status FROM sessions WHERE id=%s", (SESSION_ID,))
        row = cur.fetchone()
        return row[0] if row else None


def _cleanup(conn):
    conn.rollback()
    with conn.cursor() as cur:
        for table in (
            "alert_events",
            "echo_events",
            "eeg_samples",
            "biosignal_integrity_log",
            "schema_version_log",
            "session_signal_metadata",
            "sessions",
        ):
            key = "id" if table == "sessions" else "session_id"
            cur.execute(f"DELETE FROM {table} WHERE {key}=%s", (SESSION_ID,))
    conn.commit()


@pytest.fixture
def sc_valid_xdf(tmp_path, monkeypatch):
    return _make_xdf(tmp_path, monkeypatch, 2)


@pytest.fixture
def sc_session_active(cursor, db_conn):
    _seed_session(cursor, "active")
    db_conn.commit()
    yield {"status_after": lambda: _status(db_conn)}
    _cleanup(db_conn)


@pytest.fixture
def sc_session_closed(cursor, db_conn):
    _seed_session(cursor, "closed")
    db_conn.commit()
    yield
    _cleanup(db_conn)


@pytest.fixture
def sc_reconciled_session(cursor, db_conn, tmp_path, monkeypatch):
    _seed_session(cursor, "active")
    _seed_eeg(cursor, 3)
    db_conn.commit()
    path = _make_xdf(tmp_path, monkeypatch, 3)
    flags = {"closed": False, "log": False}
    import batch.reconciliation.db as recon_db

    original_write = recon_db.write_reconciliation_log

    def tracking_write(*args, **kwargs):
        result = original_write(*args, **kwargs)
        flags["log"] = True
        return result

    monkeypatch.setattr(recon_db, "write_reconciliation_log", tracking_write)
    original_connect = workflow.connect_db

    class TrackedConnection:
        def __init__(self, conn):
            self.conn = conn

        def __getattr__(self, name):
            return getattr(self.conn, name)

        def close(self):
            self.conn.close()
            flags["closed"] = bool(self.conn.closed)

    monkeypatch.setattr(workflow, "connect_db", lambda: TrackedConnection(original_connect()))
    yield {
        "xdf_path": path,
        "status_after": lambda: _status(db_conn),
        "log_written": lambda: flags["log"],
        "conn_closed": lambda: flags["closed"],
    }
    _cleanup(db_conn)


@pytest.fixture
def sc_negative_gap_session(cursor, db_conn, tmp_path, monkeypatch):
    _seed_session(cursor, "active")
    _seed_eeg(cursor, 5)
    db_conn.commit()
    path = _make_xdf(tmp_path, monkeypatch, 2)
    import capture.session_close.reconciliation as recon

    calls = []
    monkeypatch.setattr(recon, "run_backfill", lambda *a, **k: calls.append(True))
    yield {"xdf_path": path, "backfill_calls": lambda: len(calls)}
    _cleanup(db_conn)


@pytest.fixture
def sc_gap_session(cursor, db_conn, tmp_path, monkeypatch):
    _seed_session(cursor, "active")
    _seed_eeg(cursor, 2)
    db_conn.commit()
    path = _make_xdf(tmp_path, monkeypatch, 3)
    import capture.session_close.reconciliation as recon

    original = recon.build_report
    calls = []

    def count(*a, **k):
        calls.append(True)
        return original(*a, **k)

    monkeypatch.setattr(recon, "build_report", count)
    yield {"xdf_path": path, "reconcile_calls": lambda: len(calls)}
    _cleanup(db_conn)


@pytest.fixture
def sc_unfillable_gap_session(cursor, db_conn, tmp_path, monkeypatch):
    _seed_session(cursor, "active")
    db_conn.commit()
    path = _make_xdf(tmp_path, monkeypatch, 3)
    import capture.session_close.reconciliation as recon

    monkeypatch.setattr(recon, "run_backfill", lambda *a, **k: {})
    yield {"xdf_path": path, "status_after": lambda: _status(db_conn)}
    _cleanup(db_conn)
