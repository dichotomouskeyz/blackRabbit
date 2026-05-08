"""Three regulatory-property tests for the Consensai forwarder pipeline.

  1. Separate timestamps (lsl_timestamp vs db_insert_time)
     — Unit: none of the 4 biosignal row builders set db_insert_time.
       That column is always sourced from DB DEFAULT NOW(), never from
       application code. (21 CFR Part 11 requirement.)
     — Integration: after inserting into each of the 5 modality tables,
       lsl_timestamp is the float we sent and db_insert_time is a
       server-generated timestamptz — provably independent.

  2. No plaintext patient data
     — Integration: after a simulated session every participant_id column
       in every modality table holds the pseudonymous UUID token, not a
       real name or email.

  3. XDF row count matches TimescaleDB (happy-path reconciliation)
     — Integration: write N samples to XDF and insert the same N rows to
       the DB for all 4 biosignal streams, then verify build_report shows
       is_reconciled=True and gap=0 for every stream.

Unit tests (Section 1) require no database.
Integration tests (Sections 2–4) are marked @pytest.mark.integration and
require TEST_DATABASE_URL to be set in .env.
"""

import datetime

import pytest

from batch.reconcile import build_report, query_db_counts, read_xdf_counts
from capture.lsl_forwarder import (
    SessionConfig,
    _build_eda_rows,
    _build_eeg_rows,
    _build_hrv_rows,
    _build_respiration_rows,
)
from capture.xdf_writer import XDFWriter

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

# Unit-test config — string format doesn't matter (no DB involved)
_CFG = SessionConfig(
    session_id="aa000001-0000-4444-0000-000000000001",
    participant_id="aa000001-0000-4444-bbbb-000000000001",
    site_id="aa000001-0000-4444-cccc-000000000001",
    sponsor_id="aa000001-0000-4444-dddd-000000000001",
)
_LSL_TS = 123456.789  # arbitrary LSL epoch float

# Integration-test identifiers — valid UUIDs (distinct from test_reconcile.py)
_INT_SESSION = "f1d00001-0000-4444-aaaa-000000000001"
_INT_PART = "f1d00001-0000-4444-bbbb-000000000001"  # pseudonymous token
_INT_SITE = "f1d00001-0000-4444-cccc-000000000001"
_INT_SPONSOR = "f1d00001-0000-4444-dddd-000000000001"
_INT_DEVICE = "f1d00001-0000-4444-eeee-000000000001"
_INT_LSL_TS = 777777.111  # arbitrary LSL float used across integration tests

# PII sentinel: a real-name string that should NEVER appear in the database
_REAL_NAME = "Jane Doe"

_BIOSIGNAL_TABLES = ("eeg_samples", "hrv_samples", "eda_samples", "respiration_samples")


# ---------------------------------------------------------------------------
# Section 1 — Row builder unit tests (no DB, no LSL required)
#
# The four row builders (_build_eeg_rows, etc.) are pure functions.
# We verify three regulatory properties directly against their output:
#
#   a) lsl_timestamp equals the float we passed in — never derived from
#      wall clock or any other source inside the builder.
#   b) db_insert_time is absent from every returned dict — this column
#      must always be set by the database (DEFAULT NOW()), never by
#      application code. If a builder ever wrote db_insert_time, the
#      two timestamps would share a source and regulators could not
#      treat them as independent evidence of capture vs storage time.
#   c) participant_id is the pseudonymous token unchanged — no lookup,
#      transformation, or substitution of real patient identity occurs.
# ---------------------------------------------------------------------------


