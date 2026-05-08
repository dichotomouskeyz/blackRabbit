"""Tests for capture/session_init.py.

Section 1 — Unit tests (no DB)
  Verify return-value shape and rollback behavior using a mocked connection.

Section 2 — Integration tests (real test DB)
  Verify the committed row, column values, optional-field handling, and the
  audit trigger firing on INSERT into sessions.

Section 3 — Signal metadata integration tests (real test DB)
  Verify that create_session writes exactly 4 rows to session_signal_metadata
  in the correct order with the correct values.

Run:
    pytest tests/test_session_init.py -m "not integration" -v  # unit only
    pytest tests/test_session_init.py -m integration -v        # DB tests
"""

import uuid
from unittest.mock import MagicMock, patch

import psycopg2
import pytest

import capture.session_init as session_init
from capture.lsl_forwarder import SessionConfig, _verify_session_ready
from capture.session_init import VALID_COMPOUNDS, VALID_DOSE_UNITS, create_session

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

_SITE = "f1d00007-0000-4444-cccc-000000000001"
_SPONSOR = "f1d00007-0000-4444-dddd-000000000001"
_PART = "f1d00007-0000-4444-bbbb-000000000001"
_COMPOUND = "psilocybin"


# ---------------------------------------------------------------------------
# DB helpers for integration tests
# ---------------------------------------------------------------------------


def _conn(db_url: str) -> psycopg2.extensions.connection:
    c = psycopg2.connect(db_url)
    c.autocommit = True
    return c


def _query_session(db_url: str, session_id: str) -> tuple | None:
    """Return (site_id, sponsor_id, participant_id, compound, compound_dose,
    compound_dose_unit, protocol_arm, room_id, status, started_at) or None."""
    conn = _conn(db_url)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT site_id, sponsor_id, participant_id, compound,
               compound_dose, compound_dose_unit, protocol_arm, room_id,
               status, started_at
        FROM sessions WHERE id = %s
        """,
        (session_id,),
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row


def _query_audit(db_url: str, session_id: str) -> list[tuple]:
    """Return list of (event_type, table_name) from audit_events for session."""
    conn = _conn(db_url)
    cur = conn.cursor()
    cur.execute(
        "SELECT event_type, table_name FROM audit_events WHERE session_id = %s ORDER BY id",
        (session_id,),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def _query_metadata(db_url: str, session_id: str) -> list[dict]:
    """Return all session_signal_metadata rows for session_id, ordered by modality."""
    _ORDER = ("eeg", "hrv", "eda", "respiration")
    conn = _conn(db_url)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT modality,
               power_line_frequency, sample_rate_hz,
               eeg_reference, sampling_frequency, eeg_channel_count,
               cap_manufacturer, cap_manufacturer_model_name,
               hrv_signal_source, beat_detection_algorithm, beat_detection_version,
               electrode_placement, electrode_type, skin_prep,
               eda_signal_source, eda_range_min_us, eda_range_max_us,
               respiration_source, is_derived, respiration_unit,
               site_id, sponsor_id, participant_id, device_id
        FROM session_signal_metadata
        WHERE session_id = %s
        ORDER BY CASE modality
            WHEN 'eeg' THEN 0 WHEN 'hrv' THEN 1
            WHEN 'eda' THEN 2 WHEN 'respiration' THEN 3
        END
        """,
        (session_id,),
    )
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return rows


def _cleanup(db_url: str, *session_ids: str) -> None:
    conn = _conn(db_url)
    cur = conn.cursor()
    for sid in session_ids:
        cur.execute("DELETE FROM session_signal_metadata WHERE session_id = %s", (sid,))
        cur.execute("DELETE FROM audit_events WHERE session_id = %s", (sid,))
        cur.execute("DELETE FROM sessions WHERE id = %s", (sid,))
    cur.close()
    conn.close()


def _call(db_url: str, **kwargs) -> str:
    """Call create_session with the test DB URL and default args."""
    defaults = dict(
        compound=_COMPOUND,
        site_id=_SITE,
        sponsor_id=_SPONSOR,
        participant_id=_PART,
    )
    defaults.update(kwargs)
    with patch.object(session_init.settings, "DATABASE_URL", db_url):
        return create_session(**defaults)


