"""Tests for batch/reconcile.py.

XDF-reading tests use XDFWriter to produce real XDF files with known
sample counts, then verify the parser recovers those counts exactly.
DB-facing tests are integration tests that require TEST_DATABASE_URL.
"""

from pathlib import Path

import pytest

from batch.reconcile import (
    BACKFILL_CHUNK_SIZE_ROWS,
    SessionMeta,
    XDFReadError,
    XDFTruncatedError,
    _XDF_MAGIC,
    _build_backfill_rows,
    build_report,
    query_db_counts,
    read_xdf_counts,
    run_backfill,
    stream_xdf_samples,
)
from capture.xdf_writer import XDFWriter

# ---------------------------------------------------------------------------
# Shared test constants
# ---------------------------------------------------------------------------

SESSION_ID = "ccccdddd-0000-0000-0000-000000000001"
SITE_ID = "SITE-REC-01"
SPONSOR_ID = "SPONSOR-REC-01"

_ALL_STREAMS = ("EEG", "HRV", "EDA", "Respiration")


# ---------------------------------------------------------------------------
# XDFWriter fixture — creates a real XDF file with known sample counts
# ---------------------------------------------------------------------------


@pytest.fixture()
def xdf_file(tmp_path, monkeypatch):
    """Returns (path, expected_counts) for a fully written XDF file."""
    import config.settings as s

    monkeypatch.setattr(s, "XDF_BACKUP_DIR", tmp_path)

    w = XDFWriter(SESSION_ID, SITE_ID, SPONSOR_ID)

    # Write known sample counts per stream
    w.write_samples("EEG", [[float(i)] * 8 for i in range(50)], list(range(50)))
    w.write_samples("HRV", [[800.0 + i] for i in range(10)], list(range(10)))
    w.write_samples("EDA", [[5.0 + i * 0.1] for i in range(20)], list(range(20)))
    w.write_samples(
        "Respiration", [[0.5 + i * 0.01] for i in range(15)], list(range(15))
    )
    w.close()

    expected = {"EEG": 50, "HRV": 10, "EDA": 20, "Respiration": 15}
    return w.path, expected


@pytest.fixture()
def xdf_file_empty(tmp_path, monkeypatch):
    """Returns path to a closed XDF file with zero samples in all streams."""
    import config.settings as s

    monkeypatch.setattr(s, "XDF_BACKUP_DIR", tmp_path)
    w = XDFWriter(SESSION_ID, SITE_ID, SPONSOR_ID)
    w.close()
    return w.path


@pytest.fixture()
def xdf_file_truncated(tmp_path, monkeypatch):
    """Returns path to an XDF file where close() was never called (no footers)."""
    import config.settings as s

    monkeypatch.setattr(s, "XDF_BACKUP_DIR", tmp_path)
    w = XDFWriter(SESSION_ID, SITE_ID, SPONSOR_ID)
    w.write_samples("EEG", [[1.0] * 8], [1.0])
    # Intentionally do NOT call w.close() — simulates forwarder crash
    return w.path


# ---------------------------------------------------------------------------
# read_xdf_counts — happy path
# ---------------------------------------------------------------------------


