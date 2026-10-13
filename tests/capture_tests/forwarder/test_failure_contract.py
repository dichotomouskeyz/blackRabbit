"""Forwarder release identity rule R-021."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest


def test_canonical_identity_mismatch_fails_before_metadata_reads():
    from capture.forwarder.preflight import SessionIdentityError, verify_session_ready

    cfg = SimpleNamespace(
        session_id="session", sponsor_id="sponsor", participant_id="p", site_id="s"
    )
    conn = Mock()
    cur = Mock()
    cur.__enter__ = Mock(return_value=cur)
    cur.__exit__ = Mock(return_value=False)
    conn.cursor.return_value = cur
    cur.fetchone.return_value = ("active", "another-person", "s")
    with pytest.raises(SessionIdentityError):
        verify_session_ready(cfg, conn)
    assert cur.execute.call_count == 1