# ===========================================================================
# Section 1 — Unit tests (no DB)
# ===========================================================================


class TestCreateSessionUnit:

    def test_returns_valid_uuid_string(self):
        """create_session returns a well-formed UUID string."""
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = MagicMock()

        with patch("capture.session_init.psycopg2.connect", return_value=mock_conn):
            sid = create_session(_COMPOUND, _SITE, _SPONSOR, _PART)

        uuid.UUID(sid)  # raises ValueError if malformed

    def test_rollback_called_on_second_execute_failure(self):
        """If the status UPDATE raises, rollback is called and exception propagates."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur
        # INSERT succeeds; UPDATE raises
        mock_cur.execute.side_effect = [None, psycopg2.OperationalError("db down")]

        with patch("capture.session_init.psycopg2.connect", return_value=mock_conn):
            with pytest.raises(psycopg2.OperationalError):
                create_session(_COMPOUND, _SITE, _SPONSOR, _PART)

        mock_conn.rollback.assert_called_once()

    def test_commit_not_called_after_rollback(self):
        """On failure the transaction is rolled back, not committed."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur
        mock_cur.execute.side_effect = [None, psycopg2.OperationalError("db down")]

        with patch("capture.session_init.psycopg2.connect", return_value=mock_conn):
            with pytest.raises(psycopg2.OperationalError):
                create_session(_COMPOUND, _SITE, _SPONSOR, _PART)

        mock_conn.commit.assert_not_called()

    def test_rollback_on_metadata_insert_failure(self):
        """If a metadata INSERT raises, rollback is called — sessions row must not be committed."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur
        # sessions INSERT, status UPDATE succeed; first metadata INSERT raises
        mock_cur.execute.side_effect = [
            None,  # INSERT sessions
            None,  # UPDATE status
            psycopg2.IntegrityError("constraint violation"),  # first metadata row
        ]

        with patch("capture.session_init.psycopg2.connect", return_value=mock_conn):
            with pytest.raises(psycopg2.IntegrityError):
                create_session(_COMPOUND, _SITE, _SPONSOR, _PART)

        mock_conn.rollback.assert_called_once()
        mock_conn.commit.assert_not_called()

    def test_execute_called_six_times_on_success(self):
        """Exactly 6 execute calls: INSERT sessions, UPDATE status, 4 × metadata INSERT."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur

        with patch("capture.session_init.psycopg2.connect", return_value=mock_conn):
            create_session(_COMPOUND, _SITE, _SPONSOR, _PART)

        assert mock_cur.execute.call_count == 6

    def test_valid_compounds_matches_compound_reference(self):
        assert set(VALID_COMPOUNDS) == {
            "psilocybin",
            "psilocin",
            "lsd",
            "dmt",
            "5meo_dmt",
            "ibogaine",
            "ibogaine_hcl",
            "mdma",
        }

    def test_valid_dose_units_covers_all_forms(self):
        for unit in ("mg", "ug", "µg", "mg/kg", "ug/kg", "µg/kg"):
            assert unit in VALID_DOSE_UNITS


# ===========================================================================
# Section 2 — Integration tests (real test DB)
# ===========================================================================