class TestReadXDFCountsHappyPath:
    def test_returns_counts_for_all_streams(self, xdf_file):
        path, expected = xdf_file
        counts = read_xdf_counts(path)
        assert set(counts.keys()) == set(expected.keys())

    def test_eeg_count_correct(self, xdf_file):
        path, expected = xdf_file
        assert read_xdf_counts(path)["EEG"] == expected["EEG"]

    def test_hrv_count_correct(self, xdf_file):
        path, expected = xdf_file
        assert read_xdf_counts(path)["HRV"] == expected["HRV"]

    def test_eda_count_correct(self, xdf_file):
        path, expected = xdf_file
        assert read_xdf_counts(path)["EDA"] == expected["EDA"]

    def test_respiration_count_correct(self, xdf_file):
        path, expected = xdf_file
        assert read_xdf_counts(path)["Respiration"] == expected["Respiration"]

    def test_empty_file_returns_zero_counts(self, xdf_file_empty):
        counts = read_xdf_counts(xdf_file_empty)
        for name in _ALL_STREAMS:
            assert counts[name] == 0

    def test_multi_chunk_same_stream_accumulates(self, tmp_path, monkeypatch):
        import config.settings as s

        monkeypatch.setattr(s, "XDF_BACKUP_DIR", tmp_path)
        w = XDFWriter(SESSION_ID, SITE_ID, SPONSOR_ID)
        # Write EEG in 3 separate chunks
        w.write_samples("EEG", [[1.0] * 8] * 25, list(range(25)))
        w.write_samples("EEG", [[2.0] * 8] * 25, list(range(25, 50)))
        w.write_samples("EEG", [[3.0] * 8] * 10, list(range(50, 60)))
        w.close()
        counts = read_xdf_counts(w.path)
        # Footers contain the total written by XDFWriter, not per-chunk counts
        assert counts["EEG"] == 60


# ---------------------------------------------------------------------------
# read_xdf_counts — error cases
# ---------------------------------------------------------------------------


class TestReadXDFCountsErrors:
    def test_missing_file_raises_read_error(self, tmp_path):
        with pytest.raises(XDFReadError):
            read_xdf_counts(tmp_path / "nonexistent.xdf")

    def test_wrong_magic_raises_read_error(self, tmp_path):
        bad_file = tmp_path / "bad.xdf"
        bad_file.write_bytes(b"NOTXDF:garbage")
        with pytest.raises(XDFReadError, match="magic"):
            read_xdf_counts(bad_file)

    def test_truncated_file_raises_truncated_error(self, xdf_file_truncated):
        with pytest.raises(XDFTruncatedError):
            read_xdf_counts(xdf_file_truncated)

    def test_empty_file_raises_read_error(self, tmp_path):
        empty = tmp_path / "empty.xdf"
        empty.write_bytes(b"")
        with pytest.raises(XDFReadError):
            read_xdf_counts(empty)

    def test_just_magic_no_chunks_raises_truncated(self, tmp_path):
        f = tmp_path / "magic_only.xdf"
        f.write_bytes(_XDF_MAGIC)
        with pytest.raises(XDFTruncatedError):
            read_xdf_counts(f)


# ---------------------------------------------------------------------------
# build_report
# ---------------------------------------------------------------------------


class TestBuildReport:
    def _make_report(self, xdf_counts, db_counts, path=None):
        return build_report(
            session_id=SESSION_ID,
            xdf_path=path or Path("/fake/session.xdf"),
            xdf_counts=xdf_counts,
            db_counts=db_counts,
        )

    def test_reconciled_when_counts_match(self):
        counts = {"EEG": 100, "HRV": 10, "EDA": 20, "Respiration": 15}
        report = self._make_report(counts, counts)
        assert report.is_reconciled is True

    def test_not_reconciled_when_eeg_gap(self):
        xdf = {"EEG": 100, "HRV": 10, "EDA": 20, "Respiration": 15}
        db = {"EEG": 90, "HRV": 10, "EDA": 20, "Respiration": 15}
        report = self._make_report(xdf, db)
        assert report.is_reconciled is False

    def test_gap_is_xdf_minus_db(self):
        xdf = {"EEG": 100}
        db = {"EEG": 90}
        report = self._make_report(xdf, db)
        assert report.streams["EEG"].gap == 10

    def test_negative_gap_when_db_exceeds_xdf(self):
        xdf = {"HRV": 5}
        db = {"HRV": 8}
        report = self._make_report(xdf, db)
        assert report.streams["HRV"].gap == -3

    def test_zero_gap_when_both_zero(self):
        report = self._make_report(
            {"EEG": 0, "HRV": 0, "EDA": 0, "Respiration": 0},
            {"EEG": 0, "HRV": 0, "EDA": 0, "Respiration": 0},
        )
        assert report.is_reconciled is True

    def test_stream_present_in_xdf_not_db_flagged(self):
        xdf = {"EEG": 50}
        db = {}
        report = self._make_report(xdf, db)
        assert report.streams["EEG"].gap == 50
        assert report.is_reconciled is False

    def test_stream_present_in_db_not_xdf_flagged(self):
        xdf = {}
        db = {"HRV": 10}
        report = self._make_report(xdf, db)
        assert report.streams["HRV"].gap == -10
        assert report.is_reconciled is False

    def test_all_stream_tables_always_present_in_report(self):
        report = self._make_report({}, {})
        for name in ("EEG", "HRV", "EDA", "Respiration"):
            assert name in report.streams

    def test_as_dict_contains_required_keys(self):
        report = self._make_report({"EEG": 10}, {"EEG": 10})
        d = report.as_dict()
        assert "session_id" in d
        assert "is_reconciled" in d
        assert "streams" in d
        assert "ran_at" in d

    def test_as_dict_streams_contain_gap(self):
        report = self._make_report({"EEG": 10}, {"EEG": 7})
        d = report.as_dict()
        assert d["streams"]["EEG"]["gap"] == 3


