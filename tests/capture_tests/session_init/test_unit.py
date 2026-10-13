"""Spec-driven unit tests for session_init (session-init.md R-001..R-009).

Phase 2 — `create_session` validation + private row builders.
Assertions derive from the spec text only.

WIRING NOTES (Phase D findings, reported — not corrected):
- `create_session` performs NO pre-DB validation of compound / participant_id /
  compound_dose_unit and exposes no `db_factory` seam. The spec (R-002/R-003/R-004)
  states these raise `ValueError` *before* opening a DB connection. The tests below
  are written to the spec, so they fail against the current implementation — that
  failure is the spec-vs-implementation finding.
- R-001 ("returns a UUID v4") is marked [unit] in the spec but requires a live DB
  because there is no injectable connection; it is run under @pytest.mark.integration.
"""

import uuid

import pytest

import config.settings as settings
from capture.session_init import (
    VALID_COMPOUNDS,
    VALID_DOSE_UNITS,
    create_session,
)
from capture.session_init.metadata import _build_metadata_rows
from capture.session_init.workflow import _build_schema_version_row
from tests.capture_tests.session_init.support import (
    PARTICIPANT_ID,
    SITE_ID,
    SPONSOR_ID,
    VALID_COMPOUND,
)


class _FakeCursor:
    def execute(self, *args, **kwargs):
        return None

    def fetchone(self):
        return ("x",)


def _metadata_rows(**over):
    kwargs = dict(
        session_id=str(uuid.uuid4()),
        site_id=SITE_ID,
        sponsor_id=SPONSOR_ID,
        participant_id=PARTICIPANT_ID,
        capture_source="simulated",
        eeg_sensor_form=None,
        eeg_electrode_system=None,
        eeg_electrode_type=None,
        hrv_electrode_placement=None,
        hrv_electrode_type=None,
        eda_electrode_placement=None,
        eda_electrode_type=None,
        eda_skin_prep=None,
    )
    kwargs.update(over)
    return _build_metadata_rows(**kwargs)


class TestCreateSessionValidation:
    """session-init.md — create_session validation.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    @pytest.mark.integration
    def test_r001_returns_uuid_v4(self):
        result = create_session(
            compound=VALID_COMPOUND,
            site_id=SITE_ID,
            sponsor_id=SPONSOR_ID,
            participant_id=PARTICIPANT_ID,
        )
        assert uuid.UUID(result).version == 4

    def test_r002_invalid_compound_raises_before_db(self):
        with pytest.raises(ValueError):
            create_session(
                compound="definitely_not_a_compound",
                site_id=SITE_ID,
                sponsor_id=SPONSOR_ID,
                participant_id=PARTICIPANT_ID,
            )

    def test_r003_invalid_participant_uuid_raises_before_db(self):
        with pytest.raises(ValueError):
            create_session(
                compound=VALID_COMPOUND,
                site_id=SITE_ID,
                sponsor_id=SPONSOR_ID,
                participant_id="not-a-uuid",
            )

    def test_r004_invalid_dose_unit_raises(self):
        with pytest.raises(ValueError):
            create_session(
                compound=VALID_COMPOUND,
                site_id=SITE_ID,
                sponsor_id=SPONSOR_ID,
                participant_id=PARTICIPANT_ID,
                compound_dose_unit="furlongs",
            )

    def test_compounds_and_units_are_exported(self):
        assert VALID_COMPOUND in VALID_COMPOUNDS
        assert len(VALID_DOSE_UNITS) > 0


class TestBuildMetadataRows:
    """session-init.md — `_build_metadata_rows`.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    def test_r005_exactly_four_modality_rows(self):
        rows = _metadata_rows()
        modalities = {r["modality"] for r in rows}
        assert modalities == {"eeg", "hrv", "eda", "respiration"}
        assert len(rows) == 4

    def test_r006_tenancy_fields_unchanged(self):
        sid = str(uuid.uuid4())
        rows = _metadata_rows(session_id=sid)
        for row in rows:
            assert row["session_id"] == sid
            assert row["site_id"] == SITE_ID
            assert row["sponsor_id"] == SPONSOR_ID
            assert row["participant_id"] == PARTICIPANT_ID

    def test_r007_eda_fields_passthrough_none(self):
        rows = _metadata_rows(
            eda_electrode_placement=None,
            eda_electrode_type=None,
            eda_skin_prep=None,
        )
        eda = next(r for r in rows if r["modality"] == "eda")
        assert eda["eda_electrode_placement"] is None
        assert eda["eda_electrode_type"] is None
        assert eda["eda_skin_prep"] is None

    def test_r007_eda_fields_passthrough_values(self):
        rows = _metadata_rows(
            eda_electrode_placement="palmar",
            eda_electrode_type="ag_agcl",
            eda_skin_prep="cleaned",
        )
        eda = next(r for r in rows if r["modality"] == "eda")
        assert eda["eda_electrode_placement"] == "palmar"
        assert eda["eda_electrode_type"] == "ag_agcl"
        assert eda["eda_skin_prep"] == "cleaned"

    def test_r008_respiration_is_derived_from_settings(self, monkeypatch):
        monkeypatch.setattr(settings, "RESPIRATION_SOURCE", "rsa_derived", raising=False)
        resp = next(r for r in _metadata_rows() if r["modality"] == "respiration")
        assert resp["is_derived"] is True

        monkeypatch.setattr(settings, "RESPIRATION_SOURCE", "belt_direct", raising=False)
        resp = next(r for r in _metadata_rows() if r["modality"] == "respiration")
        assert resp["is_derived"] is False


class TestBuildSchemaVersionRow:
    """session-init.md — `_build_schema_version_row`.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    def test_r009_includes_all_provenance_fields(self):
        row = _build_schema_version_row(
            _FakeCursor(),
            str(uuid.uuid4()),
            SITE_ID,
            SPONSOR_ID,
        )
        for field in (
            "alembic_version",
            "app_version",
            "python_version",
            "postgres_version",
            "timescaledb_version",
            "pgvector_version",
        ):
            assert field in row
