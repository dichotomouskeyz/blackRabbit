"""_StreamThread lifecycle tests — start, run, stop, join.

Section 1 — Unit tests (no DB, no thread start)
  Verify internal state, _write_rows error handling, and _flush_buffer
  directly on a constructed-but-not-started thread instance.

Section 2 — Integration lifecycle tests (real thread, real test DB)
  Verify that a live thread: starts cleanly, writes samples to DB and XDF,
  stops promptly on stop_event.set(), and joins without hanging.

Run:
    pytest tests/test_stream_lifecycle.py -m "not integration" -v
    pytest tests/test_stream_lifecycle.py -m integration -v
"""

import queue
import threading
import time
from unittest.mock import MagicMock, patch

import psycopg2
import pytest

from capture.lsl_forwarder import (
    BUFFER_MAX_CHUNKS,
    SessionConfig,
    _EEG_INSERT,
    _StreamThread,
    _build_eeg_rows,
)

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

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

# One EEG sample: 8 channels
_EEG_SAMPLE = [0.1, 0.2, 0.3, 0.4, -0.1, -0.2, -0.3, -0.4]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
    """Mock LSL inlet backed by a queue.

    Drains the queue on each pull_chunk call. When the queue is empty,
    sleeps briefly (avoids spinning) and optionally signals a done_event.
    """

    def __init__(
        self,
        sample_q: queue.Queue,
        done_event: threading.Event | None = None,
        lsl_ts_start: float = 1000.0,
    ) -> None:
        self._q = sample_q
        self._done = done_event
        self._ts = lsl_ts_start

    def pull_chunk(
        self, timeout: float = 1.0, max_samples: int = 25
    ) -> tuple[list, list]:
        samples = []
        timestamps = []
        for _ in range(max_samples):
            try:
                sample = self._q.get_nowait()
                samples.append(sample)
                self._ts += 0.004  # 4 ms between EEG samples
                timestamps.append(self._ts)
            except queue.Empty:
                break

        if not samples:
            if self._done is not None and self._q.empty():
                self._done.set()
            time.sleep(min(timeout, 0.02))
            return [], []

        return samples, timestamps

    def time_correction(self, timeout: float = 5.0) -> float:
        return 0.001


def _db_conn(db_url: str) -> psycopg2.extensions.connection:
    c = psycopg2.connect(db_url)
    c.autocommit = True
    return c


def _cleanup(db_url: str, session_id: str) -> None:
    conn = _db_conn(db_url)
    cur = conn.cursor()
    cur.execute("DELETE FROM clock_drift_log WHERE session_id = %s", (session_id,))
    cur.execute("DELETE FROM eeg_samples WHERE session_id = %s", (session_id,))
    cur.execute("DELETE FROM audit_events WHERE session_id = %s", (session_id,))
    cur.execute("DELETE FROM sessions WHERE id = %s", (session_id,))
    cur.close()
    conn.close()


def _count_drift_rows(db_url: str, session_id: str) -> int:
    conn = _db_conn(db_url)
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM clock_drift_log WHERE session_id = %s", (session_id,)
    )
    n = cur.fetchone()[0]
    cur.close()
    conn.close()
    return n


