"""Database helpers for forwarder stream threads."""

import psycopg2
import psycopg2.extras

from capture.logger import get_logger
from config import settings

log = get_logger("lsl_forwarder")


def _open_connection():
    conn = psycopg2.connect(settings.DATABASE_URL)
    conn.autocommit = False
    return conn


def connect_db(thread) -> psycopg2.extensions.connection | None:
    backoff = 1.0
    while not thread._stop_event.is_set():
        try:
            conn = _open_connection()
            log.info(f"{thread._stream_type} DB connection established")
            return conn
        except psycopg2.OperationalError as exc:
            log.warning(
                f"{thread._stream_type} DB connection failed - retrying",
                extra={"retry_in_s": backoff, "error": str(exc)},
            )
            thread._stop_event.wait(backoff)
            backoff = min(backoff * 2, 30.0)
    return None


def try_reconnect(thread) -> psycopg2.extensions.connection | None:
    try:
        conn = _open_connection()
        log.info(
            f"{thread._stream_type} DB reconnected",
            extra={"buffered_chunks": len(thread.buffer)},
        )
        return conn
    except psycopg2.OperationalError:
        return None


def write_rows(thread, conn: psycopg2.extensions.connection, rows: list[dict]):
    try:
        cur = conn.cursor()
        psycopg2.extras.execute_batch(cur, thread._insert_sql, rows)
        conn.commit()
        cur.close()
        return conn
    except psycopg2.OperationalError as exc:
        log.error(
            f"{thread._stream_type} DB write failed - connection dropped",
            extra={"error": str(exc), "rows_lost_to_buffer": len(rows)},
        )
        close_after_write_error(thread, conn)
        thread.buffer.append(rows)
        return None
    except psycopg2.Error as exc:
        log.error(
            f"{thread._stream_type} DB insert error - chunk permanently dropped",
            extra={"error": str(exc), "rows_dropped": len(rows)},
        )
        rollback_quietly(conn)
        return conn


def close_after_write_error(thread, conn) -> None:
    try:
        conn.close()
    except Exception as close_exc:
        log.debug(
            f"{thread._stream_type} DB close failed after write error",
            extra={"error": str(close_exc)},
        )


def rollback_quietly(conn) -> None:
    try:
        conn.rollback()
    except Exception:
        pass


def flush_buffer(thread, conn: psycopg2.extensions.connection):
    flushed = 0
    while thread.buffer and conn is not None:
        rows = thread.buffer[0]
        conn = thread.write_rows(conn, rows)
        if conn is not None:
            thread.buffer.popleft()
            flushed += 1
    if flushed:
        log.info(
            f"{thread._stream_type} buffer flushed",
            extra={
                "chunks_flushed": flushed,
                "chunks_remaining": len(thread.buffer),
            },
        )
    return conn