# ---------------------------------------------------------------------------
# End-to-end: XDFWriter → read_xdf_counts → build_report
# ---------------------------------------------------------------------------


class TestEndToEnd:
    def test_xdf_counts_flow_into_report_correctly(self, xdf_file):
        path, expected = xdf_file
        xdf_counts = read_xdf_counts(path)
        # Simulate perfect DB (counts equal XDF counts)
        report = build_report(SESSION_ID, path, xdf_counts, xdf_counts)
        assert report.is_reconciled is True
        for name, count in expected.items():
            assert report.streams[name].xdf_count == count
            assert report.streams[name].gap == 0

    def test_simulated_db_loss_detected(self, xdf_file):
        path, expected = xdf_file
        xdf_counts = read_xdf_counts(path)
        # Simulate 5 EEG samples lost in DB
        db_counts = {**xdf_counts, "EEG": xdf_counts["EEG"] - 5}
        report = build_report(SESSION_ID, path, xdf_counts, db_counts)
        assert report.is_reconciled is False
        assert report.streams["EEG"].gap == 5


# ---------------------------------------------------------------------------
# DB integration tests — require TEST_DATABASE_URL
# ---------------------------------------------------------------------------

# Known UUIDs for the reconcile integration tests (distinct from test_schema)
# sessions.site_id / sponsor_id / participant_id are UUID columns — must be valid UUIDs.
# Biosignal tables use TEXT for those columns, so any string works there.
_REC_SESSION = "eeee0000-0000-0000-0000-000000000002"
_REC_PARTICIPANT = "eeee0000-aaaa-4444-0000-000000000002"
_REC_SITE = "eeee0001-0000-4444-0000-000000000002"
_REC_SPONSOR = "eeee0002-0000-4444-0000-000000000002"
_REC_DEVICE = "reconcile-test-device"
_REC_LSL = 99999.123456