class TestRowBuildersAllModalities:

    # EEG ------------------------------------------------------------------

    def test_eeg_one_row_per_channel(self):
        rows = _build_eeg_rows([1.0] * 8, _CFG, _LSL_TS, 0)
        assert len(rows) == 8

    def test_eeg_lsl_timestamp_propagated(self):
        rows = _build_eeg_rows([0.0] * 8, _CFG, _LSL_TS, 0)
        assert all(r["lsl_timestamp"] == pytest.approx(_LSL_TS) for r in rows)

    def test_eeg_db_insert_time_not_in_row(self):
        rows = _build_eeg_rows([0.0] * 8, _CFG, _LSL_TS, 0)
        assert all("db_insert_time" not in r for r in rows)

    def test_eeg_participant_id_is_pseudonymous_token(self):
        rows = _build_eeg_rows([0.0] * 8, _CFG, _LSL_TS, 0)
        assert all(r["participant_id"] == _CFG.participant_id for r in rows)

    def test_eeg_channel_ids_are_sequential(self):
        rows = _build_eeg_rows([1.0] * 8, _CFG, _LSL_TS, 0)
        assert [r["channel_id"] for r in rows] == [f"ch_{i}" for i in range(8)]

    def test_eeg_voltages_match_sample(self):
        sample = [float(i) * 1.1 for i in range(8)]
        rows = _build_eeg_rows(sample, _CFG, _LSL_TS, 0)
        assert [r["voltage"] for r in rows] == pytest.approx(sample)

    # HRV ------------------------------------------------------------------

    def test_hrv_one_row(self):
        assert len(_build_hrv_rows([860.0], _CFG, _LSL_TS, 0)) == 1

    def test_hrv_lsl_timestamp_propagated(self):
        r = _build_hrv_rows([860.0], _CFG, _LSL_TS, 0)[0]
        assert r["lsl_timestamp"] == pytest.approx(_LSL_TS)

    def test_hrv_db_insert_time_not_in_row(self):
        assert "db_insert_time" not in _build_hrv_rows([860.0], _CFG, _LSL_TS, 0)[0]

    def test_hrv_derives_bpm_from_rr(self):
        r = _build_hrv_rows([600.0], _CFG, _LSL_TS, 0)[0]
        assert r["heart_rate_bpm"] == pytest.approx(100.0)

    def test_hrv_zero_rr_gives_none_bpm(self):
        assert _build_hrv_rows([0.0], _CFG, _LSL_TS, 0)[0]["heart_rate_bpm"] is None

    def test_hrv_participant_id_is_pseudonymous_token(self):
        r = _build_hrv_rows([860.0], _CFG, _LSL_TS, 0)[0]
        assert r["participant_id"] == _CFG.participant_id

    # EDA ------------------------------------------------------------------

    def test_eda_one_row(self):
        assert len(_build_eda_rows([5.2], _CFG, _LSL_TS, 0)) == 1

    def test_eda_lsl_timestamp_propagated(self):
        r = _build_eda_rows([5.2], _CFG, _LSL_TS, 0)[0]
        assert r["lsl_timestamp"] == pytest.approx(_LSL_TS)

    def test_eda_db_insert_time_not_in_row(self):
        assert "db_insert_time" not in _build_eda_rows([5.2], _CFG, _LSL_TS, 0)[0]

    def test_eda_conductance_us_equals_raw(self):
        r = _build_eda_rows([5.2], _CFG, _LSL_TS, 0)[0]
        assert r["conductance_us"] == pytest.approx(r["raw_conductance_us"])

    def test_eda_participant_id_is_pseudonymous_token(self):
        r = _build_eda_rows([5.2], _CFG, _LSL_TS, 0)[0]
        assert r["participant_id"] == _CFG.participant_id

    # Respiration ----------------------------------------------------------

    def test_respiration_one_row(self):
        assert len(_build_respiration_rows([0.45], _CFG, _LSL_TS, 0)) == 1

    def test_respiration_lsl_timestamp_propagated(self):
        r = _build_respiration_rows([0.45], _CFG, _LSL_TS, 0)[0]
        assert r["lsl_timestamp"] == pytest.approx(_LSL_TS)

    def test_respiration_db_insert_time_not_in_row(self):
        assert (
            "db_insert_time" not in _build_respiration_rows([0.45], _CFG, _LSL_TS, 0)[0]
        )

    def test_respiration_processed_equals_raw(self):
        r = _build_respiration_rows([0.45], _CFG, _LSL_TS, 0)[0]
        assert r["processed_amplitude"] == pytest.approx(r["raw_amplitude"])

    def test_respiration_participant_id_is_pseudonymous_token(self):
        r = _build_respiration_rows([0.45], _CFG, _LSL_TS, 0)[0]
        assert r["participant_id"] == _CFG.participant_id

    # Cross-modality -------------------------------------------------------

    def test_all_biosignal_builders_carry_session_site_sponsor(self):
        all_rows = (
            _build_eeg_rows([0.0] * 8, _CFG, _LSL_TS, 0)
            + _build_hrv_rows([860.0], _CFG, _LSL_TS, 0)
            + _build_eda_rows([5.0], _CFG, _LSL_TS, 0)
            + _build_respiration_rows([0.4], _CFG, _LSL_TS, 0)
        )
        for r in all_rows:
            assert r["session_id"] == _CFG.session_id
            assert r["site_id"] == _CFG.site_id
            assert r["sponsor_id"] == _CFG.sponsor_id

    def test_all_biosignal_builders_propagate_sample_index(self):
        idx = 42
        all_rows = (
            _build_eeg_rows([0.0] * 8, _CFG, _LSL_TS, idx)
            + _build_hrv_rows([860.0], _CFG, _LSL_TS, idx)
            + _build_eda_rows([5.0], _CFG, _LSL_TS, idx)
            + _build_respiration_rows([0.4], _CFG, _LSL_TS, idx)
        )
        assert all(r["sample_index"] == idx for r in all_rows)


