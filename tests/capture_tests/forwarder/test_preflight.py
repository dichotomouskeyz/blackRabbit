"""Tests for forwarder preflight metadata loading."""

from unittest.mock import MagicMock, patch

from capture.forwarder.models import SessionConfig
from capture.forwarder.preflight import load_session_config
from config import settings


def test_load_session_config_attaches_eeg_channel_names():
    cfg = SessionConfig(
        session_id="11111111-1111-1111-1111-111111111111",
        participant_id="22222222-2222-2222-2222-222222222222",
        site_id="33333333-3333-3333-3333-333333333333",
        sponsor_id="44444444-4444-4444-4444-444444444444",
    )
    conn = MagicMock()
    cur = MagicMock()
    cur.fetchone.return_value = ([f"Fp{i}" for i in range(settings.EEG_CHANNEL_COUNT)],)
    conn.cursor.return_value.__enter__.return_value = cur

    with patch("capture.forwarder.preflight.psycopg2.connect", return_value=conn):
        loaded = load_session_config(cfg)

    assert loaded.eeg_channel_names == tuple(
        f"Fp{i}" for i in range(settings.EEG_CHANNEL_COUNT)
    )


def test_load_session_config_returns_input_when_names_missing():
    cfg = SessionConfig(
        session_id="11111111-1111-1111-1111-111111111111",
        participant_id="22222222-2222-2222-2222-222222222222",
        site_id="33333333-3333-3333-3333-333333333333",
        sponsor_id="44444444-4444-4444-4444-444444444444",
    )
    conn = MagicMock()
    cur = MagicMock()
    cur.fetchone.return_value = (None,)
    conn.cursor.return_value.__enter__.return_value = cur

    with patch("capture.forwarder.preflight.psycopg2.connect", return_value=conn):
        loaded = load_session_config(cfg)

    assert loaded is cfg