@pytest.mark.integration
class TestQueryDBCounts:
    """These tests require a running DB with TEST_DATABASE_URL set.

    Run with: pytest -m integration tests/test_reconcile.py
    """

    def test_zero_counts_for_unknown_session(self, db_conn):
        fake_session = "00000000-0000-0000-0000-000000000099"
        counts = query_db_counts(db_conn, fake_session)
        for name in _ALL_STREAMS:
            assert counts[name] == 0

    def test_counts_reflect_inserted_samples(self, cursor, db_conn):
        """Insert 1 sample into each table and verify counts come back as 1."""
        # Ensure the session row exists (required for FK constraints if any)
        cursor.execute(
            """
            INSERT INTO sessions (
                id, site_id, sponsor_id, participant_id,
                compound, status, started_at
            ) VALUES (
                %s, %s, %s, %s, 'psilocybin', 'active', NOW()
            ) ON CONFLICT (id) DO NOTHING
            """,
            (_REC_SESSION, _REC_SITE, _REC_SPONSOR, _REC_PARTICIPANT),
        )

        # Insert one sample into each biosignal table
        cursor.execute(
            """INSERT INTO eeg_samples
                (session_id, participant_id, site_id, sponsor_id, device_id,
                 channel_id, voltage, lsl_timestamp, sample_index)
               VALUES (%s, %s, %s, %s, %s, 'ch_0', 1.0, %s, 0)""",
            (
                _REC_SESSION,
                _REC_PARTICIPANT,
                _REC_SITE,
                _REC_SPONSOR,
                _REC_DEVICE,
                _REC_LSL,
            ),
        )
        cursor.execute(
            """INSERT INTO hrv_samples
                (session_id, participant_id, site_id, sponsor_id, device_id,
                 rr_interval_ms, lsl_timestamp, sample_index)
               VALUES (%s, %s, %s, %s, %s, 860.0, %s, 0)""",
            (
                _REC_SESSION,
                _REC_PARTICIPANT,
                _REC_SITE,
                _REC_SPONSOR,
                _REC_DEVICE,
                _REC_LSL,
            ),
        )
        cursor.execute(
            """INSERT INTO eda_samples
                (session_id, participant_id, site_id, sponsor_id, device_id,
                 raw_conductance_us, conductance_us, lsl_timestamp, sample_index)
               VALUES (%s, %s, %s, %s, %s, 5.0, 5.0, %s, 0)""",
            (
                _REC_SESSION,
                _REC_PARTICIPANT,
                _REC_SITE,
                _REC_SPONSOR,
                _REC_DEVICE,
                _REC_LSL,
            ),
        )
        cursor.execute(
            """INSERT INTO respiration_samples
                (session_id, participant_id, site_id, sponsor_id, device_id,
                 raw_amplitude, processed_amplitude, lsl_timestamp, sample_index)
               VALUES (%s, %s, %s, %s, %s, 0.5, 0.5, %s, 0)""",
            (
                _REC_SESSION,
                _REC_PARTICIPANT,
                _REC_SITE,
                _REC_SPONSOR,
                _REC_DEVICE,
                _REC_LSL,
            ),
        )
        db_conn.commit()

        counts = query_db_counts(db_conn, _REC_SESSION)
        assert counts["EEG"] == 1
        assert counts["HRV"] == 1
        assert counts["EDA"] == 1
        assert counts["Respiration"] == 1


# ---------------------------------------------------------------------------
# stream_xdf_samples — unit tests (no DB required)
# ---------------------------------------------------------------------------


