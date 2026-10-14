"""Spec-derived CI-002/003 guard checks; no database connection is permitted."""

import pytest

from scripts.provision_test_roles import provision


@pytest.mark.parametrize(
    "admin,test,readonly",
    [
        ("postgresql://admin@localhost/production",) * 2
        + ("postgresql://blackrabbit_ci_ro@localhost/production",),
        (
            "postgresql://admin@localhost/blackrabbit_test",
            "postgresql://admin@localhost/other_test",
            "postgresql://blackrabbit_ci_ro@localhost/blackrabbit_test",
        ),
        ("postgresql://admin@localhost/blackrabbit_test",) * 2
        + ("postgresql://blackrabbit_ci_ro@remote/blackrabbit_test",),
        ("postgresql://admin@localhost/blackrabbit_test",) * 2
        + ("postgresql://admin@localhost/blackrabbit_test",),
    ],
)
def test_provision_rejects_invalid_target_before_connect(monkeypatch, admin, test, readonly):
    monkeypatch.setenv("DATABASE_URL", admin)
    monkeypatch.setenv("TEST_DATABASE_URL", test)
    monkeypatch.setenv("API_READONLY_DATABASE_URL", readonly)

    def no_connection(*args, **kwargs):
        raise AssertionError("Invalid provisioning configuration reached the database")

    monkeypatch.setattr("scripts.provision_test_roles.psycopg2.connect", no_connection)
    with pytest.raises(RuntimeError):
        provision()
