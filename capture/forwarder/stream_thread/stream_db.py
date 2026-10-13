"""Database helpers for forwarder stream threads.

All helpers operate on the thread's own state: ``thread.conn`` holds the DB
connection (None while the DB is down) and ``thread.buffer`` holds chunks
awaiting replay. On psycopg2.OperationalError the rows are buffered and
``thread.conn`` is set to None; on any other psycopg2.Error the chunk is
rolled back, logged at ERROR, and dropped — the deliberate design for
constraint violations (forwarder spec, accepted risk). XDF remains the
recovery source for dropped chunks at session close.
"""

import psycopg2

from capture.forwarder.models import BUFFER_MAX_CHUNKS
from capture.forwarder.sql import EDA_INSERT, EEG_INSERT, HRV_INSERT, RESPIRATION_INSERT
from capture.forwarder.stream_thread.stream_integrity import write_integrity_log
from capture.logger import get_logger
from config import settings

log = get_logger("lsl_forwarder")

__all__ = ["BUFFER_MAX_CHUNKS", "connect_db", "flush_buffer", "try_reconnect", "write_rows"]

# Closed internal mapping — insert SQL is never derived from input.
_INSERT_SQL_BY_STREAM_TYPE = {
    "EEG": EEG_INSERT,
    "HRV": HRV_INSERT,
    "EDA": EDA_INSERT,
    "Respiration": RESPIRATION_INSERT,
}


def _open_connection():
    conn = psycopg2.connect(settings.DATABASE_URL)
    conn.autocommit = False
    return conn


def _insert_sql_for(thread) -> str:
    sql_stmt = getattr(thread, "insert_sql", None)
    return sql_stmt if sql_stmt is not None else _INSERT_SQL_BY_STREAM_TYPE[thread.stream_type]


def connect_db(thread) -> psycopg2.extensions.connection | None:
    """Establish thread.conn with exponential backoff until stop is requested."""
    backoff = 1.0
    while not thread.stop_event.is_set():
        try:
            thread.conn = _open_connection()
            log.info(f"{thread.stream_type} DB connection established")
            return thread.conn
        except psycopg2.OperationalError as exc:
            log.warning(
                f"{thread.stream_type} DB connection failed - retrying",
                extra={"retry_in_s": backoff, "error": str(exc)},
            )
            thread.stop_event.wait(backoff)
            backoff = min(backoff * 2, 30.0)
    return None


def try_reconnect(thread) -> psycopg2.extensions.connection | None:
    try:
        thread.conn = _open_connection()
        log.info(
            f"{thread.stream_type} DB reconnected",
            extra={"buffered_chunks": len(thread.buffer)},
        )
        return thread.conn
    except psycopg2.OperationalError:
        thread.conn = None
        return None


def write_rows(
    thread,
    rows: list[dict],
    buffer_on_failure: bool = True,
) -> psycopg2.extensions.connection | None:
    """Write one chunk + its integrity row in a single transaction via thread.conn.

    OperationalError → rows buffered (unless buffer_on_failure=False, used by
    flush_buffer which already holds the rows in the buffer), conn closed and
    thread.conn set to None. Other psycopg2.Error → rollback, log, drop chunk,
    keep the connection.
    """
    conn = thread.conn
    if conn is None:
        if buffer_on_failure:
            thread.buffer.append(rows)
        return None

    try:
        cur = conn.cursor()
        try:
            insert_sql = _insert_sql_for(thread)
            for row in rows:
                cur.execute(insert_sql, row)
            write_integrity_log(thread, cur, rows)
            conn.commit()
        finally:
            cur.close()
        return conn
    except psycopg2.OperationalError as exc:
        log.error(
            f"{thread.stream_type} DB write failed - connection dropped",
            extra={"error": str(exc), "rows_lost_to_buffer": len(rows)},
        )
        rollback_quietly(conn)
        close_after_write_error(thread, conn)
        thread.conn = None
        if buffer_on_failure:
            thread.buffer.append(rows)
        return None
    except psycopg2.Error as exc:
        log.error(
            f"{thread.stream_type} DB chunk write failed - chunk dropped, "
            "XDF retains it for reconciliation",
            extra={"error": str(exc), "rows_dropped": len(rows)},
        )
        rollback_quietly(conn)
        return conn


def close_after_write_error(thread, conn) -> None:
    try:
        conn.close()
    except Exception as close_exc:
        log.debug(
            f"{thread.stream_type} DB close failed after write error",
            extra={"error": str(close_exc)},
        )


def rollback_quietly(conn) -> None:
    try:
        conn.rollback()
    except Exception:
        pass


def flush_buffer(thread) -> psycopg2.extensions.connection | None:
    """Replay buffered chunks FIFO via thread.conn; remove only after success."""
    flushed = 0
    while thread.buffer and thread.conn is not None:
        rows = thread.buffer[0]
        if write_rows(thread, rows, buffer_on_failure=False) is None:
            break
        thread.buffer.popleft()
        flushed += 1
    if flushed:
        log.info(
            f"{thread.stream_type} buffer flushed",
            extra={
                "chunks_flushed": flushed,
                "chunks_remaining": len(thread.buffer),
            },
        )
    return thread.conn