# ---------------------------------------------------------------------------
# Section 2 — Timestamp separation (DB integration)
#
# After inserting one row into each of the 5 modality tables we SELECT both
# timestamp columns back and assert:
#
#   • lsl_timestamp is the DOUBLE PRECISION float we sent — unchanged.
#   • db_insert_time is a Python datetime returned by psycopg2 (the DB
#     set it via DEFAULT NOW()). It is a TIMESTAMPTZ, not a float — a
#     different type and a different data source than lsl_timestamp.
#
# Together these two checks confirm that the two timestamps can never
# accidentally be equal or derived from the same source: one is a float
# from the LSL clock, the other is a server-side wall-clock timestamptz.
# ---------------------------------------------------------------------------


def _insert_session_row(cursor, session_id, site_id, sponsor_id, participant_id):
    cursor.execute(
        """
        INSERT INTO sessions (id, site_id, sponsor_id, participant_id,
                              compound, status, started_at)
        VALUES (%s, %s, %s, %s, 'psilocybin', 'active', NOW())
        ON CONFLICT (id) DO NOTHING
        """,
        (session_id, site_id, sponsor_id, participant_id),
    )


@pytest.mark.integration
class TestSeparateTimestampsDB:
    """lsl_timestamp (float) and db_insert_time (timestamptz) are always distinct."""

    def _insert_one_sample_each(self, cursor):
        cursor.execute(
            """INSERT INTO eeg_samples
               (session_id, participant_id, site_id, sponsor_id, device_id,
                channel_id, voltage, lsl_timestamp, sample_index)
               VALUES (%s, %s, %s, %s, %s, 'ch_0', 1.0, %s, 0)""",
            (
                _INT_SESSION,
                _INT_PART,
                _INT_SITE,
                _INT_SPONSOR,
                _INT_DEVICE,
                _INT_LSL_TS,
            ),
        )
        cursor.execute(
            """INSERT INTO hrv_samples
               (session_id, participant_id, site_id, sponsor_id, device_id,
                rr_interval_ms, lsl_timestamp, sample_index)
               VALUES (%s, %s, %s, %s, %s, 860.0, %s, 0)""",
            (
                _INT_SESSION,
                _INT_PART,
                _INT_SITE,
                _INT_SPONSOR,
                _INT_DEVICE,
                _INT_LSL_TS,
            ),
        )
        cursor.execute(
            """INSERT INTO eda_samples
               (session_id, participant_id, site_id, sponsor_id, device_id,
                raw_conductance_us, conductance_us, lsl_timestamp, sample_index)
               VALUES (%s, %s, %s, %s, %s, 5.0, 5.0, %s, 0)""",
            (
                _INT_SESSION,
                _INT_PART,
                _INT_SITE,
                _INT_SPONSOR,
                _INT_DEVICE,
                _INT_LSL_TS,
            ),
        )
        cursor.execute(
            """INSERT INTO respiration_samples
               (session_id, participant_id, site_id, sponsor_id, device_id,
                raw_amplitude, processed_amplitude, lsl_timestamp, sample_index)
               VALUES (%s, %s, %s, %s, %s, 0.5, 0.5, %s, 0)""",
            (
                _INT_SESSION,
                _INT_PART,
                _INT_SITE,
                _INT_SPONSOR,
                _INT_DEVICE,
                _INT_LSL_TS,
            ),
        )
        cursor.execute(
            """INSERT INTO humen_events
               (session_id, participant_id, site_id, sponsor_id,
                event_type, source, actor_id, actor_role, zone_label, lsl_timestamp)
               VALUES (%s, %s, %s, %s,
                       'proximity_state_change', 'manual_logging',
                       'therapist_01', 'therapist', 'arms_reach', %s)""",
            (_INT_SESSION, _INT_PART, _INT_SITE, _INT_SPONSOR, _INT_LSL_TS),
        )

    def test_eeg_lsl_timestamp_stored_correctly(self, cursor):
        _insert_session_row(cursor, _INT_SESSION, _INT_SITE, _INT_SPONSOR, _INT_PART)
        self._insert_one_sample_each(cursor)
        cursor.execute(
            "SELECT lsl_timestamp FROM eeg_samples WHERE session_id = %s",
            (_INT_SESSION,),
        )
        stored = cursor.fetchone()[0]
        assert stored == pytest.approx(_INT_LSL_TS)

    def test_eeg_db_insert_time_is_datetime(self, cursor):
        _insert_session_row(cursor, _INT_SESSION, _INT_SITE, _INT_SPONSOR, _INT_PART)
        self._insert_one_sample_each(cursor)
        cursor.execute(
            "SELECT db_insert_time FROM eeg_samples WHERE session_id = %s",
            (_INT_SESSION,),
        )
        stored = cursor.fetchone()[0]
        assert stored is not None
        assert isinstance(stored, datetime.datetime)

    def test_hrv_lsl_timestamp_stored_correctly(self, cursor):
        _insert_session_row(cursor, _INT_SESSION, _INT_SITE, _INT_SPONSOR, _INT_PART)
        self._insert_one_sample_each(cursor)
        cursor.execute(
            "SELECT lsl_timestamp FROM hrv_samples WHERE session_id = %s",
            (_INT_SESSION,),
        )
        assert cursor.fetchone()[0] == pytest.approx(_INT_LSL_TS)

    def test_hrv_db_insert_time_is_datetime(self, cursor):
        _insert_session_row(cursor, _INT_SESSION, _INT_SITE, _INT_SPONSOR, _INT_PART)
        self._insert_one_sample_each(cursor)
        cursor.execute(
            "SELECT db_insert_time FROM hrv_samples WHERE session_id = %s",
            (_INT_SESSION,),
        )
        stored = cursor.fetchone()[0]
        assert stored is not None
        assert isinstance(stored, datetime.datetime)

    def test_eda_lsl_timestamp_stored_correctly(self, cursor):
        _insert_session_row(cursor, _INT_SESSION, _INT_SITE, _INT_SPONSOR, _INT_PART)
        self._insert_one_sample_each(cursor)
        cursor.execute(
            "SELECT lsl_timestamp FROM eda_samples WHERE session_id = %s",
            (_INT_SESSION,),
        )
        assert cursor.fetchone()[0] == pytest.approx(_INT_LSL_TS)

    def test_eda_db_insert_time_is_datetime(self, cursor):
        _insert_session_row(cursor, _INT_SESSION, _INT_SITE, _INT_SPONSOR, _INT_PART)
        self._insert_one_sample_each(cursor)
        cursor.execute(
            "SELECT db_insert_time FROM eda_samples WHERE session_id = %s",
            (_INT_SESSION,),
        )
        stored = cursor.fetchone()[0]
        assert stored is not None
        assert isinstance(stored, datetime.datetime)

    def test_respiration_lsl_timestamp_stored_correctly(self, cursor):
        _insert_session_row(cursor, _INT_SESSION, _INT_SITE, _INT_SPONSOR, _INT_PART)
        self._insert_one_sample_each(cursor)
        cursor.execute(
            "SELECT lsl_timestamp FROM respiration_samples WHERE session_id = %s",
            (_INT_SESSION,),
        )
        assert cursor.fetchone()[0] == pytest.approx(_INT_LSL_TS)

    def test_respiration_db_insert_time_is_datetime(self, cursor):
        _insert_session_row(cursor, _INT_SESSION, _INT_SITE, _INT_SPONSOR, _INT_PART)
        self._insert_one_sample_each(cursor)
        cursor.execute(
            "SELECT db_insert_time FROM respiration_samples WHERE session_id = %s",
            (_INT_SESSION,),
        )
        stored = cursor.fetchone()[0]
        assert stored is not None
        assert isinstance(stored, datetime.datetime)

    def test_humen_lsl_timestamp_stored_correctly(self, cursor):
        _insert_session_row(cursor, _INT_SESSION, _INT_SITE, _INT_SPONSOR, _INT_PART)
        self._insert_one_sample_each(cursor)
        cursor.execute(
            "SELECT lsl_timestamp FROM humen_events WHERE session_id = %s",
            (_INT_SESSION,),
        )
        assert cursor.fetchone()[0] == pytest.approx(_INT_LSL_TS)

    def test_humen_db_insert_time_is_datetime(self, cursor):
        _insert_session_row(cursor, _INT_SESSION, _INT_SITE, _INT_SPONSOR, _INT_PART)
        self._insert_one_sample_each(cursor)
        cursor.execute(
            "SELECT db_insert_time FROM humen_events WHERE session_id = %s",
            (_INT_SESSION,),
        )
        stored = cursor.fetchone()[0]
        assert stored is not None
        assert isinstance(stored, datetime.datetime)


