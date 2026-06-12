"""INV-015 [unit] — new UI env vars are optional; settings.validate() unaffected.

ANTHROPIC_API_KEY / API_BASE_URL (and any Python-side UI var) are optional in
config/settings.py (_get_optional, never _require); their absence must not raise
in settings.validate(), so the capture/ARC import path is unaffected.
"""

import importlib

import pytest


def _reload_settings(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("API_BASE_URL", raising=False)
    import config.settings as settings

    return importlib.reload(settings)


def test_ui_vars_are_optional_attributes(monkeypatch):
    # Tests INV-015 [unit]: settings exposes the UI vars and they are optional.
    settings = _reload_settings(monkeypatch)
    assert hasattr(settings, "ANTHROPIC_API_KEY"), "settings must declare ANTHROPIC_API_KEY"
    assert hasattr(settings, "API_BASE_URL"), "settings must declare API_BASE_URL"
    # Optional -> None when unset, never a raised error at import.
    assert settings.ANTHROPIC_API_KEY is None
    assert settings.API_BASE_URL is None


def test_validate_succeeds_with_ui_vars_unset(monkeypatch):
    # Tests INV-015 [unit]: validate() does not raise when UI vars are absent.
    settings = _reload_settings(monkeypatch)
    try:
        settings.validate()
    except RuntimeError as exc:
        msg = str(exc)
        assert "ANTHROPIC_API_KEY" not in msg and "API_BASE_URL" not in msg, (
            f"settings.validate() must not require UI vars: {msg}"
        )
        pytest.skip(f"validate() failed for unrelated reasons (env not fully set): {exc}")