class TestStreamXDFSamples:
    def test_yields_correct_sample_count_eeg(self, xdf_file):
        path, expected = xdf_file
        samples = list(stream_xdf_samples(path, "EEG"))
        assert len(samples) == expected["EEG"]

    def test_yields_correct_sample_count_hrv(self, xdf_file):
        path, expected = xdf_file
        samples = list(stream_xdf_samples(path, "HRV"))
        assert len(samples) == expected["HRV"]

    def test_sample_index_is_sequential_from_zero(self, xdf_file):
        path, _ = xdf_file
        indices = [idx for idx, _, _ in stream_xdf_samples(path, "HRV")]
        assert indices == list(range(len(indices)))

    def test_timestamps_are_floats(self, xdf_file):
        path, _ = xdf_file
        for _, ts, _ in stream_xdf_samples(path, "EDA"):
            assert isinstance(ts, float)

    def test_eeg_channel_values_are_8_per_sample(self, xdf_file):
        path, _ = xdf_file
        for _, _, vals in stream_xdf_samples(path, "EEG"):
            assert len(vals) == 8

    def test_hrv_has_one_channel(self, xdf_file):
        path, _ = xdf_file
        for _, _, vals in stream_xdf_samples(path, "HRV"):
            assert len(vals) == 1

    def test_skips_other_streams(self, xdf_file):
        path, expected = xdf_file
        eeg_samples = list(stream_xdf_samples(path, "EEG"))
        hrv_samples = list(stream_xdf_samples(path, "HRV"))
        # EEG and HRV streams are independent — counts should match expected
        assert len(eeg_samples) == expected["EEG"]
        assert len(hrv_samples) == expected["HRV"]

    def test_values_recoverable_for_known_write(self, tmp_path, monkeypatch):
        import config.settings as s

        monkeypatch.setattr(s, "XDF_BACKUP_DIR", tmp_path)
        w = XDFWriter(SESSION_ID, SITE_ID, SPONSOR_ID)
        known_vals = [1.1, 2.2, 3.3, 4.4, 5.5, 6.6, 7.7, 8.8]
        w.write_samples("EEG", [known_vals], [42.0])
        w.close()
        samples = list(stream_xdf_samples(w.path, "EEG"))
        assert len(samples) == 1
        _, ts, vals = samples[0]
        assert ts == pytest.approx(42.0)
        assert vals == pytest.approx(known_vals, abs=1e-5)

    def test_empty_stream_yields_nothing(self, xdf_file_empty):
        samples = list(stream_xdf_samples(xdf_file_empty, "EEG"))
        assert samples == []

    def test_wrong_magic_raises(self, tmp_path):
        bad = tmp_path / "bad.xdf"
        bad.write_bytes(b"NOTXDF")
        with pytest.raises(XDFReadError):
            list(stream_xdf_samples(bad, "EEG"))

    def test_multi_chunk_indices_are_contiguous(self, tmp_path, monkeypatch):
        import config.settings as s

        monkeypatch.setattr(s, "XDF_BACKUP_DIR", tmp_path)
        w = XDFWriter(SESSION_ID, SITE_ID, SPONSOR_ID)
        w.write_samples("HRV", [[800.0]] * 5, list(range(5)))
        w.write_samples("HRV", [[810.0]] * 3, list(range(5, 8)))
        w.write_samples("HRV", [[820.0]] * 2, list(range(8, 10)))
        w.close()
        indices = [i for i, _, _ in stream_xdf_samples(w.path, "HRV")]
        assert indices == list(range(10))


# ---------------------------------------------------------------------------
# _build_backfill_rows — unit tests
# ---------------------------------------------------------------------------

_META = SessionMeta(
    participant_id="test-participant",
    site_id="SITE-01",
    sponsor_id="SPONSOR-01",
)
_SID = "aaaa0000-0000-0000-0000-bbbbbbbbbbbb"


