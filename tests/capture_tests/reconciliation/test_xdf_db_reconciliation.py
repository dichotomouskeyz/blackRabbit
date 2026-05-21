"""Happy-path XDF-vs-DB reconciliation integration tests.

After a simulated session XDF counts == DB counts → is_reconciled=True.
Distinct from the backfill/recovery tests in test_backfill.py.
"""

import pytest

from batch.reconcile import build_report, query_db_counts, read_xdf_counts
from batch.reconciliation.db import write_reconciliation_log
from batch.reconciliation.models import SessionMeta
from capture.xdf.writer import XDFWriter
from tests.capture_tests.forwarder.support import (
    _INT_DEVICE,
    _insert_session_row,
)

_REC_EEG_N = 20
_REC_HRV_N = 5
_REC_EDA_N = 8
_REC_RESP_N = 6

_REC_SESSION = "f1d00002-0000-4444-aaaa-000000000002"
_REC_PART = "f1d00002-0000-4444-bbbb-000000000002"
_REC_SITE = "f1d00002-0000-4444-cccc-000000000002"
_REC_SPONSOR = "f1d00002-0000-4444-dddd-000000000002"


def _get_integrity_rows(cursor, session_id):
    cursor.execute(
        """
        SELECT log_type, reconciliation_report
        FROM biosignal_integrity_log
        WHERE session_id = %s
        ORDER BY id
        """,
        (session_id,),
    )
    return cursor.fetchall()


