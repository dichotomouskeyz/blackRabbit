"""Unit tests for capture.session_init — no DB required."""

import importlib
import uuid
from unittest.mock import MagicMock, patch

import psycopg2
import pytest

from capture.session_init.constants import VALID_COMPOUNDS, VALID_DOSE_UNITS
from capture.session_init.workflow import create_session
from tests.capture_tests.session_init.support import _COMPOUND, _PART, _SITE, _SPONSOR


class TestCreateSessionUnit:
    def test_workflow_import_does_not_validate_settings(self):
        import capture.session_init.workflow as workflow

        with patch.object(workflow.settings, "validate") as validate:
            importlib.reload(workflow)

        validate.assert_not_called()

    def test_create_session_validates_settings(self):
        import capture.session_init.workflow as workflow

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = MagicMock()

        with (
            patch.object(workflow.settings, "validate") as validate,
            patch("capture.session_init.workflow.psycopg2.connect", return_value=mock_conn),
        ):
            create_session(_COMPOUND, _SITE, _SPONSOR, _PART)

        validate.assert_called_once()

    def test_returns_valid_uuid_string(self):
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = MagicMock()

        with patch("capture.session_init.workflow.psycopg2.connect", return_value=mock_conn):
            sid = create_session(_COMPOUND, _SITE, _SPONSOR, _PART)

        uuid.UUID(sid)

    def test_rollback_called_on_second_execute_failure(self):
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur
        mock_cur.execute.side_effect = [None, psycopg2.OperationalError("db down")]

        with patch("capture.session_init.workflow.psycopg2.connect", return_value=mock_conn):
            with pytest.raises(psycopg2.OperationalError):
                create_session(_COMPOUND, _SITE, _SPONSOR, _PART)

        mock_conn.rollback.assert_called_once()

    def test_commit_not_called_after_rollback(self):
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur
        mock_cur.execute.side_effect = [None, psycopg2.OperationalError("db down")]

        with patch("capture.session_init.workflow.psycopg2.connect", return_value=mock_conn):
            with pytest.raises(psycopg2.OperationalError):
                create_session(_COMPOUND, _SITE, _SPONSOR, _PART)

        mock_conn.commit.assert_not_called()

    def test_rollback_on_metadata_insert_failure(self):
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur
        mock_cur.execute.side_effect = [
            None,
            None,
            psycopg2.IntegrityError("constraint violation"),
        ]

        with patch("capture.session_init.workflow.psycopg2.connect", return_value=mock_conn):
            with pytest.raises(psycopg2.IntegrityError):
                create_session(_COMPOUND, _SITE, _SPONSOR, _PART)

        mock_conn.rollback.assert_called_once()
        mock_conn.commit.assert_not_called()

    def test_execute_called_ten_times_on_success(self):
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur

        with patch("capture.session_init.workflow.psycopg2.connect", return_value=mock_conn):
            create_session(_COMPOUND, _SITE, _SPONSOR, _PART)

        assert mock_cur.execute.call_count == 10

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
