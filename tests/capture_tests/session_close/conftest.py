"""session_close conftest: import guard + integration fixtures.

Import guard: importing `capture.session_close.workflow` calls `settings.validate()`
at module level. Neutralise it only for that one import, then restore.
"""

from pathlib import Path

import pytest

import capture.xdf.writer as writer_mod
import config.settings as settings
from capture.xdf.constants import CHANNEL_COUNTS
from capture.xdf.writer import XDFWriter
from tests.capture_tests.session_close.support import (
    PARTICIPANT_ID,
    SESSION_ID,
    SITE_ID,
    SPONSOR_ID,
)

_orig_validate = settings.validate
settings.validate = lambda: None
try:  # noqa: SIM105 - explicit for clarity
    import capture.session_close.workflow  # noqa: F401
finally:
    settings.validate = _orig_validate

# ---------------------------------------------------------------------------
# Integration fixtures for test_run.py
# ---------------------------------------------------------------------------
import capture.session_close.workflow as wf  # noqa: E402

_EEG_CH = CHANNEL_COUNTS["EEG"]


def _eeg_sample(v: float) -> list:
    return [float(v)] * _EEG_CH


def _seed_session(cursor, status: str) -> None:
    cursor.execute(
        """
        INSERT INTO sessions
            (id, site_id, sponsor_id, participant_id, capture_source,
             compound, status, started_at)
        VALUES
            (%s::uuid, %s::uuid, %s::uuid, %s::uuid, 'simulated',
             'psilocybin', %s::session_status, NOW())
        """,
        (SESSION_ID, SITE_ID, SPONSOR_ID, PARTICIPANT_ID, status),
    )


def _seed_eeg(cursor, n: int, start_ts: float = 1000.0) -> None:
    for i in range(n):
        cursor.execute(
            """
            INSERT INTO eeg_samples
                (id, session_id, participant_id, site_id, sponsor_id,
                 device_id, lsl_timestamp, db_insert_time, sample_index,
                 channel_id, voltage)
            VALUES
                (gen_random_uuid(), %s::uuid, %s::uuid, %s::uuid, %s::uuid,
                 %s::uuid, %s, NOW(), %s, 'ch_0', 1.0)
            """,
            (
                SESSION_ID,
                PARTICIPANT_ID,
                SITE_ID,
                SPONSOR_ID,
                "00000000-0000-4000-8000-000000000099",
                start_ts + i,
                i,
            ),
        )


def _make_xdf(tmp_path: Path, monkeypatch, n_samples: int) -> Path:
    monkeypatch.setattr(writer_mod.settings, "XDF_BACKUP_DIR", str(tmp_path), raising=False)
    writer = XDFWriter(SESSION_ID, PARTICIPANT_ID, SITE_ID, SPONSOR_ID)
    if n_samples > 0:
        writer.write_samples(
            "EEG",
            [_eeg_sample(i) for i in range(n_samples)],
            [1000.0 + i for i in range(n_samples)],
        )
    writer.close()
    return writer._path


def _status_after(db_conn) -> callable:
    def _():
        with db_conn.cursor() as cur:
            cur.execute("SELECT status FROM sessions WHERE id = %s::uuid", (SESSION_ID,))
            row = cur.fetchone()
            return row[0] if row else None

    return _


def _alert_written(db_conn) -> callable:
    def _(alert_type: str) -> bool:
        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM alert_events WHERE session_id = %s::uuid AND alert_type = %s",
                (SESSION_ID, alert_type),
            )
            return cur.fetchone()[0] > 0

    return _


def _cleanup(cursor, db_conn) -> None:
    db_conn.rollback()
    for stmt in (
        "DELETE FROM alert_events WHERE session_id = %s::uuid",
        "DELETE FROM echo_events WHERE session_id = %s::uuid",
        "DELETE FROM eeg_samples WHERE session_id = %s::uuid",
        "DELETE FROM biosignal_integrity_log WHERE session_id = %s::uuid",
        "DELETE FROM schema_version_log WHERE session_id = %s::uuid",
        "DELETE FROM session_signal_metadata WHERE session_id = %s::uuid",
        "DELETE FROM sessions WHERE id = %s::uuid",
    ):
        try:
            cursor.execute(stmt, (SESSION_ID,))
        except Exception:
            db_conn.rollback()
    db_conn.commit()