class TestBuildBackfillRows:
    def test_eeg_returns_8_rows(self):
        rows = _build_backfill_rows(
            "EEG", _SID, 0, 1.0, [float(i) for i in range(8)], _META
        )
        assert len(rows) == 8

    def test_eeg_channel_ids_correct(self):
        rows = _build_backfill_rows("EEG", _SID, 0, 1.0, [0.0] * 8, _META)
        channel_ids = [r["channel_id"] for r in rows]
        assert channel_ids == [f"ch_{i}" for i in range(8)]

    def test_eeg_voltage_values_correct(self):
        vals = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]
        rows = _build_backfill_rows("EEG", _SID, 0, 1.0, vals, _META)
        voltages = [r["voltage"] for r in rows]
        assert voltages == pytest.approx(vals)

    def test_hrv_returns_one_row(self):
        rows = _build_backfill_rows("HRV", _SID, 0, 1.0, [857.0], _META)
        assert len(rows) == 1

    def test_hrv_derives_heart_rate(self):
        rows = _build_backfill_rows("HRV", _SID, 0, 1.0, [600.0], _META)
        assert rows[0]["heart_rate_bpm"] == pytest.approx(100.0)

    def test_hrv_zero_rr_gives_none_bpm(self):
        rows = _build_backfill_rows("HRV", _SID, 0, 1.0, [0.0], _META)
        assert rows[0]["heart_rate_bpm"] is None

    def test_eda_conductance_us_equals_raw(self):
        rows = _build_backfill_rows("EDA", _SID, 0, 1.0, [5.0], _META)
        assert rows[0]["raw_conductance_us"] == rows[0]["conductance_us"]

    def test_respiration_processed_equals_raw(self):
        rows = _build_backfill_rows("Respiration", _SID, 0, 1.0, [0.5], _META)
        assert rows[0]["raw_amplitude"] == rows[0]["processed_amplitude"]

    def test_session_id_propagated(self):
        rows = _build_backfill_rows("HRV", _SID, 0, 1.0, [800.0], _META)
        assert rows[0]["session_id"] == _SID

    def test_sample_index_propagated(self):
        rows = _build_backfill_rows("EDA", _SID, 42, 1.0, [5.0], _META)
        assert rows[0]["sample_index"] == 42

    def test_lsl_timestamp_propagated(self):
        rows = _build_backfill_rows("HRV", _SID, 0, 99.5, [800.0], _META)
        assert rows[0]["lsl_timestamp"] == pytest.approx(99.5)

    def test_participant_site_sponsor_from_meta(self):
        rows = _build_backfill_rows("EDA", _SID, 0, 1.0, [5.0], _META)
        r = rows[0]
        assert r["participant_id"] == _META.participant_id
        assert r["site_id"] == _META.site_id
        assert r["sponsor_id"] == _META.sponsor_id

    def test_nullable_fields_are_none(self):
        hrv = _build_backfill_rows("HRV", _SID, 0, 1.0, [800.0], _META)[0]
        eda = _build_backfill_rows("EDA", _SID, 0, 1.0, [5.0], _META)[0]
        resp = _build_backfill_rows("Respiration", _SID, 0, 1.0, [0.5], _META)[0]
        assert hrv["beat_quality"] is None
        assert eda["signal_quality"] is None
        assert resp["breath_phase"] is None
        assert resp["breaths_per_min"] is None

    def test_unknown_stream_raises(self):
        with pytest.raises(ValueError, match="unknown stream_name"):
            _build_backfill_rows("Bogus", _SID, 0, 1.0, [1.0], _META)


# ---------------------------------------------------------------------------
# BACKFILL_CHUNK_SIZE_ROWS constant sanity check
# ---------------------------------------------------------------------------


class TestBackfillConstants:
    def test_chunk_size_is_positive(self):
        assert BACKFILL_CHUNK_SIZE_ROWS > 0

    def test_chunk_size_is_reasonable(self):
        # Should be tunable in Phase 5; default must be between 100 and 10,000
        assert 100 <= BACKFILL_CHUNK_SIZE_ROWS <= 10_000


# ---------------------------------------------------------------------------
# Integration test — simulated DB interruption + XDF backfill
# ---------------------------------------------------------------------------

_BF_SESSION = "cccc3333-bbbb-4444-aaaa-000000000099"
_BF_PARTICIPANT = "ffffffff-aaaa-4444-bbbb-000000000001"
_BF_SITE = "cccc3333-1111-4444-aaaa-000000000099"
_BF_SPONSOR = "cccc3333-2222-4444-aaaa-000000000099"
_BF_DEVICE = "backfill-test-device"