@pytest.mark.integration
class TestCreateSessionDB:

    def test_row_exists_after_create(self, db_url):
        """create_session persists a row to sessions."""
        sid = _call(db_url)
        try:
            row = _query_session(db_url, sid)
            assert row is not None
        finally:
            _cleanup(db_url, sid)

    def test_status_is_active(self, db_url):
        """Final status is 'active', not 'initializing'."""
        sid = _call(db_url)
        try:
            row = _query_session(db_url, sid)
            assert str(row[8]) == "active"
        finally:
            _cleanup(db_url, sid)

    def test_required_columns_stored_correctly(self, db_url):
        """site_id, sponsor_id, participant_id, compound all round-trip unchanged."""
        sid = _call(db_url)
        try:
            site_id, sponsor_id, participant_id, compound = _query_session(db_url, sid)[
                :4
            ]
            assert str(site_id) == _SITE
            assert str(sponsor_id) == _SPONSOR
            assert str(participant_id) == _PART
            assert compound == _COMPOUND
        finally:
            _cleanup(db_url, sid)

    def test_started_at_is_set(self, db_url):
        """started_at is populated — required for session duration accounting."""
        sid = _call(db_url)
        try:
            started_at = _query_session(db_url, sid)[9]
            assert started_at is not None
        finally:
            _cleanup(db_url, sid)

    def test_optional_columns_null_by_default(self, db_url):
        """compound_dose, compound_dose_unit, protocol_arm, room_id are NULL when omitted."""
        sid = _call(db_url)
        try:
            row = _query_session(db_url, sid)
            compound_dose, compound_dose_unit, protocol_arm, room_id = row[4:8]
            assert compound_dose is None
            assert compound_dose_unit is None
            assert protocol_arm is None
            assert room_id is None
        finally:
            _cleanup(db_url, sid)

    def test_optional_columns_populated_when_provided(self, db_url):
        """All optional fields stored correctly when passed."""
        room = "f1d00007-0000-4444-eeee-000000000001"
        sid = _call(
            db_url,
            compound_dose=25.0,
            compound_dose_unit="mg",
            protocol_arm="high_dose_25mg",
            room_id=room,
        )
        try:
            row = _query_session(db_url, sid)
            compound_dose, compound_dose_unit, protocol_arm, room_id = row[4:8]
            assert compound_dose == pytest.approx(25.0)
            assert compound_dose_unit == "mg"
            assert protocol_arm == "high_dose_25mg"
            assert str(room_id) == room
        finally:
            _cleanup(db_url, sid)

    def test_audit_insert_event_fired(self, db_url):
        """INSERT triggers fire: 1 for sessions + 4 for session_signal_metadata."""
        sid = _call(db_url)
        try:
            audit = _query_audit(db_url, sid)
            # 1 sessions INSERT + 4 signal metadata INSERTs
            assert len(audit) == 5
            tables = [r[1] for r in audit]
            assert tables.count("sessions") == 1
            assert tables.count("session_signal_metadata") == 4
            assert all(r[0] == "INSERT" for r in audit)
        finally:
            _cleanup(db_url, sid)

    def test_watermark_trigger_silent_on_activate(self, db_url):
        """The initializing → active UPDATE must not write any watermark event."""
        sid = _call(db_url)
        try:
            event_types = [r[0] for r in _query_audit(db_url, sid)]
            assert "watermark_verified" not in event_types
            assert "watermark_failed" not in event_types
        finally:
            _cleanup(db_url, sid)

    def test_unique_session_id_per_call(self, db_url):
        """Successive calls produce distinct UUIDs."""
        sid1 = _call(db_url)
        sid2 = _call(db_url)
        try:
            assert sid1 != sid2
        finally:
            _cleanup(db_url, sid1, sid2)

    def test_all_compounds_stored_correctly(self, db_url):
        """All compound_reference IDs round-trip through the sessions table."""
        for compound in ("psilocybin", "lsd", "ibogaine", "ibogaine_hcl", "mdma"):
            sid = _call(db_url, compound=compound)
            try:
                row = _query_session(db_url, sid)
                assert row[3] == compound
            finally:
                _cleanup(db_url, sid)


# ===========================================================================
# Section 3 — Signal metadata integration tests
# ===========================================================================