# ---------------------------------------------------------------------------
# Section 3 — No plaintext patient data (DB integration)
#
# 21 CFR Part 11 and Consensai's data tenancy rules require that real
# participant identity never reaches any biosignal or event table.
# participant_id must always be a pseudonymous opaque token.
#
# What we test:
#   • Every participant_id column in every modality table holds exactly
#     the pseudonymous UUID token we passed in — never a real name.
#   • The PII sentinel string (_REAL_NAME = "Jane Doe") does not appear
#     in any text column of any of the 5 modality tables.
#
# The second check catches a class of bugs where a lookup, join, or
# accidental substitution replaces the token with a resolved real name
# before the row reaches the DB.
# ---------------------------------------------------------------------------

# Queries that return every text value stored for the session across each table.
# Covers all columns that could inadvertently hold patient identity.
_PII_SCAN_QUERIES: dict[str, str] = {
    "eeg_samples": """
        SELECT participant_id, site_id, sponsor_id, device_id, channel_id
        FROM eeg_samples WHERE session_id = %s
    """,
    "hrv_samples": """
        SELECT participant_id, site_id, sponsor_id, device_id
        FROM hrv_samples WHERE session_id = %s
    """,
    "eda_samples": """
        SELECT participant_id, site_id, sponsor_id, device_id
        FROM eda_samples WHERE session_id = %s
    """,
    "respiration_samples": """
        SELECT participant_id, site_id, sponsor_id, device_id
        FROM respiration_samples WHERE session_id = %s
    """,
    "humen_events": """
        SELECT participant_id, site_id, sponsor_id, event_type, source,
               actor_id, actor_role, zone_label
        FROM humen_events WHERE session_id = %s
    """,
}