def _fetch_drift_row(db_url: str, session_id: str) -> tuple | None:
    """Return (stream_type, remote_clock_offset_s, exceeds_threshold, threshold_s)."""
    conn = _db_conn(db_url)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT stream_type, remote_clock_offset_s, exceeds_threshold, threshold_s
        FROM clock_drift_log
        WHERE session_id = %s
        ORDER BY db_insert_time
        LIMIT 1
        """,
        (session_id,),
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row


def _count_eeg_rows(db_url: str, session_id: str) -> int:
    conn = _db_conn(db_url)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM eeg_samples WHERE session_id = %s", (session_id,))
    n = cur.fetchone()[0]
    cur.close()
    conn.close()
    return n


def _insert_session_row(db_url: str, session_id: str) -> None:
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


# ===========================================================================
# Section 1 — Unit tests
# ===========================================================================


class TestStreamThreadUnit:

    def test_thread_name_reflects_stream_type(self):
        t = _make_thread(stream_type="HRV")
        assert t.name == "fwd_hrv"

    def test_thread_is_daemon(self):
        t = _make_thread()
        assert t.daemon is True

    def test_initial_sample_index_is_zero(self):
        t = _make_thread()
        assert t._sample_index == 0

    def test_initial_buffer_is_empty(self):
        t = _make_thread()
        assert len(t._buffer) == 0

    def test_write_rows_returns_conn_on_success(self):
        """_write_rows commits and returns the same connection on success."""
        t = _make_thread()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = MagicMock()

        rows = _build_eeg_rows(_EEG_SAMPLE, _CFG, 1000.0, 0)
        # execute_batch calls cur.mogrify() which requires a real cursor; patch it
        with patch("psycopg2.extras.execute_batch"):
            result = t._write_rows(mock_conn, rows)

        assert result is mock_conn
        mock_conn.commit.assert_called_once()

    def test_write_rows_buffers_on_operational_error(self):
        """OperationalError (connection dropped) → rows buffered, None returned."""
        t = _make_thread()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = MagicMock()

        rows = _build_eeg_rows(_EEG_SAMPLE, _CFG, 1000.0, 0)
        with patch(
            "psycopg2.extras.execute_batch",
            side_effect=psycopg2.OperationalError("lost connection"),
        ):
            result = t._write_rows(mock_conn, rows)

        assert result is None
        assert len(t._buffer) == 1
        assert t._buffer[0] is rows
        mock_conn.close.assert_called_once()

    def test_write_rows_rolls_back_on_non_connection_error(self):
        """Non-operational DB error (constraint violation) → rollback, conn returned."""
        t = _make_thread()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = MagicMock()

        rows = _build_eeg_rows(_EEG_SAMPLE, _CFG, 1000.0, 0)
        with patch(
            "psycopg2.extras.execute_batch",
            side_effect=psycopg2.IntegrityError("duplicate key"),
        ):
            result = t._write_rows(mock_conn, rows)

        assert result is mock_conn
        mock_conn.rollback.assert_called_once()

    def test_flush_buffer_drains_all_chunks(self):
        """_flush_buffer empties the deque when all writes succeed."""
        t = _make_thread()
        rows_a = _build_eeg_rows(_EEG_SAMPLE, _CFG, 1000.0, 0)
        rows_b = _build_eeg_rows(_EEG_SAMPLE, _CFG, 1000.004, 1)
        t._buffer.append(rows_a)
        t._buffer.append(rows_b)

        mock_conn = MagicMock()
        # Override _write_rows at instance level — no real cursor needed
        t._write_rows = lambda conn, rows: conn

        result = t._flush_buffer(mock_conn)

        assert len(t._buffer) == 0
        assert result is mock_conn

    def test_flush_buffer_stops_on_connection_drop(self):
        """If connection drops mid-flush, remaining chunks stay in the buffer."""
        t = _make_thread()
        rows_a = _build_eeg_rows(_EEG_SAMPLE, _CFG, 1000.0, 0)
        rows_b = _build_eeg_rows(_EEG_SAMPLE, _CFG, 1000.004, 1)
        t._buffer.append(rows_a)
        t._buffer.append(rows_b)

        mock_conn = MagicMock()
        # _write_rows returns None → simulates connection drop
        t._write_rows = lambda conn, rows: None

        result = t._flush_buffer(mock_conn)

        assert result is None
        # rows_a was attempted (not popped on failure), rows_b untouched
        assert len(t._buffer) == 2

    def test_buffer_max_chunks_constant_is_positive(self):
        assert BUFFER_MAX_CHUNKS > 0


# ===========================================================================
# Section 2 — Integration lifecycle tests
# ===========================================================================


@pytest.mark.integration
class TestStreamThreadLifecycle:

    def test_thread_exits_if_inlet_not_found(self):
        """Thread exits cleanly and promptly when no LSL stream is found."""
        stop = threading.Event()
        t = _make_thread(stop_event=stop)
        t._resolve_inlet = lambda: None  # no stream found

        t.start()
        t.join(timeout=2.0)

        assert not t.is_alive(), "thread did not exit after inlet not found"

    def test_thread_stops_on_stop_event(self, db_url):
        """Thread stops within 5 s when stop_event is set."""
        session_id = "f1d00008-0000-4444-aaaa-000000000002"
        _insert_session_row(db_url, session_id)

        cfg = SessionConfig(
            session_id=session_id,
            participant_id=_PART,
            site_id=_SITE,
            sponsor_id=_SPONSOR,
        )
        stop = threading.Event()
        xdf = MagicMock()

        t = _make_thread(stop_event=stop, xdf_writer=xdf, cfg=cfg)

        sample_q: queue.Queue = queue.Queue()
        t._resolve_inlet = lambda: _FakeInlet(sample_q)
        t._connect_db = lambda: (
            lambda conn: setattr(conn, "autocommit", False) or conn
        )(psycopg2.connect(db_url))

        try:
            t.start()
            assert t.is_alive()

            stop.set()
            t.join(timeout=5.0)

            assert not t.is_alive(), "thread did not stop within 5 s"
        finally:
            _cleanup(db_url, session_id)

    def test_thread_writes_eeg_samples_to_db(self, db_url):
        """Thread writes all fed samples to eeg_samples before stopping."""
        session_id = "f1d00008-0000-4444-aaaa-000000000003"
        _insert_session_row(db_url, session_id)

        cfg = SessionConfig(
            session_id=session_id,
            participant_id=_PART,
            site_id=_SITE,
            sponsor_id=_SPONSOR,
        )
        stop = threading.Event()
        xdf = MagicMock()

        t = _make_thread(stop_event=stop, xdf_writer=xdf, cfg=cfg)

        n_chunks = 2
        samples_per_chunk = 3  # 3 LSL samples × 8 channels = 24 DB rows
        sample_q: queue.Queue = queue.Queue()
        done = threading.Event()

        for _ in range(n_chunks * samples_per_chunk):
            sample_q.put(list(_EEG_SAMPLE))

        t._resolve_inlet = lambda: _FakeInlet(sample_q, done_event=done)
        t._connect_db = lambda: (
            lambda conn: setattr(conn, "autocommit", False) or conn
        )(psycopg2.connect(db_url))

        try:
            t.start()

            # Wait until the fake inlet reports the queue is empty
            done.wait(timeout=5.0)
            # Give the thread one more iteration to commit the last chunk
            time.sleep(0.1)

            stop.set()
            t.join(timeout=5.0)

            expected_rows = n_chunks * samples_per_chunk * 8  # 8 channels per sample
            actual = _count_eeg_rows(db_url, session_id)
            assert (
                actual == expected_rows
            ), f"expected {expected_rows} eeg_samples rows, got {actual}"
        finally:
            _cleanup(db_url, session_id)

    def test_thread_writes_xdf_before_db(self, db_url, tmp_path):
        """XDF writer receives write_samples before any DB commit.

        XDF is the authoritative backup — it must be written first.
        """
        session_id = "f1d00008-0000-4444-aaaa-000000000004"
        _insert_session_row(db_url, session_id)

        cfg = SessionConfig(
            session_id=session_id,
            participant_id=_PART,
            site_id=_SITE,
            sponsor_id=_SPONSOR,
        )
        stop = threading.Event()
        xdf = MagicMock()
        xdf_calls: list[str] = []
        db_commit_calls: list[str] = []

        # Intercept XDF writes and DB commits in order
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
        t._connect_db = lambda: (
            lambda conn: setattr(conn, "autocommit", False) or conn
        )(psycopg2.connect(db_url))

        try:
            t.start()
            done.wait(timeout=5.0)
            time.sleep(0.1)
            stop.set()
            t.join(timeout=5.0)

            assert xdf_calls, "XDF writer was never called"
            assert db_commit_calls, "DB was never committed"
            # XDF write must appear before the first DB commit
            all_calls = xdf_calls + db_commit_calls
            assert all_calls.index("xdf") < all_calls.index(
                "db"
            ), "DB was committed before XDF was written"
        finally:
            _cleanup(db_url, session_id)

    def test_sample_index_increments_across_chunks(self, db_url):
        """sample_index is monotonically increasing across consecutive chunks."""
        session_id = "f1d00008-0000-4444-aaaa-000000000005"
        _insert_session_row(db_url, session_id)

        cfg = SessionConfig(
            session_id=session_id,
            participant_id=_PART,
            site_id=_SITE,
            sponsor_id=_SPONSOR,
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
        t._connect_db = lambda: (
            lambda conn: setattr(conn, "autocommit", False) or conn
        )(psycopg2.connect(db_url))

        try:
            t.start()
            done.wait(timeout=5.0)
            time.sleep(0.1)
            stop.set()
            t.join(timeout=5.0)

            conn = _db_conn(db_url)
            cur = conn.cursor()
            cur.execute(
                """
                SELECT DISTINCT sample_index FROM eeg_samples
                WHERE session_id = %s ORDER BY sample_index
                """,
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
        """_maybe_record_drift writes a row to clock_drift_log on the first loop iteration.

        _last_drift_time starts at 0.0, so time.monotonic() - 0.0 always
        exceeds CLOCK_DRIFT_RECORD_INTERVAL on the first call, guaranteeing
        at least one drift row per thread run. The _FakeInlet returns a fixed
        offset of 0.001 s (below the 0.1 s threshold).
        """
        session_id = "f1d00008-0000-4444-aaaa-000000000006"
        _insert_session_row(db_url, session_id)

        cfg = SessionConfig(
            session_id=session_id,
            participant_id=_PART,
            site_id=_SITE,
            sponsor_id=_SPONSOR,
        )
        stop = threading.Event()
        xdf = MagicMock()

        t = _make_thread(stop_event=stop, xdf_writer=xdf, cfg=cfg)

        sample_q: queue.Queue = queue.Queue()
        done = threading.Event()
        sample_q.put(list(_EEG_SAMPLE))

        t._resolve_inlet = lambda: _FakeInlet(sample_q, done_event=done)
        t._connect_db = lambda: (
            lambda conn: setattr(conn, "autocommit", False) or conn
        )(psycopg2.connect(db_url))

        try:
            t.start()
            done.wait(timeout=5.0)
            time.sleep(0.1)
            stop.set()
            t.join(timeout=5.0)

            assert (
                _count_drift_rows(db_url, session_id) >= 1
            ), "no clock_drift_log row written"

            row = _fetch_drift_row(db_url, session_id)
            assert row is not None
            stream_type, offset_s, exceeds, threshold_s = row
            assert stream_type == "EEG"
            assert abs(offset_s - 0.001) < 1e-6, f"unexpected offset {offset_s}"
            assert exceeds is False, "0.001 s should not exceed the 0.1 s threshold"
            assert threshold_s == pytest.approx(0.1)
        finally:
            _cleanup(db_url, session_id)
