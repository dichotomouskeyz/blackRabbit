"""Database helpers for ECHO marker writes."""

import time

import psycopg2

from capture.echo_handler.sql import ECHO_INSERT
from capture.logger import get_logger
from config import settings

log = get_logger("echo_handler")

DB_BACKOFF_INITIAL_S = 1.0
DB_BACKOFF_MAX_S = 30.0
WRITE_MAX_RETRIES = 3
WRITE_RETRY_DELAY_S = 0.5


def close_quietly(conn) -> None:
    try:
        conn.close()
    except Exception as close_exc:
        log.debug(
            "ECHO DB close failed after write error",
            extra={"error": str(close_exc)},
        )


def rollback_quietly(conn) -> None:
    try:
        conn.rollback()
    except Exception as rb_exc:
        log.debug(
            "ECHO DB rollback failed",
            extra={"error": str(rb_exc)},
        )


def connect_db(stop_event):
    backoff = DB_BACKOFF_INITIAL_S
    while not stop_event.is_set():
        try:
            conn = psycopg2.connect(settings.DATABASE_URL)
            conn.autocommit = False
            log.info("ECHO DB connection established")
            return conn
        except psycopg2.OperationalError as exc:
            log.warning(
                "ECHO DB connection failed — retrying",
                extra={"retry_in_s": backoff, "error": str(exc)},
            )
            stop_event.wait(backoff)
            backoff = min(backoff * 2, DB_BACKOFF_MAX_S)
    return None


def try_reconnect(buffer_depth: int):
    try:
        conn = psycopg2.connect(settings.DATABASE_URL)
        conn.autocommit = False
        log.info(
            "ECHO DB reconnected",
            extra={"buffered_events": buffer_depth},
        )
        return conn
    except psycopg2.OperationalError:
        return None


def write_row(conn, row: dict):
    for attempt in range(1, WRITE_MAX_RETRIES + 1):
        try:
            with conn.cursor() as cur:
                cur.execute(ECHO_INSERT, row)
            conn.commit()
            log.info(
                "ECHO event persisted",
                extra={
                    "session_id": row.get("session_id"),
                    "participant_id": row.get("participant_id"),
                    "site_id": row.get("site_id"),
                    "sponsor_id": row.get("sponsor_id"),
                    "event_type": row.get("event_type"),
                    "source": "manual_logging",
                    "actor_id": row.get("actor_id"),
                    "actor_role": row.get("actor_role"),
                    "zone_label": row.get("zone_label"),
                    "lsl_timestamp": row.get("lsl_timestamp"),
                    "ingestion_path": "live_db",
                },
            )
            return conn, True
        except psycopg2.OperationalError as exc:
            # Connection is dead — no point retrying.
            log.error(
                "ECHO DB write failed — connection dropped",
                extra={"error": str(exc)},
            )
            close_quietly(conn)
            return None, False
        except psycopg2.Error as exc:
            rollback_quietly(conn)
            if attempt < WRITE_MAX_RETRIES:
                log.warning(
                    "ECHO DB write error — retrying",
                    extra={"attempt": attempt, "max": WRITE_MAX_RETRIES, "error": str(exc)},
                )
                time.sleep(WRITE_RETRY_DELAY_S)
            else:
                log.error(
                    "ECHO DB write failed after retries — dropping connection",
                    extra={
                        "attempts": WRITE_MAX_RETRIES,
                        "error": str(exc),
                        "session_id": row.get("session_id"),
                        "event_type": row.get("event_type"),
                        "lsl_timestamp": row.get("lsl_timestamp"),
                        "ingestion_path": "live_db",
                    },
                )
                close_quietly(conn)
                return None, False
    return None, False