@pytest.fixture
def sc_valid_xdf(tmp_path, monkeypatch):
    """A closed, well-formed XDF with one EEG sample — valid for all exit-code tests."""
    return _make_xdf(tmp_path, monkeypatch, n_samples=2)


@pytest.fixture
def sc_session_active(cursor, db_conn):
    """Active session; status_after() queries the DB after run()."""
    _seed_session(cursor, "active")
    db_conn.commit()
    yield {"status_after": _status_after(db_conn)}
    _cleanup(cursor, db_conn)


@pytest.fixture
def sc_session_closed(cursor, db_conn):
    """Already-closed session — run() must return 2 (non-closeable state)."""
    _seed_session(cursor, "closed")
    db_conn.commit()
    yield
    _cleanup(cursor, db_conn)


@pytest.fixture
def sc_reconciled_session(cursor, db_conn, tmp_path, monkeypatch):
    """Session where DB and XDF agree (gap = 0) → run() closes reconciled, returns 0."""
    _seed_session(cursor, "active")
    _seed_eeg(cursor, 3)
    db_conn.commit()
    xdf_path = _make_xdf(tmp_path, monkeypatch, n_samples=3)

    # Patch ARC so it doesn't need a real config file.
    monkeypatch.setattr(wf, "load_arc_watchdog_config", lambda: _FakeArcConfig())
    monkeypatch.setattr(wf, "run_arc_post_session", lambda conn, sid, sponsor: _FakeArcResult())

    log_written_flag = {"v": False}
    _orig_write = None

    import batch.reconciliation.db as _recon_db

    _orig_write = _recon_db.write_reconciliation_log

    def _tracking_write(*a, **kw):
        log_written_flag["v"] = True
        return _orig_write(*a, **kw)

    monkeypatch.setattr(_recon_db, "write_reconciliation_log", _tracking_write)

    conn_closed_flag = {"v": False}
    _orig_run = wf.run

    def _tracking_run(session_id, sponsor_id, xdf_path):
        result = _orig_run(session_id, sponsor_id, xdf_path)
        conn_closed_flag["v"] = True  # if run() returned, finally ran
        return result

    yield {
        "xdf_path": xdf_path,
        "status_after": _status_after(db_conn),
        "log_written": lambda: log_written_flag["v"],
        "conn_closed": lambda: conn_closed_flag["v"],
    }
    _cleanup(cursor, db_conn)


@pytest.fixture
def sc_negative_gap_session(cursor, db_conn, tmp_path, monkeypatch):
    """DB > XDF (negative gap) — backfill must not run."""
    _seed_session(cursor, "active")
    _seed_eeg(cursor, 5)  # 5 in DB
    db_conn.commit()
    xdf_path = _make_xdf(tmp_path, monkeypatch, n_samples=2)  # only 2 in XDF

    monkeypatch.setattr(wf, "load_arc_watchdog_config", lambda: _FakeArcConfig())
    monkeypatch.setattr(wf, "run_arc_post_session", lambda conn, sid, sponsor: _FakeArcResult())

    call_count = {"n": 0}
    import capture.session_close.reconciliation as sc_recon

    _orig_backfill = sc_recon.run_backfill

    def _counting_backfill(*a, **kw):
        call_count["n"] += 1
        return _orig_backfill(*a, **kw)

    monkeypatch.setattr(sc_recon, "run_backfill", _counting_backfill)

    yield {
        "xdf_path": xdf_path,
        "backfill_calls": lambda: call_count["n"],
    }
    _cleanup(cursor, db_conn)