@pytest.mark.integration
class TestXDFMatchesTimescaleDB:
    """After a simulated session XDF counts == DB counts → is_reconciled=True."""

    def test_happy_path_all_streams_reconciled(self, cursor, db_conn, tmp_path, monkeypatch):
        import config.settings as s

        monkeypatch.setattr(s, "XDF_BACKUP_DIR", tmp_path)
        monkeypatch.setattr(s, "DEVICE_ID", _INT_DEVICE)

        w = XDFWriter(_REC_SESSION, _REC_PART, _REC_SITE, _REC_SPONSOR)
        w.write_samples(
            "EEG",
            [[float(i)] * 8 for i in range(_REC_EEG_N)],
            list(range(_REC_EEG_N)),
        )
        w.write_samples(
            "HRV",
            [[800.0 + i] for i in range(_REC_HRV_N)],
            list(range(_REC_HRV_N)),
        )
        w.write_samples(
            "EDA",
            [[5.0 + i * 0.1] for i in range(_REC_EDA_N)],
            list(range(_REC_EDA_N)),
        )
        w.write_samples(
            "Respiration",
            [[0.5 + i * 0.01] for i in range(_REC_RESP_N)],
            list(range(_REC_RESP_N)),
        )
        w.close()
        xdf_path = w.path

        _insert_session_row(cursor, _REC_SESSION, _REC_SITE, _REC_SPONSOR, _REC_PART)

        for si in range(_REC_EEG_N):
            for ch in range(8):
                cursor.execute(
                    """INSERT INTO eeg_samples
                       (session_id, participant_id, site_id, sponsor_id, device_id,
                        channel_id, voltage, lsl_timestamp, sample_index)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (_REC_SESSION, _REC_PART, _REC_SITE, _REC_SPONSOR, _INT_DEVICE,
                     f"ch_{ch}", float(si), float(si), si),
                )
        for si in range(_REC_HRV_N):
            cursor.execute(
                """INSERT INTO hrv_samples
                   (session_id, participant_id, site_id, sponsor_id, device_id,
                    rr_interval_ms, lsl_timestamp, sample_index)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (_REC_SESSION, _REC_PART, _REC_SITE, _REC_SPONSOR, _INT_DEVICE,
                 800.0 + si, float(si), si),
            )
        for si in range(_REC_EDA_N):
            cursor.execute(
                """INSERT INTO eda_samples
                   (session_id, participant_id, site_id, sponsor_id, device_id,
                    raw_conductance_us, conductance_us, lsl_timestamp, sample_index)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (_REC_SESSION, _REC_PART, _REC_SITE, _REC_SPONSOR, _INT_DEVICE,
                 5.0 + si * 0.1, 5.0 + si * 0.1, float(si), si),
            )
        for si in range(_REC_RESP_N):
            cursor.execute(
                """INSERT INTO respiration_samples
                   (session_id, participant_id, site_id, sponsor_id, device_id,
                    raw_amplitude, processed_amplitude, lsl_timestamp, sample_index)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (_REC_SESSION, _REC_PART, _REC_SITE, _REC_SPONSOR, _INT_DEVICE,
                 0.5 + si * 0.01, 0.5 + si * 0.01, float(si), si),
            )

        xdf_counts = read_xdf_counts(xdf_path)
        db_counts = query_db_counts(db_conn, _REC_SESSION)
        report = build_report(_REC_SESSION, xdf_path, xdf_counts, db_counts)

        assert report.is_reconciled is True, "Expected reconciled=True, got streams: " + ", ".join(
            f"{k}(gap={v.gap})" for k, v in report.streams.items()
        )

    def test_reconciliation_log_written(self, cursor, db_conn, tmp_path, monkeypatch):
        import config.settings as s

        monkeypatch.setattr(s, "XDF_BACKUP_DIR", tmp_path)
        monkeypatch.setattr(s, "DEVICE_ID", _INT_DEVICE)

        w = XDFWriter(_REC_SESSION, _REC_PART, _REC_SITE, _REC_SPONSOR)
        w.write_samples("EEG", [[0.0] * 8], [0])
        w.close()

        _insert_session_row(cursor, _REC_SESSION, _REC_SITE, _REC_SPONSOR, _REC_PART)
        for ch in range(8):
            cursor.execute(
                """INSERT INTO eeg_samples
                   (session_id, participant_id, site_id, sponsor_id, device_id,
                    channel_id, voltage, lsl_timestamp, sample_index)
                   VALUES (%s, %s, %s, %s, %s, %s, 0.0, 0.0, 0)""",
                (_REC_SESSION, _REC_PART, _REC_SITE, _REC_SPONSOR, _INT_DEVICE, f"ch_{ch}"),
            )

        xdf_counts = read_xdf_counts(w.path)
        db_counts = query_db_counts(db_conn, _REC_SESSION)
        report = build_report(_REC_SESSION, w.path, xdf_counts, db_counts)

        write_reconciliation_log(
            db_conn,
            SessionMeta(
                participant_id=_REC_PART,
                site_id=_REC_SITE,
                sponsor_id=_REC_SPONSOR,
            ),
            report,
        )
        db_conn.commit()

        rows = _get_integrity_rows(cursor, _REC_SESSION)
        assert rows[0][0] == "xdf_reconciliation"
        assert rows[0][1]["is_reconciled"] is True

    def test_happy_path_eeg_count_exact(self, cursor, db_conn, tmp_path, monkeypatch):
        import config.settings as s

        monkeypatch.setattr(s, "XDF_BACKUP_DIR", tmp_path)
        monkeypatch.setattr(s, "DEVICE_ID", _INT_DEVICE)

        w = XDFWriter(_REC_SESSION, _REC_PART, _REC_SITE, _REC_SPONSOR)
        w.write_samples("EEG", [[0.0] * 8] * _REC_EEG_N, list(range(_REC_EEG_N)))
        w.close()

        _insert_session_row(cursor, _REC_SESSION, _REC_SITE, _REC_SPONSOR, _REC_PART)
        for si in range(_REC_EEG_N):
            for ch in range(8):
                cursor.execute(
                    """INSERT INTO eeg_samples
                       (session_id, participant_id, site_id, sponsor_id, device_id,
                        channel_id, voltage, lsl_timestamp, sample_index)
                       VALUES (%s, %s, %s, %s, %s, %s, 0.0, %s, %s)""",
                    (_REC_SESSION, _REC_PART, _REC_SITE, _REC_SPONSOR, _INT_DEVICE,
                     f"ch_{ch}", float(si), si),
                )

        xdf_counts = read_xdf_counts(w.path)
        db_counts = query_db_counts(db_conn, _REC_SESSION)
        report = build_report(_REC_SESSION, w.path, xdf_counts, db_counts)

        assert report.streams["EEG"].xdf_count == _REC_EEG_N
        assert report.streams["EEG"].db_count == _REC_EEG_N
        assert report.streams["EEG"].gap == 0

    def test_happy_path_gap_zero_for_all_streams(self, cursor, db_conn, tmp_path, monkeypatch):
        import config.settings as s

        monkeypatch.setattr(s, "XDF_BACKUP_DIR", tmp_path)
        monkeypatch.setattr(s, "DEVICE_ID", _INT_DEVICE)

        w = XDFWriter(_REC_SESSION, _REC_PART, _REC_SITE, _REC_SPONSOR)
        w.write_samples("EEG", [[0.0] * 8] * _REC_EEG_N, list(range(_REC_EEG_N)))
        w.write_samples("HRV", [[800.0]] * _REC_HRV_N, list(range(_REC_HRV_N)))
        w.write_samples("EDA", [[5.0]] * _REC_EDA_N, list(range(_REC_EDA_N)))
        w.write_samples("Respiration", [[0.5]] * _REC_RESP_N, list(range(_REC_RESP_N)))
        w.close()

        _insert_session_row(cursor, _REC_SESSION, _REC_SITE, _REC_SPONSOR, _REC_PART)
        for si in range(_REC_EEG_N):
            for ch in range(8):
                cursor.execute(
                    """INSERT INTO eeg_samples
                       (session_id, participant_id, site_id, sponsor_id, device_id,
                        channel_id, voltage, lsl_timestamp, sample_index)
                       VALUES (%s, %s, %s, %s, %s, %s, 0.0, %s, %s)""",
                    (_REC_SESSION, _REC_PART, _REC_SITE, _REC_SPONSOR, _INT_DEVICE,
                     f"ch_{ch}", float(si), si),
                )
        for si in range(_REC_HRV_N):
            cursor.execute(
                """INSERT INTO hrv_samples
                   (session_id, participant_id, site_id, sponsor_id, device_id,
                    rr_interval_ms, lsl_timestamp, sample_index)
                   VALUES (%s, %s, %s, %s, %s, 800.0, %s, %s)""",
                (_REC_SESSION, _REC_PART, _REC_SITE, _REC_SPONSOR, _INT_DEVICE, float(si), si),
            )
        for si in range(_REC_EDA_N):
            cursor.execute(
                """INSERT INTO eda_samples
                   (session_id, participant_id, site_id, sponsor_id, device_id,
                    raw_conductance_us, conductance_us, lsl_timestamp, sample_index)
                   VALUES (%s, %s, %s, %s, %s, 5.0, 5.0, %s, %s)""",
                (_REC_SESSION, _REC_PART, _REC_SITE, _REC_SPONSOR, _INT_DEVICE, float(si), si),
            )
        for si in range(_REC_RESP_N):
            cursor.execute(
                """INSERT INTO respiration_samples
                   (session_id, participant_id, site_id, sponsor_id, device_id,
                    raw_amplitude, processed_amplitude, lsl_timestamp, sample_index)
                   VALUES (%s, %s, %s, %s, %s, 0.5, 0.5, %s, %s)""",
                (_REC_SESSION, _REC_PART, _REC_SITE, _REC_SPONSOR, _INT_DEVICE, float(si), si),
            )

        xdf_counts = read_xdf_counts(w.path)
        db_counts = query_db_counts(db_conn, _REC_SESSION)
        report = build_report(_REC_SESSION, w.path, xdf_counts, db_counts)

        for stream_name in ("EEG", "HRV", "EDA", "Respiration"):
            assert report.streams[stream_name].gap == 0, (
                f"{stream_name}: expected gap=0, got {report.streams[stream_name].gap}"
            )