@pytest.mark.integration
class TestXDFBackfillSimulation:
    """Simulates a mid-session DB outage: XDF has all samples, DB has only
    a partial set. Verifies that backfill closes every gap and is idempotent.

    chunk_size=8 is intentionally small so that:
      - EEG (8 channels × 20 missing samples = 160 rows) → 20 commits
      - HRV (4 missing samples × 1 row) → 1 partial commit
      - Respiration (10 missing samples × 1 row) → 2 commits (8 + 2)
    This exercises the chunking code path without writing thousands of rows.
    """

    def test_backfill_closes_gaps_and_is_idempotent(
        self, cursor, db_conn, tmp_path, monkeypatch
    ):
        import config.settings as s

        monkeypatch.setattr(s, "XDF_BACKUP_DIR", tmp_path)
        monkeypatch.setattr(s, "DEVICE_ID", _BF_DEVICE)

        # ------------------------------------------------------------------ #
        # 1. Build XDF with complete sample set                               #
        # ------------------------------------------------------------------ #
        w = XDFWriter(_BF_SESSION, _BF_SITE, _BF_SPONSOR)
        w.write_samples("EEG", [[float(i)] * 8 for i in range(50)], list(range(50)))
        w.write_samples("HRV", [[800.0 + i] for i in range(10)], list(range(10)))
        w.write_samples("EDA", [[5.0 + i * 0.1] for i in range(20)], list(range(20)))
        w.write_samples(
            "Respiration", [[0.5 + i * 0.01] for i in range(15)], list(range(15))
        )
        w.close()
        xdf_path = w.path

        try:
            # ---------------------------------------------------------------- #
            # 2. Insert partial data into DB — simulates mid-session outage    #
            #    Present:  EEG 0-29 (30/50), HRV 0-5 (6/10),                  #
            #              EDA 0-19 (20/20, full), Respiration 0-4 (5/15)      #
            #    Missing:  EEG 30-49 (gap=20), HRV 6-9 (gap=4),               #
            #              Respiration 5-14 (gap=10)                           #
            # ---------------------------------------------------------------- #
            cursor.execute(
                """
                INSERT INTO sessions
                    (id, site_id, sponsor_id, participant_id, compound, status, started_at)
                VALUES (%s, %s, %s, %s, 'psilocybin', 'active', NOW())
                ON CONFLICT (id) DO NOTHING
                """,
                (_BF_SESSION, _BF_SITE, _BF_SPONSOR, _BF_PARTICIPANT),
            )

            # EEG narrow-row: 8 rows per LSL sample
            for si in range(30):
                for ch in range(8):
                    cursor.execute(
                        """INSERT INTO eeg_samples
                            (session_id, participant_id, site_id, sponsor_id, device_id,
                             channel_id, voltage, lsl_timestamp, sample_index)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                        (
                            _BF_SESSION,
                            _BF_PARTICIPANT,
                            _BF_SITE,
                            _BF_SPONSOR,
                            _BF_DEVICE,
                            f"ch_{ch}",
                            float(si),
                            float(si),
                            si,
                        ),
                    )

            for si in range(6):
                cursor.execute(
                    """INSERT INTO hrv_samples
                        (session_id, participant_id, site_id, sponsor_id, device_id,
                         rr_interval_ms, lsl_timestamp, sample_index)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                    (
                        _BF_SESSION,
                        _BF_PARTICIPANT,
                        _BF_SITE,
                        _BF_SPONSOR,
                        _BF_DEVICE,
                        800.0 + si,
                        float(si),
                        si,
                    ),
                )

            for si in range(20):
                cursor.execute(
                    """INSERT INTO eda_samples
                        (session_id, participant_id, site_id, sponsor_id, device_id,
                         raw_conductance_us, conductance_us, lsl_timestamp, sample_index)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (
                        _BF_SESSION,
                        _BF_PARTICIPANT,
                        _BF_SITE,
                        _BF_SPONSOR,
                        _BF_DEVICE,
                        5.0 + si * 0.1,
                        5.0 + si * 0.1,
                        float(si),
                        si,
                    ),
                )

            for si in range(5):
                cursor.execute(
                    """INSERT INTO respiration_samples
                        (session_id, participant_id, site_id, sponsor_id, device_id,
                         raw_amplitude, processed_amplitude, lsl_timestamp, sample_index)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (
                        _BF_SESSION,
                        _BF_PARTICIPANT,
                        _BF_SITE,
                        _BF_SPONSOR,
                        _BF_DEVICE,
                        0.5 + si * 0.01,
                        0.5 + si * 0.01,
                        float(si),
                        si,
                    ),
                )

            db_conn.commit()

            # ---------------------------------------------------------------- #
            # 3. Confirm gaps are detected before backfill                     #
            # ---------------------------------------------------------------- #
            xdf_counts = read_xdf_counts(xdf_path)
            db_counts = query_db_counts(db_conn, _BF_SESSION)
            report = build_report(_BF_SESSION, xdf_path, xdf_counts, db_counts)

            assert report.is_reconciled is False
            assert report.streams["EEG"].gap == 20
            assert report.streams["HRV"].gap == 4
            assert report.streams["EDA"].gap == 0
            assert report.streams["Respiration"].gap == 10

            # ---------------------------------------------------------------- #
            # 4. Run backfill with chunk_size=8 to exercise chunking logic     #
            # ---------------------------------------------------------------- #
            meta = SessionMeta(
                participant_id=_BF_PARTICIPANT,
                site_id=_BF_SITE,
                sponsor_id=_BF_SPONSOR,
            )
            run_backfill(db_conn, report, meta, chunk_size=8)

            # ---------------------------------------------------------------- #
            # 5. Verify all gaps are closed                                    #
            # ---------------------------------------------------------------- #
            db_counts_after = query_db_counts(db_conn, _BF_SESSION)
            report_after = build_report(
                _BF_SESSION, xdf_path, xdf_counts, db_counts_after
            )

            assert report_after.is_reconciled is True
            assert report_after.streams["EEG"].db_count == 50
            assert report_after.streams["HRV"].db_count == 10
            assert report_after.streams["EDA"].db_count == 20
            assert report_after.streams["Respiration"].db_count == 15

            # ---------------------------------------------------------------- #
            # 6. Verify sample_index values are contiguous 0..N-1              #
            # ---------------------------------------------------------------- #
            for table, expected_n in (
                ("eeg_samples", 50),
                ("hrv_samples", 10),
                ("eda_samples", 20),
                ("respiration_samples", 15),
            ):
                cursor.execute(
                    f"SELECT DISTINCT sample_index FROM {table} "
                    f"WHERE session_id = %s ORDER BY sample_index",
                    (_BF_SESSION,),
                )
                indices = [row[0] for row in cursor.fetchall()]
                assert indices == list(range(expected_n)), (
                    f"{table}: expected indices 0..{expected_n - 1}, "
                    f"got {len(indices)} values starting with {indices[:5]}"
                )

            # ---------------------------------------------------------------- #
            # 7. Idempotency — re-run with original gap-containing report      #
            #    ON CONFLICT DO NOTHING + frozenset dedup must prevent doubles  #
            # ---------------------------------------------------------------- #
            run_backfill(db_conn, report, meta, chunk_size=8)
            db_counts_rerun = query_db_counts(db_conn, _BF_SESSION)

            assert db_counts_rerun["EEG"] == 50
            assert db_counts_rerun["HRV"] == 10
            assert db_counts_rerun["EDA"] == 20
            assert db_counts_rerun["Respiration"] == 15

        finally:
            # backfill_stream commits internally so the rollback in db_conn
            # teardown won't clean up those rows — we must DELETE explicitly.
            for table in (
                "eeg_samples",
                "hrv_samples",
                "eda_samples",
                "respiration_samples",
            ):
                cursor.execute(
                    f"DELETE FROM {table} WHERE session_id = %s",
                    (_BF_SESSION,),
                )
            cursor.execute("DELETE FROM sessions WHERE id = %s", (_BF_SESSION,))
            db_conn.commit()