@pytest.fixture
def sc_gap_session(cursor, db_conn, tmp_path, monkeypatch):
    """XDF > DB (positive gap) — backfill runs, reconcile called twice."""
    _seed_session(cursor, "active")
    _seed_eeg(cursor, 2)  # 2 in DB
    db_conn.commit()
    xdf_path = _make_xdf(tmp_path, monkeypatch, n_samples=3)  # 3 in XDF

    monkeypatch.setattr(wf, "load_arc_watchdog_config", lambda: _FakeArcConfig())
    monkeypatch.setattr(wf, "run_arc_post_session", lambda conn, sid, sponsor: _FakeArcResult())

    call_count = {"n": 0}
    import capture.session_close.reconciliation as sc_recon

    _orig_build = sc_recon.build_report

    def _counting_build(*a, **kw):
        call_count["n"] += 1
        return _orig_build(*a, **kw)

    monkeypatch.setattr(sc_recon, "build_report", _counting_build)

    yield {
        "xdf_path": xdf_path,
        "reconcile_calls": lambda: call_count["n"],
    }
    _cleanup(cursor, db_conn)


@pytest.fixture
def sc_unfillable_gap_session(cursor, db_conn, tmp_path, monkeypatch):
    """XDF > DB but backfill fills nothing → run() returns 1, status = failed."""
    _seed_session(cursor, "active")
    # 0 EEG in DB; 3 in XDF — gap of 3.
    db_conn.commit()
    xdf_path = _make_xdf(tmp_path, monkeypatch, n_samples=3)

    monkeypatch.setattr(wf, "load_arc_watchdog_config", lambda: _FakeArcConfig())
    monkeypatch.setattr(wf, "run_arc_post_session", lambda conn, sid, sponsor: _FakeArcResult())

    # Backfill no-op: simulates samples that can't be inserted.
    import capture.session_close.reconciliation as sc_recon

    monkeypatch.setattr(sc_recon, "run_backfill", lambda *a, **kw: {})

    yield {
        "xdf_path": xdf_path,
        "status_after": _status_after(db_conn),
    }
    _cleanup(cursor, db_conn)


@pytest.fixture
def sc_arc_config_broken(cursor, db_conn, tmp_path, monkeypatch):
    """load_arc_watchdog_config raises → run() returns 1, arc_failure alert written."""
    _seed_session(cursor, "active")
    _seed_eeg(cursor, 2)
    db_conn.commit()
    xdf_path = _make_xdf(tmp_path, monkeypatch, n_samples=2)

    monkeypatch.setattr(
        wf, "load_arc_watchdog_config", lambda: (_ for _ in ()).throw(RuntimeError("bad config"))
    )

    yield {
        "xdf_path": xdf_path,
        "alert_written": _alert_written(db_conn),
    }
    _cleanup(cursor, db_conn)


@pytest.fixture
def sc_arc_raises(cursor, db_conn, tmp_path, monkeypatch):
    """run_arc_post_session raises ARCPostSessionError → run() returns 1."""
    from batch.arc.processor import ARCPostSessionError

    _seed_session(cursor, "active")
    _seed_eeg(cursor, 2)
    db_conn.commit()
    xdf_path = _make_xdf(tmp_path, monkeypatch, n_samples=2)

    monkeypatch.setattr(wf, "load_arc_watchdog_config", lambda: _FakeArcConfig())
    monkeypatch.setattr(
        wf,
        "run_arc_post_session",
        lambda conn, sid, sponsor: (_ for _ in ()).throw(ARCPostSessionError("arc boom")),
    )

    yield {
        "xdf_path": xdf_path,
        "alert_written": _alert_written(db_conn),
        "alert_used_own_conn": lambda: _alert_written(db_conn)("arc_failure"),
    }
    _cleanup(cursor, db_conn)


# ---------------------------------------------------------------------------
# Minimal stubs for ARC integration points
# ---------------------------------------------------------------------------


class _FakeArcConfig:
    version_label = "test"
    path = Path("test.toml")
    config_version = "test-001"
    content_sha256 = "a" * 64


class _FakeArcResult:
    canonical_anchor_count = 0
    cluster_count = 0
    baseline_row_count = 0