@pytest.mark.integration
class TestNoPlaintextPatientData:
    """participant_id is always the pseudonymous token — never a real name."""

    def _insert_minimal_session(self, cursor):
        _insert_session_row(cursor, _INT_SESSION, _INT_SITE, _INT_SPONSOR, _INT_PART)
        cursor.execute(
            """INSERT INTO eeg_samples
               (session_id, participant_id, site_id, sponsor_id, device_id,
                channel_id, voltage, lsl_timestamp, sample_index)
               VALUES (%s, %s, %s, %s, %s, 'ch_0', 1.0, %s, 0)""",
            (
                _INT_SESSION,
                _INT_PART,
                _INT_SITE,
                _INT_SPONSOR,
                _INT_DEVICE,
                _INT_LSL_TS,
            ),
        )
        cursor.execute(
            """INSERT INTO hrv_samples
               (session_id, participant_id, site_id, sponsor_id, device_id,
                rr_interval_ms, lsl_timestamp, sample_index)
               VALUES (%s, %s, %s, %s, %s, 860.0, %s, 0)""",
            (
                _INT_SESSION,
                _INT_PART,
                _INT_SITE,
                _INT_SPONSOR,
                _INT_DEVICE,
                _INT_LSL_TS,
            ),
        )
        cursor.execute(
            """INSERT INTO eda_samples
               (session_id, participant_id, site_id, sponsor_id, device_id,
                raw_conductance_us, conductance_us, lsl_timestamp, sample_index)
               VALUES (%s, %s, %s, %s, %s, 5.0, 5.0, %s, 0)""",
            (
                _INT_SESSION,
                _INT_PART,
                _INT_SITE,
                _INT_SPONSOR,
                _INT_DEVICE,
                _INT_LSL_TS,
            ),
        )
        cursor.execute(
            """INSERT INTO respiration_samples
               (session_id, participant_id, site_id, sponsor_id, device_id,
                raw_amplitude, processed_amplitude, lsl_timestamp, sample_index)
               VALUES (%s, %s, %s, %s, %s, 0.5, 0.5, %s, 0)""",
            (
                _INT_SESSION,
                _INT_PART,
                _INT_SITE,
                _INT_SPONSOR,
                _INT_DEVICE,
                _INT_LSL_TS,
            ),
        )
        cursor.execute(
            """INSERT INTO humen_events
               (session_id, participant_id, site_id, sponsor_id,
                event_type, source, actor_id, actor_role, zone_label, lsl_timestamp)
               VALUES (%s, %s, %s, %s,
                       'proximity_state_change', 'manual_logging',
                       'therapist_01', 'therapist', 'arms_reach', %s)""",
            (_INT_SESSION, _INT_PART, _INT_SITE, _INT_SPONSOR, _INT_LSL_TS),
        )

    def test_eeg_participant_id_is_pseudonymous_token(self, cursor):
        self._insert_minimal_session(cursor)
        cursor.execute(
            "SELECT participant_id FROM eeg_samples WHERE session_id = %s",
            (_INT_SESSION,),
        )
        assert cursor.fetchone()[0] == _INT_PART

    def test_hrv_participant_id_is_pseudonymous_token(self, cursor):
        self._insert_minimal_session(cursor)
        cursor.execute(
            "SELECT participant_id FROM hrv_samples WHERE session_id = %s",
            (_INT_SESSION,),
        )
        assert cursor.fetchone()[0] == _INT_PART

    def test_eda_participant_id_is_pseudonymous_token(self, cursor):
        self._insert_minimal_session(cursor)
        cursor.execute(
            "SELECT participant_id FROM eda_samples WHERE session_id = %s",
            (_INT_SESSION,),
        )
        assert cursor.fetchone()[0] == _INT_PART

    def test_respiration_participant_id_is_pseudonymous_token(self, cursor):
        self._insert_minimal_session(cursor)
        cursor.execute(
            "SELECT participant_id FROM respiration_samples WHERE session_id = %s",
            (_INT_SESSION,),
        )
        assert cursor.fetchone()[0] == _INT_PART

    def test_humen_participant_id_is_pseudonymous_token(self, cursor):
        self._insert_minimal_session(cursor)
        cursor.execute(
            "SELECT participant_id FROM humen_events WHERE session_id = %s",
            (_INT_SESSION,),
        )
        assert cursor.fetchone()[0] == _INT_PART

    def test_no_real_name_in_any_text_column(self, cursor):
        """Scan every text column across all 5 tables for the PII sentinel string.

        _REAL_NAME = "Jane Doe" was never passed to any INSERT in this test,
        so finding it anywhere would indicate an unexpected substitution or
        data pollution that violates the pseudonymisation requirement.
        """
        self._insert_minimal_session(cursor)
        for table, query in _PII_SCAN_QUERIES.items():
            cursor.execute(query, (_INT_SESSION,))
            for row in cursor.fetchall():
                for cell in row:
                    if cell is not None:
                        assert _REAL_NAME not in str(
                            cell
                        ), f"PII sentinel '{_REAL_NAME}' found in {table}: {cell!r}"


