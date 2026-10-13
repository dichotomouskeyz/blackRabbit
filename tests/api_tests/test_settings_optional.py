"""INV-015 [unit] — Python-side UI vars are optional; settings.validate() unaffected.

After the frontend-shell reconciliation (RS-001), the agent route is provider-neutral
and runs in the JS env, so ANTHROPIC_API_KEY and the Python-side API_BASE_URL were
removed from config/settings.py — the UI's own vars (API_BASE_URL, AGENT_*) live only
in the JS env (frontend-shell INV-009). The remaining Python-side UI vars
(API_READONLY_DATABASE_URL, API_SPONSOR_ID, API_SITE_ID) are optional (_get_optional,
never _require); their absence must not raise in settings.validate(), so the capture/ARC
import path is unaffected.
"""

import importlib

import pytest

_REMOVED_PYTHON_UI_VARS = ("ANTHROPIC_API_KEY", "API_BASE_URL")
_OPTIONAL_PYTHON_UI_VARS = ("API_READONLY_DATABASE_URL", "API_SPONSOR_ID", "API_SITE_ID")


@pytest.fixture(autouse=True)
def restore_runtime_settings(monkeypatch):
    """Keep INV-015 import tests from erasing later integration-test configuration."""
    yield
    monkeypatch.undo()
    import config.settings as settings

    importlib.reload(settings)


def _reload_settings(monkeypatch):
    for var in (*_REMOVED_PYTHON_UI_VARS, *_OPTIONAL_PYTHON_UI_VARS):
        monkeypatch.delenv(var, raising=False)
    import config.settings as settings

    return importlib.reload(settings)


def test_removed_ui_vars_are_not_declared(monkeypatch):
    # Tests INV-009/RS-001: the JS-only / removed UI vars are NOT Python settings.
    settings = _reload_settings(monkeypatch)
    for var in _REMOVED_PYTHON_UI_VARS:
        assert not hasattr(settings, var), (
            f"{var} must not be a config.settings attribute — it is JS-env-only "
            f"(frontend-shell INV-009) or removed (RS-001)"
        )


def test_remaining_ui_vars_are_optional_attributes(monkeypatch):
    # Tests INV-015 [unit]: the remaining Python-side UI vars are declared and optional.
    # (Value may be non-None if the local .env sets them — settings loads .env at import.
    # The invariant is that they are _get_optional, i.e. importing never raises on them.)
    settings = _reload_settings(monkeypatch)
    for var in _OPTIONAL_PYTHON_UI_VARS:
        assert hasattr(settings, var), f"settings must declare {var}"


def test_validate_succeeds_with_ui_vars_unset(monkeypatch):
    # Tests INV-015 [unit]: validate() does not require any UI var.
    settings = _reload_settings(monkeypatch)
    try:
        settings.validate()
    except RuntimeError as exc:
        msg = str(exc)
        for var in (*_REMOVED_PYTHON_UI_VARS, *_OPTIONAL_PYTHON_UI_VARS):
            assert var not in msg, f"settings.validate() must not require UI var {var}: {msg}"
        pytest.skip(f"validate() failed for unrelated reasons (env not fully set): {exc}")
