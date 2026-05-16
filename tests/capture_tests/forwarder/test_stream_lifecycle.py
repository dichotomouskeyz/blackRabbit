"""_StreamThread integration lifecycle tests — real thread, real test DB."""

import queue
import threading
import time
from unittest.mock import MagicMock

import psycopg2
import pytest

from capture.forwarder import (
    SessionConfig,
    _EEG_INSERT,
    _StreamThread,
    _build_eeg_rows,
)

_SESSION = "f1d00008-0000-4444-aaaa-000000000001"
_PART = "f1d00008-0000-4444-bbbb-000000000001"
_SITE = "f1d00008-0000-4444-cccc-000000000001"
_SPONSOR = "f1d00008-0000-4444-dddd-000000000001"

_CFG = SessionConfig(
    session_id=_SESSION,
    participant_id=_PART,
    site_id=_SITE,
    sponsor_id=_SPONSOR,
)

_EEG_SAMPLE = [0.1, 0.2, 0.3, 0.4, -0.1, -0.2, -0.3, -0.4]


def _make_thread(
    stop_event: threading.Event | None = None,
    xdf_writer=None,
    stream_type: str = "EEG",
    cfg: SessionConfig = _CFG,
) -> _StreamThread:
    if stop_event is None:
        stop_event = threading.Event()
    if xdf_writer is None:
        xdf_writer = MagicMock()
    return _StreamThread(
        stream_name=f"Test{stream_type}",
        stream_type=stream_type,
        chunk_size=25,
        row_builder=_build_eeg_rows,
        insert_sql=_EEG_INSERT,
        cfg=cfg,
        stop_event=stop_event,
        xdf_writer=xdf_writer,
        table_name="eeg_samples",
        hash_fields=("sample_index", "channel_id", "voltage"),
        hash_sort_keys=("sample_index", "channel_id"),
    )


class _FakeInlet:
    """Mock LSL inlet backed by a queue."""

    def __init__(self, sample_q, done_event=None, lsl_ts_start=1000.0):
        self._q = sample_q
        self._done = done_event
        self._ts = lsl_ts_start

    def pull_chunk(self, timeout=1.0, max_samples=25):
        samples = []
        timestamps = []
        for _ in range(max_samples):
            try:
                sample = self._q.get_nowait()
                samples.append(sample)
                self._ts += 0.004
                timestamps.append(self._ts)
            except queue.Empty:
                break

        if not samples:
            if self._done is not None and self._q.empty():
                self._done.set()
            time.sleep(min(timeout, 0.02))
            return [], []

        return samples, timestamps

    def time_correction(self, timeout=5.0):
        return 0.001


def _db_conn(db_url):
    c = psycopg2.connect(db_url)
    c.autocommit = True
    return c


def _cleanup(db_url, session_id):
    conn = _db_conn(db_url)
    cur = conn.cursor()
    cur.execute("DELETE FROM clock_drift_log WHERE session_id = %s", (session_id,))
    cur.execute("DELETE FROM eeg_samples WHERE session_id = %s", (session_id,))
    cur.execute("DELETE FROM audit_events WHERE session_id = %s", (session_id,))
    cur.execute("DELETE FROM sessions WHERE id = %s", (session_id,))
    cur.close()
    conn.close()


def _count_drift_rows(db_url, session_id):
    conn = _db_conn(db_url)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM clock_drift_log WHERE session_id = %s", (session_id,))
    n = cur.fetchone()[0]
    cur.close()
    conn.close()
    return n


def _fetch_drift_row(db_url, session_id):
    conn = _db_conn(db_url)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT stream_type, remote_clock_offset_s, exceeds_threshold, threshold_s
        FROM clock_drift_log WHERE session_id = %s ORDER BY db_insert_time LIMIT 1
        """,
        (session_id,),
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row


def _count_eeg_rows(db_url, session_id):
    conn = _db_conn(db_url)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM eeg_samples WHERE session_id = %s", (session_id,))
    n = cur.fetchone()[0]
    cur.close()
    conn.close()
    return n


def _insert_session_row(db_url, session_id):
    conn = _db_conn(db_url)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO sessions (id, site_id, sponsor_id, participant_id,
                              compound, status, started_at)
        VALUES (%s, %s::uuid, %s::uuid, %s::uuid, 'psilocybin', 'active', NOW())
        ON CONFLICT (id) DO NOTHING
        """,
        (session_id, _SITE, _SPONSOR, _PART),
    )
    cur.close()
    conn.close()