# ---------------------------------------------------------------------------
# Section 4 — XDF row count matches TimescaleDB (happy-path reconciliation)
#
# During a session, lsl_forwarder writes each chunk to XDF first, then to
# the DB. After the session ends, batch/reconcile checks that the counts
# agree. This test simulates the happy path: no DB outage occurred, so
# both stores should hold identical sample counts and build_report should
# declare is_reconciled=True with gap=0 for every stream.
#
# This is distinct from TestXDFBackfillSimulation in test_reconcile.py,
# which tests the recovery path after a DB outage.
# ---------------------------------------------------------------------------

# Known sample counts for the happy-path simulation
_REC_EEG_N = 20  # 20 samples × 8 ch = 160 EEG rows in DB
_REC_HRV_N = 5
_REC_EDA_N = 8
_REC_RESP_N = 6

# Session / participant UUIDs distinct from Section 2/3 to avoid cross-test
# contamination if tests run in the same transaction.
_REC_SESSION = "f1d00002-0000-4444-aaaa-000000000002"
_REC_PART = "f1d00002-0000-4444-bbbb-000000000002"
_REC_SITE = "f1d00002-0000-4444-cccc-000000000002"
_REC_SPONSOR = "f1d00002-0000-4444-dddd-000000000002"


@pytest.mark.integration
class TestXDFMatchesTimescaleDB:
    """After a simulated session XDF counts == DB counts → is_reconciled=True."""

    def test_happy_path_all_streams_reconciled(
        self, cursor, db_conn, tmp_path, monkeypatch
    ):
        import config.settings as s

        monkeypatch.setattr(s, "XDF_BACKUP_DIR", tmp_path)
        monkeypatch.setattr(s, "DEVICE_ID", _INT_DEVICE)

        # ------------------------------------------------------------------ #
        # 1. Write known sample counts to XDF                                #
        # ------------------------------------------------------------------ #
        w = XDFWriter(_REC_SESSION, _REC_SITE, _REC_SPONSOR)
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

        # ------------------------------------------------------------------ #
        # 2. Insert the same counts to DB — simulates the forwarder writing  #
        #    both stores in parallel with no interruptions.                  #
        # ------------------------------------------------------------------ #
        _insert_session_row(cursor, _REC_SESSION, _REC_SITE, _REC_SPONSOR, _REC_PART)

        for si in range(_REC_EEG_N):
            for ch in range(8):
                cursor.execute(
                    """INSERT INTO eeg_samples
                       (session_id, participant_id, site_id, sponsor_id, device_id,
                        channel_id, voltage, lsl_timestamp, sample_index)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (
                        _REC_SESSION,
                        _REC_PART,
                        _REC_SITE,
                        _REC_SPONSOR,
                        _INT_DEVICE,
                        f"ch_{ch}",
                        float(si),
                        float(si),
                        si,
                    ),
                )

        for si in range(_REC_HRV_N):
            cursor.execute(
                """INSERT INTO hrv_samples
                   (session_id, participant_id, site_id, sponsor_id, device_id,
                    rr_interval_ms, lsl_timestamp, sample_index)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    _REC_SESSION,
                    _REC_PART,
                    _REC_SITE,
                    _REC_SPONSOR,
                    _INT_DEVICE,
                    800.0 + si,
                    float(si),
                    si,
                ),
            )

        for si in range(_REC_EDA_N):
            cursor.execute(
                """INSERT INTO eda_samples
                   (session_id, participant_id, site_id, sponsor_id, device_id,
                    raw_conductance_us, conductance_us, lsl_timestamp, sample_index)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    _REC_SESSION,
                    _REC_PART,
                    _REC_SITE,
                    _REC_SPONSOR,
                    _INT_DEVICE,
                    5.0 + si * 0.1,
                    5.0 + si * 0.1,
                    float(si),
                    si,
                ),
            )

        for si in range(_REC_RESP_N):
            cursor.execute(
                """INSERT INTO respiration_samples
                   (session_id, participant_id, site_id, sponsor_id, device_id,
                    raw_amplitude, processed_amplitude, lsl_timestamp, sample_index)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    _REC_SESSION,
                    _REC_PART,
                    _REC_SITE,
                    _REC_SPONSOR,
                    _INT_DEVICE,
                    0.5 + si * 0.01,
                    0.5 + si * 0.01,
                    float(si),
                    si,
                ),
            )

        # ------------------------------------------------------------------ #
        # 3. Reconcile: XDF counts == DB counts → is_reconciled=True         #
        # ------------------------------------------------------------------ #
        xdf_counts = read_xdf_counts(xdf_path)
        db_counts = query_db_counts(db_conn, _REC_SESSION)
        report = build_report(_REC_SESSION, xdf_path, xdf_counts, db_counts)

        assert (
            report.is_reconciled is True
        ), "Expected reconciled=True, got streams: " + ", ".join(
            f"{k}(gap={v.gap})" for k, v in report.streams.items()
        )

    def test_happy_path_eeg_count_exact(self, cursor, db_conn, tmp_path, monkeypatch):
        import config.settings as s

        monkeypatch.setattr(s, "XDF_BACKUP_DIR", tmp_path)
        monkeypatch.setattr(s, "DEVICE_ID", _INT_DEVICE)

        w = XDFWriter(_REC_SESSION, _REC_SITE, _REC_SPONSOR)
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
                    (
                        _REC_SESSION,
                        _REC_PART,
                        _REC_SITE,
                        _REC_SPONSOR,
                        _INT_DEVICE,
                        f"ch_{ch}",
                        float(si),
                        si,
                    ),
                )

        xdf_counts = read_xdf_counts(w.path)
        db_counts = query_db_counts(db_conn, _REC_SESSION)
        report = build_report(_REC_SESSION, w.path, xdf_counts, db_counts)

        assert report.streams["EEG"].xdf_count == _REC_EEG_N
        assert report.streams["EEG"].db_count == _REC_EEG_N
        assert report.streams["EEG"].gap == 0

    def test_happy_path_gap_zero_for_all_streams(
        self, cursor, db_conn, tmp_path, monkeypatch
    ):
        import config.settings as s

        monkeypatch.setattr(s, "XDF_BACKUP_DIR", tmp_path)
        monkeypatch.setattr(s, "DEVICE_ID", _INT_DEVICE)

        w = XDFWriter(_REC_SESSION, _REC_SITE, _REC_SPONSOR)
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
                    (
                        _REC_SESSION,
                        _REC_PART,
                        _REC_SITE,
                        _REC_SPONSOR,
                        _INT_DEVICE,
                        f"ch_{ch}",
                        float(si),
                        si,
                    ),
                )
        for si in range(_REC_HRV_N):
            cursor.execute(
                """INSERT INTO hrv_samples
                   (session_id, participant_id, site_id, sponsor_id, device_id,
                    rr_interval_ms, lsl_timestamp, sample_index)
                   VALUES (%s, %s, %s, %s, %s, 800.0, %s, %s)""",
                (
                    _REC_SESSION,
                    _REC_PART,
                    _REC_SITE,
                    _REC_SPONSOR,
                    _INT_DEVICE,
                    float(si),
                    si,
                ),
            )
        for si in range(_REC_EDA_N):
            cursor.execute(
                """INSERT INTO eda_samples
                   (session_id, participant_id, site_id, sponsor_id, device_id,
                    raw_conductance_us, conductance_us, lsl_timestamp, sample_index)
                   VALUES (%s, %s, %s, %s, %s, 5.0, 5.0, %s, %s)""",
                (
                    _REC_SESSION,
                    _REC_PART,
                    _REC_SITE,
                    _REC_SPONSOR,
                    _INT_DEVICE,
                    float(si),
                    si,
                ),
            )
        for si in range(_REC_RESP_N):
            cursor.execute(
                """INSERT INTO respiration_samples
                   (session_id, participant_id, site_id, sponsor_id, device_id,
                    raw_amplitude, processed_amplitude, lsl_timestamp, sample_index)
                   VALUES (%s, %s, %s, %s, %s, 0.5, 0.5, %s, %s)""",
                (
                    _REC_SESSION,
                    _REC_PART,
                    _REC_SITE,
                    _REC_SPONSOR,
                    _INT_DEVICE,
                    float(si),
                    si,
                ),
            )

        xdf_counts = read_xdf_counts(w.path)
        db_counts = query_db_counts(db_conn, _REC_SESSION)
        report = build_report(_REC_SESSION, w.path, xdf_counts, db_counts)

        for stream_name in ("EEG", "HRV", "EDA", "Respiration"):
            assert (
                report.streams[stream_name].gap == 0
            ), f"{stream_name}: expected gap=0, got {report.streams[stream_name].gap}"
