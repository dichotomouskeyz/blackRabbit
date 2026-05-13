"""Backfill and sample reconstruction tests for reconciliation."""

import pytest

from batch.reconcile import (
    BACKFILL_CHUNK_SIZE_ROWS,
    SessionMeta,
    _build_backfill_rows,
    build_report,
    query_db_counts,
    read_xdf_counts,
    run_backfill,
)
from capture.xdf_writer import XDFWriter
from tests.reconcile_test._support import (
    _BF_DEVICE,
    _BF_PARTICIPANT,
    _BF_SESSION,
    _BF_SITE,
    _BF_SPONSOR,
)


_META = SessionMeta(
    participant_id="test-participant",
    site_id="SITE-01",
    sponsor_id="SPONSOR-01",
)
_SID = "aaaa0000-0000-0000-0000-bbbbbbbbbbbb"


class TestBuildBackfillRows:
    def test_eeg_returns_8_rows(self):
        rows = _build_backfill_rows("EEG", _SID, 0, 1.0, [float(i) for i in range(8)], _META)
        assert len(rows) == 8

    def test_eeg_channel_ids_correct(self):
        rows = _build_backfill_rows("EEG", _SID, 0, 1.0, [0.0] * 8, _META)
        assert [r["channel_id"] for r in rows] == [f"ch_{i}" for i in range(8)]

    def test_eeg_voltage_values_correct(self):
        vals = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]
        rows = _build_backfill_rows("EEG", _SID, 0, 1.0, vals, _META)
        assert [r["voltage"] for r in rows] == pytest.approx(vals)

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


class TestBackfillConstants:
    def test_chunk_size_is_positive(self):
        assert BACKFILL_CHUNK_SIZE_ROWS > 0

    def test_chunk_size_is_reasonable(self):
        assert 100 <= BACKFILL_CHUNK_SIZE_ROWS <= 10_000


@pytest.mark.integration
class TestXDFBackfillSimulation:
    def test_backfill_closes_gaps_and_is_idempotent(self, cursor, db_conn, tmp_path, monkeypatch):
        import config.settings as s

        monkeypatch.setattr(s, "XDF_BACKUP_DIR", tmp_path)
        monkeypatch.setattr(s, "DEVICE_ID", _BF_DEVICE)

        w = XDFWriter(_BF_SESSION, _BF_SITE, _BF_SPONSOR)
        w.write_samples("EEG", [[float(i)] * 8 for i in range(50)], list(range(50)))
        w.write_samples("HRV", [[800.0 + i] for i in range(10)], list(range(10)))
        w.write_samples("EDA", [[5.0 + i * 0.1] for i in range(20)], list(range(20)))
        w.write_samples("Respiration", [[0.5 + i * 0.01] for i in range(15)], list(range(15)))
        w.write_marker("ECHO|proximity_state_change|therapist_01|therapist|in_room", 100.0)
        w.write_marker("ECHO|proximity_state_change|therapist_01|therapist|arms_reach", 105.0)
        w.close()
        xdf_path = w.path

        try:
            cursor.execute(
                """
                INSERT INTO sessions
                    (id, site_id, sponsor_id, participant_id, compound, status, started_at)
                VALUES (%s, %s, %s, %s, 'psilocybin', 'active', NOW())
                ON CONFLICT (id) DO NOTHING
                """,
                (_BF_SESSION, _BF_SITE, _BF_SPONSOR, _BF_PARTICIPANT),
            )

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

            cursor.execute(
                """INSERT INTO echo_events
                    (session_id, participant_id, site_id, sponsor_id,
                     event_type, source, actor_id, actor_role, zone_label, lsl_timestamp)
                   VALUES (%s, %s, %s, %s,
                           'proximity_state_change', 'manual_logging',
                           'therapist_01', 'therapist', 'in_room', %s)""",
                (_BF_SESSION, _BF_PARTICIPANT, _BF_SITE, _BF_SPONSOR, 100.0),
            )

            db_conn.commit()

            xdf_counts = read_xdf_counts(xdf_path)
            db_counts = query_db_counts(db_conn, _BF_SESSION)
            report = build_report(_BF_SESSION, xdf_path, xdf_counts, db_counts)

            assert report.is_reconciled is False
            assert report.streams["EEG"].gap == 20
            assert report.streams["HRV"].gap == 4
            assert report.streams["EDA"].gap == 0
            assert report.streams["Respiration"].gap == 10
            assert report.streams["ECHO"].gap == 1

            meta = SessionMeta(
                participant_id=_BF_PARTICIPANT,
                site_id=_BF_SITE,
                sponsor_id=_BF_SPONSOR,
            )
            run_backfill(db_conn, report, meta, chunk_size=8)

            db_counts_after = query_db_counts(db_conn, _BF_SESSION)
            report_after = build_report(_BF_SESSION, xdf_path, xdf_counts, db_counts_after)

            assert report_after.is_reconciled is True
            assert report_after.streams["EEG"].db_count == 50
            assert report_after.streams["HRV"].db_count == 10
            assert report_after.streams["EDA"].db_count == 20
            assert report_after.streams["Respiration"].db_count == 15
            assert report_after.streams["ECHO"].db_count == 2

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
                assert indices == list(range(expected_n))

            run_backfill(db_conn, report, meta, chunk_size=8)
            db_counts_rerun = query_db_counts(db_conn, _BF_SESSION)

            assert db_counts_rerun["EEG"] == 50
            assert db_counts_rerun["HRV"] == 10
            assert db_counts_rerun["EDA"] == 20
            assert db_counts_rerun["Respiration"] == 15
            assert db_counts_rerun["ECHO"] == 2

        finally:
            for table in (
                "eeg_samples",
                "hrv_samples",
                "eda_samples",
                "respiration_samples",
            ):
                cursor.execute(f"DELETE FROM {table} WHERE session_id = %s", (_BF_SESSION,))
            cursor.execute("DELETE FROM echo_events WHERE session_id = %s", (_BF_SESSION,))
            cursor.execute("DELETE FROM sessions WHERE id = %s", (_BF_SESSION,))
            db_conn.commit()
