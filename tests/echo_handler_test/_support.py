"""Shared fixtures and helpers for echo handler tests."""

from __future__ import annotations

import os
import threading
import time
from unittest.mock import MagicMock

import psycopg2
from dotenv import load_dotenv

from capture.echo_handler import ECHOThread
from capture.xdf_writer import XDFWriter

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

_SID_INSERT = "e0eebc99-9c0b-4ef8-bb6d-6bb9bd380a01"
_SID_AUDIT = "e0eebc99-9c0b-4ef8-bb6d-6bb9bd380a02"
_SID_STATES = "e0eebc99-9c0b-4ef8-bb6d-6bb9bd380a03"

_LIVE_SITE = "f1d00003-0000-4444-cccc-000000000001"
_LIVE_SPONSOR = "f1d00003-0000-4444-dddd-000000000001"
_LIVE_PART = "f1d00003-0000-4444-bbbb-000000000001"


def db_conn():
    url = os.getenv("TEST_DATABASE_URL", "")
    url = url.replace("postgresql://", "")
    user_pass, rest = url.split("@")
    user, password = user_pass.split(":")
    host_port, dbname = rest.split("/")
    host, port = host_port.split(":")
    return psycopg2.connect(
        host=host, port=int(port), dbname=dbname, user=user, password=password
    )


def database_url() -> str:
    url = os.getenv("TEST_DATABASE_URL", "")
    if not url:
        raise RuntimeError("TEST_DATABASE_URL is required for echo handler tests")
    return url


def insert_echo_event(session_id: str, zone_label: str, lsl_ts: float) -> None:
    cfg = MagicMock()
    cfg.session_id = session_id
    cfg.participant_id = "aaaa0002-0000-0000-0000-000000000001"
    cfg.site_id = "bbbb0000-0000-0000-0000-000000000001"
    cfg.sponsor_id = "cccc0000-0000-0000-0000-000000000001"

    thread = ECHOThread(cfg=cfg, stop_event=MagicMock(), xdf_writer=MagicMock())
    conn = psycopg2.connect(os.getenv("TEST_DATABASE_URL"))
    conn.autocommit = False
    try:
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
    finally:
        conn.close()


def build_thread(session_id: str, xdf_writer, marker_queue):
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
        time.sleep(min(timeout, 0.05))
        return None, 0.0

    mock_inlet = MagicMock()
    mock_inlet.pull_sample.side_effect = pull_sample

    stop = threading.Event()
    thread = ECHOThread(cfg=cfg, stop_event=stop, xdf_writer=xdf_writer)
    thread._resolve_inlet = MagicMock(return_value=mock_inlet)

    def _test_connect_db():
        conn = psycopg2.connect(db_url)
        conn.autocommit = False
        return conn

    thread._connect_db = _test_connect_db
    return thread, stop


def poll_for_rows(session_id: str, expected_n: int, timeout_s: float = 5.0) -> bool:
    db_url = os.getenv("TEST_DATABASE_URL")
    conn = psycopg2.connect(db_url)
    conn.autocommit = True
    deadline = time.monotonic() + timeout_s
    try:
        while time.monotonic() < deadline:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM echo_events WHERE session_id = %s",
                    (session_id,),
                )
                if cur.fetchone()[0] >= expected_n:
                    return True
            time.sleep(0.05)
        return False
    finally:
        conn.close()


def cleanup_echo_events(session_id: str) -> None:
    db_url = os.getenv("TEST_DATABASE_URL")
    conn = psycopg2.connect(db_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM echo_events WHERE session_id = %s", (session_id,))
    finally:
        conn.close()


def make_xdf(session_id: str, monkeypatch, tmp_path) -> XDFWriter:
    import config.settings as s

    monkeypatch.setattr(s, "XDF_BACKUP_DIR", tmp_path)
    return XDFWriter(session_id, _LIVE_SITE, _LIVE_SPONSOR)