@pytest.mark.integration
class TestSignalMetadataDB:

    def test_four_metadata_rows_created(self, db_url):
        """create_session writes exactly 4 rows to session_signal_metadata."""
        sid = _call(db_url)
        try:
            rows = _query_metadata(db_url, sid)
            assert len(rows) == 4
        finally:
            _cleanup(db_url, sid)

    def test_modalities_in_canonical_order(self, db_url):
        """Rows cover all four modalities: eeg, hrv, eda, respiration."""
        sid = _call(db_url)
        try:
            rows = _query_metadata(db_url, sid)
            modalities = [r["modality"] for r in rows]
            assert modalities == ["eeg", "hrv", "eda", "respiration"]
        finally:
            _cleanup(db_url, sid)

    def test_tenancy_columns_match_session(self, db_url):
        """site_id, sponsor_id, participant_id identical on all 4 metadata rows."""
        sid = _call(db_url)
        try:
            rows = _query_metadata(db_url, sid)
            for row in rows:
                assert str(row["site_id"]) == _SITE
                assert str(row["sponsor_id"]) == _SPONSOR
                assert str(row["participant_id"]) == _PART
        finally:
            _cleanup(db_url, sid)

    def test_eeg_row_fields(self, db_url):
        """EEG metadata row carries eeg_reference, sampling_frequency, channel_count."""
        sid = _call(db_url)
        try:
            eeg = _query_metadata(db_url, sid)[0]
            assert eeg["modality"] == "eeg"
            assert eeg["eeg_reference"] == session_init.settings.EEG_REFERENCE
            assert eeg["sampling_frequency"] == pytest.approx(
                float(session_init.settings.SAMPLE_RATE_EEG)
            )
            assert eeg["eeg_channel_count"] == session_init.settings.EEG_CHANNEL_COUNT
            assert eeg["power_line_frequency"] == pytest.approx(
                session_init.settings.POWER_LINE_FREQUENCY
            )
        finally:
            _cleanup(db_url, sid)

    def test_hrv_row_fields(self, db_url):
        """HRV metadata row carries hrv_signal_source and sample_rate_hz."""
        sid = _call(db_url)
        try:
            hrv = _query_metadata(db_url, sid)[1]
            assert hrv["modality"] == "hrv"
            assert hrv["hrv_signal_source"] == session_init.settings.HRV_SIGNAL_SOURCE
            assert hrv["sample_rate_hz"] == pytest.approx(
                float(session_init.settings.SAMPLE_RATE_HRV)
            )
        finally:
            _cleanup(db_url, sid)

    def test_eda_row_fields(self, db_url):
        """EDA metadata row carries eda_signal_source and sample_rate_hz."""
        sid = _call(db_url)
        try:
            eda = _query_metadata(db_url, sid)[2]
            assert eda["modality"] == "eda"
            assert eda["eda_signal_source"] == session_init.settings.EDA_SIGNAL_SOURCE
            assert eda["sample_rate_hz"] == pytest.approx(
                float(session_init.settings.SAMPLE_RATE_EDA)
            )
        finally:
            _cleanup(db_url, sid)

    def test_respiration_row_fields(self, db_url):
        """Respiration metadata row carries respiration_source and is_derived."""
        sid = _call(db_url)
        try:
            resp = _query_metadata(db_url, sid)[3]
            assert resp["modality"] == "respiration"
            assert (
                resp["respiration_source"] == session_init.settings.RESPIRATION_SOURCE
            )
            assert resp["is_derived"] == (
                session_init.settings.RESPIRATION_SOURCE == "rsa_derived"
            )
            assert resp["sample_rate_hz"] == pytest.approx(
                float(session_init.settings.SAMPLE_RATE_RESPIRATION)
            )
        finally:
            _cleanup(db_url, sid)

    def test_eda_electrode_args_stored(self, db_url):
        """CLI electrode args are written to the eda metadata row."""
        sid = _call(
            db_url,
            electrode_placement="palmar",
            electrode_type="ag_agcl",
            skin_prep="cleaned",
        )
        try:
            eda = _query_metadata(db_url, sid)[2]
            assert eda["electrode_placement"] == "palmar"
            assert eda["electrode_type"] == "ag_agcl"
            assert eda["skin_prep"] == "cleaned"
        finally:
            _cleanup(db_url, sid)

    def test_eda_electrode_args_null_by_default(self, db_url):
        """Electrode args are NULL when not provided."""
        sid = _call(db_url)
        try:
            eda = _query_metadata(db_url, sid)[2]
            assert eda["electrode_placement"] is None
            assert eda["electrode_type"] is None
            assert eda["skin_prep"] is None
        finally:
            _cleanup(db_url, sid)

    def test_metadata_rolled_back_with_session_on_failure(self):
        """If any metadata insert raises, the entire transaction is rolled back."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur
        # sessions INSERT + status UPDATE succeed; second metadata INSERT (hrv) raises
        mock_cur.execute.side_effect = [
            None,  # INSERT sessions
            None,  # UPDATE status
            None,  # eeg metadata
            psycopg2.IntegrityError("hrv constraint"),  # hrv metadata
        ]

        with patch("capture.session_init.psycopg2.connect", return_value=mock_conn):
            with pytest.raises(psycopg2.IntegrityError):
                create_session(_COMPOUND, _SITE, _SPONSOR, _PART)

        mock_conn.rollback.assert_called_once()
        mock_conn.commit.assert_not_called()


# ===========================================================================
# Section 4 — _verify_session_ready integration tests
# ===========================================================================

_VFY_SITE = "f1d00008-0000-4444-cccc-000000000001"
_VFY_SPONSOR = "f1d00008-0000-4444-dddd-000000000001"
_VFY_PART = "f1d00008-0000-4444-bbbb-000000000001"


def _vfy_cfg(session_id: str) -> SessionConfig:
    return SessionConfig(
        session_id=session_id,
        participant_id=_VFY_PART,
        site_id=_VFY_SITE,
        sponsor_id=_VFY_SPONSOR,
    )


@pytest.mark.integration
class TestVerifySessionReady:

    def test_passes_after_session_init(self, db_url):
        """Happy path: session_init creates all 5 rows, verify passes without raising."""
        sid = _call(
            db_url, site_id=_VFY_SITE, sponsor_id=_VFY_SPONSOR, participant_id=_VFY_PART
        )
        try:
            cfg = _vfy_cfg(sid)
            with patch("capture.lsl_forwarder.settings.DATABASE_URL", db_url):
                _verify_session_ready(cfg)  # must not raise
        finally:
            _cleanup(db_url, sid)

    def test_raises_if_session_missing(self, db_url):
        """Raises RuntimeError when the session_id has no sessions row."""
        ghost_id = str(uuid.uuid4())
        cfg = _vfy_cfg(ghost_id)
        with patch("capture.lsl_forwarder.settings.DATABASE_URL", db_url):
            with pytest.raises(RuntimeError, match="not found"):
                _verify_session_ready(cfg)

    def test_raises_if_status_not_active(self, db_url):
        """Raises RuntimeError when session exists but status is not 'active'."""
        sid = _call(
            db_url, site_id=_VFY_SITE, sponsor_id=_VFY_SPONSOR, participant_id=_VFY_PART
        )
        try:
            conn = _conn(db_url)
            cur = conn.cursor()
            cur.execute("UPDATE sessions SET status = 'closing' WHERE id = %s", (sid,))
            conn.commit()
            cur.close()
            conn.close()

            cfg = _vfy_cfg(sid)
            with patch("capture.lsl_forwarder.settings.DATABASE_URL", db_url):
                with pytest.raises(RuntimeError, match="status.*closing"):
                    _verify_session_ready(cfg)
        finally:
            _cleanup(db_url, sid)

    def test_raises_if_metadata_rows_missing(self, db_url):
        """Raises RuntimeError when signal metadata rows are absent."""
        sid = _call(
            db_url, site_id=_VFY_SITE, sponsor_id=_VFY_SPONSOR, participant_id=_VFY_PART
        )
        try:
            conn = _conn(db_url)
            cur = conn.cursor()
            cur.execute(
                "DELETE FROM session_signal_metadata WHERE session_id = %s AND modality IN ('hrv', 'eda')",
                (sid,),
            )
            conn.commit()
            cur.close()
            conn.close()

            cfg = _vfy_cfg(sid)
            with patch("capture.lsl_forwarder.settings.DATABASE_URL", db_url):
                with pytest.raises(RuntimeError, match="missing signal metadata"):
                    _verify_session_ready(cfg)
        finally:
            _cleanup(db_url, sid)

    def test_error_message_names_missing_modalities(self, db_url):
        """The RuntimeError message lists exactly which modalities are absent."""
        sid = _call(
            db_url, site_id=_VFY_SITE, sponsor_id=_VFY_SPONSOR, participant_id=_VFY_PART
        )
        try:
            conn = _conn(db_url)
            cur = conn.cursor()
            cur.execute(
                "DELETE FROM session_signal_metadata WHERE session_id = %s AND modality = 'respiration'",
                (sid,),
            )
            conn.commit()
            cur.close()
            conn.close()

            cfg = _vfy_cfg(sid)
            with patch("capture.lsl_forwarder.settings.DATABASE_URL", db_url):
                with pytest.raises(RuntimeError, match="respiration"):
                    _verify_session_ready(cfg)
        finally:
            _cleanup(db_url, sid)
