"""Operator UI INV-002/014/015: missing optional read DB config fails closed.

A configured tenant cannot make read endpoints fall back to a write-capable
connection or expose a raw server error when API_READONLY_DATABASE_URL is unset.
"""

import pytest

from config import settings
from tests.api_tests.support import (
    _INT_SITE_A,
    _INT_SPONSOR_A,
    _UNIT_VALID_SESSION_ID,
)


@pytest.mark.parametrize("readonly_url", [None, ""])
@pytest.mark.parametrize(
    "path",
    [
        "/sessions",
        f"/sessions/{_UNIT_VALID_SESSION_ID}/status",
        f"/sessions/{_UNIT_VALID_SESSION_ID}/arc",
    ],
)
def test_missing_readonly_url_returns_actionable_503_without_connecting(
    client, override_tenant, monkeypatch, readonly_url, path
):
    override_tenant(_INT_SPONSOR_A, _INT_SITE_A)
    monkeypatch.setattr(settings, "API_READONLY_DATABASE_URL", readonly_url)

    def no_connection(*args, **kwargs):
        raise AssertionError("Read endpoint attempted a connection without its read-only URL")

    monkeypatch.setattr("api.deps.psycopg2.connect", no_connection)

    response = client.get(path)

    assert response.status_code == 503
    assert response.json()["error"]
    assert "API_READONLY_DATABASE_URL" in response.json()["message"]
    assert client.get("/health").status_code == 200