@pytest.mark.integration
class TestStreamThreadLifecycle:
    def test_thread_exits_if_inlet_not_found(self):
        stop = threading.Event()
        t = _make_thread(stop_event=stop)
        t._resolve_inlet = lambda: None

        t.start()
        t.join(timeout=2.0)

        assert not t.is_alive(), "thread did not exit after inlet not found"

    def test_thread_stops_on_stop_event(self, db_url):
        session_id = "f1d00008-0000-4444-aaaa-000000000002"
        _insert_session_row(db_url, session_id)

        cfg = SessionConfig(
            session_id=session_id, participant_id=_PART, site_id=_SITE, sponsor_id=_SPONSOR
        )
        stop = threading.Event()
        xdf = MagicMock()
        t = _make_thread(stop_event=stop, xdf_writer=xdf, cfg=cfg)

        sample_q: queue.Queue = queue.Queue()
        t._resolve_inlet = lambda: _FakeInlet(sample_q)
        t._connect_db = lambda: (lambda conn: setattr(conn, "autocommit", False) or conn)(
            psycopg2.connect(db_url)
        )

        try:
            t.start()
            assert t.is_alive()
            stop.set()
            t.join(timeout=5.0)
            assert not t.is_alive(), "thread did not stop within 5 s"
        finally:
            _cleanup(db_url, session_id)

    def test_thread_writes_eeg_samples_to_db(self, db_url):
        session_id = "f1d00008-0000-4444-aaaa-000000000003"
        _insert_session_row(db_url, session_id)

        cfg = SessionConfig(
            session_id=session_id, participant_id=_PART, site_id=_SITE, sponsor_id=_SPONSOR
        )
        stop = threading.Event()
        xdf = MagicMock()
        t = _make_thread(stop_event=stop, xdf_writer=xdf, cfg=cfg)

        n_chunks = 2
        samples_per_chunk = 3
        sample_q: queue.Queue = queue.Queue()
        done = threading.Event()

        for _ in range(n_chunks * samples_per_chunk):
            sample_q.put(list(_EEG_SAMPLE))

        t._resolve_inlet = lambda: _FakeInlet(sample_q, done_event=done)
        t._connect_db = lambda: (lambda conn: setattr(conn, "autocommit", False) or conn)(
            psycopg2.connect(db_url)
        )

        try:
            t.start()
            done.wait(timeout=5.0)
            time.sleep(0.1)
            stop.set()
            t.join(timeout=5.0)

            expected_rows = n_chunks * samples_per_chunk * 8
            actual = _count_eeg_rows(db_url, session_id)
            assert actual == expected_rows, f"expected {expected_rows} eeg_samples rows, got {actual}"
        finally:
            _cleanup(db_url, session_id)

    def test_thread_writes_xdf_before_db(self, db_url, tmp_path):
        session_id = "f1d00008-0000-4444-aaaa-000000000004"
        _insert_session_row(db_url, session_id)

        cfg = SessionConfig(
            session_id=session_id, participant_id=_PART, site_id=_SITE, sponsor_id=_SPONSOR
        )
        stop = threading.Event()
        xdf = MagicMock()
        xdf_calls: list[str] = []
        db_commit_calls: list[str] = []

        def _xdf_write(stream_type, samples, timestamps):
            xdf_calls.append("xdf")

        xdf.write_samples = _xdf_write

        sample_q: queue.Queue = queue.Queue()
        done = threading.Event()
        sample_q.put(list(_EEG_SAMPLE))

        t = _make_thread(stop_event=stop, xdf_writer=xdf, cfg=cfg)
        original_write_rows = t._write_rows

        def _tracked_write_rows(conn, rows):
            result = original_write_rows(conn, rows)
            if result is not None:
                db_commit_calls.append("db")
            return result

        t._write_rows = _tracked_write_rows
        t._resolve_inlet = lambda: _FakeInlet(sample_q, done_event=done)
        t._connect_db = lambda: (lambda conn: setattr(conn, "autocommit", False) or conn)(
            psycopg2.connect(db_url)
        )

        try:
            t.start()
            done.wait(timeout=5.0)
            time.sleep(0.1)
            stop.set()
            t.join(timeout=5.0)

            assert xdf_calls, "XDF writer was never called"
            assert db_commit_calls, "DB was never committed"
            all_calls = xdf_calls + db_commit_calls
            assert all_calls.index("xdf") < all_calls.index("db"), (
                "DB was committed before XDF was written"
            )
        finally:
            _cleanup(db_url, session_id)

    def test_sample_index_increments_across_chunks(self, db_url):
        session_id = "f1d00008-0000-4444-aaaa-000000000005"
        _insert_session_row(db_url, session_id)

        cfg = SessionConfig(
            session_id=session_id, participant_id=_PART, site_id=_SITE, sponsor_id=_SPONSOR
        )
        stop = threading.Event()
        xdf = MagicMock()
        t = _make_thread(stop_event=stop, xdf_writer=xdf, cfg=cfg)

        sample_q: queue.Queue = queue.Queue()
        done = threading.Event()
        n_samples = 5
        for _ in range(n_samples):
            sample_q.put(list(_EEG_SAMPLE))

        t._resolve_inlet = lambda: _FakeInlet(sample_q, done_event=done)
        t._connect_db = lambda: (lambda conn: setattr(conn, "autocommit", False) or conn)(
            psycopg2.connect(db_url)
        )

        try:
            t.start()
            done.wait(timeout=5.0)
            time.sleep(0.1)
            stop.set()
            t.join(timeout=5.0)

            conn = _db_conn(db_url)
            cur = conn.cursor()
            cur.execute(
                "SELECT DISTINCT sample_index FROM eeg_samples WHERE session_id = %s ORDER BY sample_index",
                (session_id,),
            )
            indices = [r[0] for r in cur.fetchall()]
            cur.close()
            conn.close()

            assert len(indices) == n_samples
            assert indices == list(range(n_samples))
        finally:
            _cleanup(db_url, session_id)

    def test_clock_drift_written_to_db(self, db_url):
        session_id = "f1d00008-0000-4444-aaaa-000000000006"
        _insert_session_row(db_url, session_id)

        cfg = SessionConfig(
            session_id=session_id, participant_id=_PART, site_id=_SITE, sponsor_id=_SPONSOR
        )
        stop = threading.Event()
        xdf = MagicMock()
        t = _make_thread(stop_event=stop, xdf_writer=xdf, cfg=cfg)

        sample_q: queue.Queue = queue.Queue()
        done = threading.Event()
        sample_q.put(list(_EEG_SAMPLE))

        t._resolve_inlet = lambda: _FakeInlet(sample_q, done_event=done)
        t._connect_db = lambda: (lambda conn: setattr(conn, "autocommit", False) or conn)(
            psycopg2.connect(db_url)
        )

        try:
            t.start()
            done.wait(timeout=5.0)
            time.sleep(0.1)
            stop.set()
            t.join(timeout=5.0)

            assert _count_drift_rows(db_url, session_id) >= 1, "no clock_drift_log row written"

            row = _fetch_drift_row(db_url, session_id)
            assert row is not None
            stream_type, offset_s, exceeds, threshold_s = row
            assert stream_type == "EEG"
            assert abs(offset_s - 0.001) < 1e-6, f"unexpected offset {offset_s}"
            assert exceeds is False
            assert threshold_s == pytest.approx(0.1)
        finally:
            _cleanup(db_url, session_id)
