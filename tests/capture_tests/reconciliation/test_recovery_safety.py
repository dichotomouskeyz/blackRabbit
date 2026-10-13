"""Approved reconciliation release contract, R-014/R-018/R-020/R-023..029.

Real XDF recordings exercise provenance and replay; only PostgreSQL is replaced
with a small persistence seam so these safety checks run without an integration DB.
"""

import sys
from dataclasses import replace
from unittest.mock import MagicMock

import pytest

from batch import reconcile
from batch.reconciliation import backfill as bf
from batch.reconciliation import db as rdb
from batch.reconciliation.models import SessionMeta, XDFReadError
from capture.session_lock import SessionBusyError
from capture.xdf.constants import CHANNEL_COUNTS
from capture.xdf.writer import XDFWriter
from tests.capture_tests.reconciliation.support import (
    DEVICE_ID,
    PARTICIPANT_ID,
    SESSION_ID,
    SITE_ID,
    SPONSOR_ID,
)

NAMES = tuple(f"electrode_{index}" for index in range(CHANNEL_COUNTS["EEG"]))
META = SessionMeta(PARTICIPANT_ID, SITE_ID, SPONSOR_ID, NAMES, {"EEG": DEVICE_ID}, "closing")


@pytest.fixture
def recording(tmp_path, monkeypatch):
    from capture.xdf import writer as writer_module

    monkeypatch.setattr(writer_module.settings, "XDF_BACKUP_DIR", str(tmp_path))

    def create(*, session_id=SESSION_ID, eeg=True, markers=()):
        writer = XDFWriter(
            session_id,
            PARTICIPANT_ID,
            SITE_ID,
            SPONSOR_ID,
            eeg_channel_names=NAMES,
            device_id=DEVICE_ID,
        )
        if eeg:
            writer.write_samples("EEG", [[float(i) for i in range(len(NAMES))]], [1000.0])
        for marker in markers:
            writer.write_marker(marker, 1001.0)
        writer.close()
        return writer.path

    return create


@pytest.fixture
def database(monkeypatch):
    conn = MagicMock()
    monkeypatch.setattr(bf, "fetch_session_meta", lambda *args, **kwargs: META)
    monkeypatch.setattr(bf, "acquire_session_lock", lambda *args: None)
    return conn


@pytest.mark.parametrize(
    "helper,args",
    [
        (rdb.fetch_session_meta, (SESSION_ID,)),
        (rdb.query_db_counts, (SESSION_ID,)),
        (rdb.query_max_clock_drift_s, (SESSION_ID,)),
        (rdb.fetch_existing_sample_indices, (SESSION_ID, "eeg_samples")),
        (rdb.fetch_existing_eeg_keys, (SESSION_ID,)),
        (rdb.fetch_existing_echo_keys, (SESSION_ID,)),
        (rdb.fetch_existing_echo_timestamps, (SESSION_ID,)),
        (rdb.close_session, (SESSION_ID,)),
    ],
)
def test_scope_is_required_before_sql(helper, args):
    conn = MagicMock()
    with pytest.raises(ValueError, match="sponsor_id"):
        helper(conn, *args)
    conn.cursor.assert_not_called()


def test_close_refuses_wrong_scope_without_commit():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.rowcount = 0
    with pytest.raises(ValueError, match="close refused"):
        rdb.close_session(conn, SESSION_ID, SPONSOR_ID, is_reconciled=True, site_id=SITE_ID)
    assert cur.execute.call_args.args[1] == ("closed", SESSION_ID, SPONSOR_ID, SITE_ID, SITE_ID)
    conn.rollback.assert_called_once()
    conn.commit.assert_not_called()


def test_wrong_sponsor_cannot_load_metadata():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchone.return_value = None
    with pytest.raises(ValueError, match="not found"):
        rdb.fetch_session_meta(conn, SESSION_ID, SPONSOR_ID, site_id=SITE_ID)
    assert cur.execute.call_args.args[1] == (SESSION_ID, SPONSOR_ID, SITE_ID, SITE_ID)
    assert cur.execute.call_count == 1


def test_log_rejects_forged_participant_before_insert(monkeypatch):
    conn = MagicMock()
    monkeypatch.setattr(rdb, "fetch_session_meta", lambda *args, **kwargs: META)
    report = rdb.build_report(SESSION_ID, "session.xdf", {}, {})
    with pytest.raises(ValueError, match="participant_id"):
        rdb.write_reconciliation_log(
            conn, report, replace(META, participant_id=SESSION_ID), sponsor_id=SPONSOR_ID
        )
    conn.cursor.assert_not_called()


def test_partial_eeg_frame_recovery_preserves_names_and_is_idempotent(
    recording, database, monkeypatch
):
    path = recording()
    existing = {(0, NAMES[0])}
    inserted = []
    monkeypatch.setattr(bf, "fetch_existing_sample_indices", lambda *a, **k: frozenset({0}))
    monkeypatch.setattr(bf, "fetch_existing_eeg_keys", lambda *a, **k: frozenset(existing))

    def persist(cursor, sql, rows):
        inserted.extend(rows)
        existing.update((row["sample_index"], row["channel_id"]) for row in rows)

    monkeypatch.setattr(bf.psycopg2.extras, "execute_batch", persist)
    first = bf.backfill_stream(
        database, "EEG", SESSION_ID, path, META, chunk_size=2, sponsor_id=SPONSOR_ID
    )
    second = bf.backfill_stream(
        database, "EEG", SESSION_ID, path, META, chunk_size=2, sponsor_id=SPONSOR_ID
    )
    assert first == len(NAMES) - 1
    assert second == 0
    assert [row["channel_id"] for row in inserted] == list(NAMES[1:])
    assert {row["device_id"] for row in inserted} == {DEVICE_ID}
    assert {row["lsl_timestamp"] for row in inserted} == {1000.0}


