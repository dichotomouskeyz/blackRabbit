"""Integration tests for capture.session_init — real test DB."""

import pytest

from tests.capture_tests.session_init.support import (
    _COMPOUND,
    _PART,
    _SITE,
    _SPONSOR,
    _call,
    _cleanup,
    _query_audit,
    _query_session,
)


@pytest.mark.integration
class TestCreateSessionDB:
    def test_row_exists_after_create(self, db_url):
        sid = _call(db_url)
        try:
            row = _query_session(db_url, sid)
            assert row is not None
        finally:
            _cleanup(db_url, sid)

    def test_status_is_active(self, db_url):
        sid = _call(db_url)
        try:
            row = _query_session(db_url, sid)
            assert str(row[9]) == "active"
        finally:
            _cleanup(db_url, sid)

    def test_required_columns_stored_correctly(self, db_url):
        sid = _call(db_url)
        try:
            (
                site_id,
                sponsor_id,
                participant_id,
                capture_mode,
                compound,
            ) = _query_session(db_url, sid)[:5]
            assert str(site_id) == _SITE
            assert str(sponsor_id) == _SPONSOR
            assert str(participant_id) == _PART
            assert capture_mode == "simulated"
            assert compound == _COMPOUND
        finally:
            _cleanup(db_url, sid)

    def test_started_at_is_set(self, db_url):
        sid = _call(db_url)
        try:
            started_at = _query_session(db_url, sid)[10]
            assert started_at is not None
        finally:
            _cleanup(db_url, sid)

    def test_optional_columns_null_by_default(self, db_url):
        sid = _call(db_url)
        try:
            row = _query_session(db_url, sid)
            compound_dose, compound_dose_unit, protocol_arm, room_id = row[5:9]
            assert compound_dose is None
            assert compound_dose_unit is None
            assert protocol_arm is None
            assert room_id is None
        finally:
            _cleanup(db_url, sid)

    def test_optional_columns_populated_when_provided(self, db_url):
        room = "f1d00007-0000-4444-eeee-000000000001"
        sid = _call(
            db_url,
            capture_mode="hardware",
            compound_dose=25.0,
            compound_dose_unit="mg",
            protocol_arm="high_dose_25mg",
            room_id=room,
        )
        try:
            row = _query_session(db_url, sid)
            compound_dose, compound_dose_unit, protocol_arm, room_id = row[5:9]
            assert compound_dose == pytest.approx(25.0)
            assert compound_dose_unit == "mg"
            assert protocol_arm == "high_dose_25mg"
            assert str(room_id) == room
        finally:
            _cleanup(db_url, sid)

    def test_capture_mode_persisted_when_provided(self, db_url):
        sid = _call(db_url, capture_mode="hardware")
        try:
            row = _query_session(db_url, sid)
            assert row[3] == "hardware"
        finally:
            _cleanup(db_url, sid)

    def test_audit_insert_event_fired(self, db_url):
        sid = _call(db_url)
        try:
            audit = _query_audit(db_url, sid)
            assert len(audit) == 6
            tables = [r[1] for r in audit]
            assert tables.count("sessions") == 2
            assert tables.count("session_signal_metadata") == 4
            assert [r[0] for r in audit].count("INSERT") == 5
            assert ("session_status_transition", "sessions") in audit
        finally:
            _cleanup(db_url, sid)

    def test_watermark_trigger_silent_on_activate(self, db_url):
        sid = _call(db_url)
        try:
            event_types = [r[0] for r in _query_audit(db_url, sid)]
            assert "session_status_transition" in event_types
            assert "watermark_verified" not in event_types
            assert "watermark_failed" not in event_types
        finally:
            _cleanup(db_url, sid)

    def test_unique_session_id_per_call(self, db_url):
        sid1 = _call(db_url)
        sid2 = _call(db_url)
        try:
            assert sid1 != sid2
        finally:
            _cleanup(db_url, sid1, sid2)

    def test_all_compounds_stored_correctly(self, db_url):
        for compound in ("psilocybin", "lsd", "ibogaine", "ibogaine_hcl", "mdma"):
            sid = _call(db_url, compound=compound)
            try:
                row = _query_session(db_url, sid)
                assert row[4] == compound
            finally:
                _cleanup(db_url, sid)
