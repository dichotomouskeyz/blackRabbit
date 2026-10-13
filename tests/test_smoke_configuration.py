"""SM-001: reject accidental smoke targets before opening a database."""

from unittest.mock import Mock

import pytest

from scripts.backend_smoke import configure


@pytest.mark.parametrize(
    "database_url,test_url",
    [
        ("", ""),
        ("dbname=production", "dbname=production"),
        ("dbname=blackrabbit_test", "dbname=other_test"),
        ("dbname=blackrabbit_audit", ""),
    ],
)
def test_invalid_smoke_target_is_rejected_before_connection(
    monkeypatch, tmp_path, database_url, test_url
):
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("TEST_DATABASE_URL", test_url)
    connect = Mock(side_effect=AssertionError("Unexpected database access"))
    monkeypatch.setattr("scripts.backend_smoke.psycopg2.connect", connect)
    with pytest.raises(RuntimeError):
        configure(tmp_path)
    connect.assert_not_called()
    assert not list(tmp_path.iterdir())