def test_duplicate_pending_echo_keys_are_replayed_once(recording, database, monkeypatch):
    marker = "ECHO|manual_marker|actor1|therapist|dose_administration"
    path = recording(eeg=False, markers=(marker, marker))
    existing = set()
    inserted = []
    monkeypatch.setattr(bf, "fetch_existing_echo_keys", lambda *a, **k: frozenset(existing))

    def persist(cursor, sql, rows):
        inserted.extend(rows)
        existing.update(
            (
                float(row["lsl_timestamp"]),
                str(row["event_type"]),
                str(row["actor_id"]),
                str(row["actor_role"]),
                str(row["zone_label"]),
            )
            for row in rows
        )

    monkeypatch.setattr(bf.psycopg2.extras, "execute_batch", persist)
    assert bf.backfill_echo_markers(database, SESSION_ID, path, META, sponsor_id=SPONSOR_ID) == 1
    assert bf.backfill_echo_markers(database, SESSION_ID, path, META, sponsor_id=SPONSOR_ID) == 0
    assert len(inserted) == 1


def test_xdf_from_another_session_is_rejected_before_insert(recording, database, monkeypatch):
    path = recording(session_id=PARTICIPANT_ID)
    persist = MagicMock()
    monkeypatch.setattr(bf.psycopg2.extras, "execute_batch", persist)
    with pytest.raises(XDFReadError, match="session_id"):
        bf.backfill_stream(database, "EEG", SESSION_ID, path, META, sponsor_id=SPONSOR_ID)
    persist.assert_not_called()


def test_channel_provenance_conflict_is_rejected(recording, database, monkeypatch):
    path = recording()
    conflicting = replace(META, eeg_channel_names=tuple(reversed(NAMES)))
    monkeypatch.setattr(bf, "fetch_session_meta", lambda *args, **kwargs: conflicting)
    with pytest.raises(XDFReadError, match="channels differ"):
        bf.backfill_stream(database, "EEG", SESSION_ID, path, META, sponsor_id=SPONSOR_ID)


def test_header_channel_names_recover_missing_session_names(recording, database, monkeypatch):
    path = recording()
    monkeypatch.setattr(
        bf, "fetch_session_meta", lambda *args, **kwargs: replace(META, eeg_channel_names=None)
    )
    canonical = bf._validate_replay(database, SESSION_ID, path, META, SPONSOR_ID, SITE_ID, 2, False)
    assert canonical.eeg_channel_names == NAMES


def test_forged_caller_meta_is_rejected_before_reading_xdf(database):
    with pytest.raises(ValueError, match="site_id"):
        bf.backfill_stream(
            database,
            "EEG",
            SESSION_ID,
            "not-read.xdf",
            replace(META, site_id=SESSION_ID),
            sponsor_id=SPONSOR_ID,
        )


def test_busy_session_is_rejected_before_metadata_or_replay(database, monkeypatch):
    metadata = MagicMock()
    monkeypatch.setattr(bf, "fetch_session_meta", metadata)

    def busy(*args):
        raise SessionBusyError("busy")

    monkeypatch.setattr(bf, "acquire_session_lock", busy)
    with pytest.raises(SessionBusyError):
        bf.backfill_stream(database, "EEG", SESSION_ID, "not-read.xdf", META, sponsor_id=SPONSOR_ID)
    metadata.assert_not_called()


@pytest.mark.parametrize("chunk_size", [0, -1, True])
def test_invalid_chunk_size_is_rejected_before_lock(database, monkeypatch, chunk_size):
    lock = MagicMock()
    monkeypatch.setattr(bf, "acquire_session_lock", lock)
    with pytest.raises(ValueError, match="chunk_size"):
        bf.backfill_stream(
            database,
            "EEG",
            SESSION_ID,
            "not-read.xdf",
            META,
            chunk_size=chunk_size,
            sponsor_id=SPONSOR_ID,
        )
    lock.assert_not_called()


def test_eeg_row_builder_rejects_channel_width_mismatch():
    with pytest.raises(ValueError, match="width"):
        bf._build_backfill_rows("EEG", META, 0, 1.0, [1.0], SESSION_ID)


def test_cli_requires_sponsor_and_parses_optional_site_legacy(monkeypatch):
    argv = ["reconcile", "--session-id", SESSION_ID, "--xdf-path", "session.xdf"]
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as error:
        reconcile._parse_args()
    assert error.value.code == 2
    monkeypatch.setattr(
        sys, "argv", [*argv, "--sponsor-id", SPONSOR_ID, "--site-id", SITE_ID, "--legacy-xdf"]
    )
    parsed = reconcile._parse_args()
    assert parsed.sponsor_id == SPONSOR_ID
    assert parsed.site_id == SITE_ID
    assert parsed.legacy_xdf is True
