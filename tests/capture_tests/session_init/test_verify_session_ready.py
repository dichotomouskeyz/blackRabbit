"""Integration tests for _verify_session_ready."""

import uuid
from unittest.mock import patch

import pytest

from capture.forwarder import SessionConfig, _verify_session_ready
from tests.capture_tests.session_init.support import (
    _call,
    _cleanup,
    _conn,
)

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
        sid = _call(db_url, site_id=_VFY_SITE, sponsor_id=_VFY_SPONSOR, participant_id=_VFY_PART)
        try:
            cfg = _vfy_cfg(sid)
            with patch("capture.forwarder.settings.DATABASE_URL", db_url):
                _verify_session_ready(cfg)
        finally:
            _cleanup(db_url, sid)

    def test_raises_if_session_missing(self, db_url):
        ghost_id = str(uuid.uuid4())
        cfg = _vfy_cfg(ghost_id)
        with patch("capture.forwarder.settings.DATABASE_URL", db_url):
            with pytest.raises(RuntimeError, match="not found"):
                _verify_session_ready(cfg)

    def test_raises_if_status_not_active(self, db_url):
        sid = _call(db_url, site_id=_VFY_SITE, sponsor_id=_VFY_SPONSOR, participant_id=_VFY_PART)
        try:
            conn = _conn(db_url)
            cur = conn.cursor()
            cur.execute("UPDATE sessions SET status = 'closing' WHERE id = %s", (sid,))
            conn.commit()
            cur.close()
            conn.close()

            cfg = _vfy_cfg(sid)
            with patch("capture.forwarder.settings.DATABASE_URL", db_url):
                with pytest.raises(RuntimeError, match="status.*closing"):
                    _verify_session_ready(cfg)
        finally:
            _cleanup(db_url, sid)

    def test_raises_if_metadata_rows_missing(self, db_url):
        sid = _call(db_url, site_id=_VFY_SITE, sponsor_id=_VFY_SPONSOR, participant_id=_VFY_PART)
        try:
            conn = _conn(db_url)
            cur = conn.cursor()
            cur.execute(
                "DELETE FROM session_signal_metadata"
                " WHERE session_id = %s AND modality IN ('hrv', 'eda')",
                (sid,),
            )
            conn.commit()
            cur.close()
            conn.close()

            cfg = _vfy_cfg(sid)
            with patch("capture.forwarder.settings.DATABASE_URL", db_url):
                with pytest.raises(RuntimeError, match="missing signal metadata"):
                    _verify_session_ready(cfg)
        finally:
            _cleanup(db_url, sid)

    def test_error_message_names_missing_modalities(self, db_url):
        sid = _call(db_url, site_id=_VFY_SITE, sponsor_id=_VFY_SPONSOR, participant_id=_VFY_PART)
        try:
            conn = _conn(db_url)
            cur = conn.cursor()
            cur.execute(
                "DELETE FROM session_signal_metadata"
                " WHERE session_id = %s AND modality = 'respiration'",
                (sid,),
            )
            conn.commit()
            cur.close()
            conn.close()

            cfg = _vfy_cfg(sid)
            with patch("capture.forwarder.settings.DATABASE_URL", db_url):
                with pytest.raises(RuntimeError, match="respiration"):
                    _verify_session_ready(cfg)
        finally:
            _cleanup(db_url, sid)
