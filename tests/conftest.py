"""Consensai 1a — Pytest configuration and shared fixtures.

WHY CONFTEST.PY EXISTS:
  pytest automatically loads conftest.py before running any tests.
  It's where you put shared setup code (called "fixtures") that
  multiple test files can use without repeating themselves.

  Think of a fixture like a reusable tool. Instead of every test
  opening its own database connection, they all just ask for the
  db_conn fixture and pytest hands them one.

HOW FIXTURES WORK:
  A fixture is a function decorated with @pytest.fixture.
  When a test function lists a fixture name as a parameter,
  pytest calls the fixture first and passes the result in.

YIELD FIXTURES:
  When a fixture uses yield instead of return, everything
  before yield is setup, and everything after is teardown.
  Pytest runs teardown automatically after the test finishes,
  even if the test fails. This guarantees the database is always
  cleaned up, no matter what.
"""

import os

import psycopg2
import pytest
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))


def _parse_url(url: str) -> dict:
    """Parse a postgres URL into psycopg2 connect kwargs."""
    url = url.replace("postgresql://", "")
    user_pass, rest = url.split("@")
    user, password = user_pass.split(":")
    host_port, dbname = rest.split("/")
    host, port = host_port.split(":")
    return dict(host=host, port=int(port), dbname=dbname, user=user, password=password)


@pytest.fixture(scope="session")
def db_url():
    """Return the test database URL.

    scope=session means this fixture runs ONCE for the entire
    test session, not once per test.
    """
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        raise RuntimeError(
            "TEST_DATABASE_URL not set in .env. "
            "Add: TEST_DATABASE_URL=postgresql://postgres:PASSWORD@localhost:5432/consensai_test"
        )
    return url


@pytest.fixture(scope="function")
def db_conn(db_url):
    """Open a database connection for a single test, then close it.

    scope=function means a fresh connection for every test.
    We ROLLBACK at the end instead of COMMIT so test data never
    actually persists to the database. Keeps the test DB clean
    without needing to manually delete rows after each test.

    WHY PSYCOPG2 DIRECTLY (NOT SQLALCHEMY):
      These are schema validation tests. We want to test the raw
      database behavior - does the table exist, does the trigger
      fire, does the constraint reject invalid data?
      psycopg2 is the direct Postgres driver with no abstraction.
    """
    conn = psycopg2.connect(**_parse_url(db_url))
    conn.autocommit = False
    yield conn
    conn.rollback()
    conn.close()


@pytest.fixture(scope="function")
def cursor(db_conn):
    """Return a cursor for the current test connection.

    A cursor is the object you use to execute SQL.
    The connection is the channel; the cursor is the pen.
    """
    cur = db_conn.cursor()
    yield cur
    cur.close()


@pytest.fixture(scope="session", autouse=True)
def setup_restricted_role(db_url):
    """Create a non-owner role for testing REVOKE-based access controls.

    WHY THIS IS NEEDED:
      PostgreSQL table owners bypass REVOKE — they can always UPDATE/DELETE
      their own tables regardless of privilege grants. The postgres superuser
      is effectively the owner of all objects created in this session.
      To test that REVOKE UPDATE / REVOKE DELETE actually blocks access,
      we must connect as a non-owner role.

      This fixture creates a minimal role (consensai_limited) that has
      SELECT + INSERT only. REVOKE-protected tables should reject UPDATE
      and DELETE from this role.
    """
    kwargs = _parse_url(db_url)
    conn = psycopg2.connect(**kwargs)
    conn.autocommit = True
    cur = conn.cursor()

    cur.execute("DROP ROLE IF EXISTS consensai_limited;")
    cur.execute("CREATE ROLE consensai_limited LOGIN PASSWORD 'limitedpass' NOINHERIT;")
    cur.execute(f"GRANT CONNECT ON DATABASE {kwargs['dbname']} TO consensai_limited;")
    cur.execute("GRANT USAGE ON SCHEMA public TO consensai_limited;")
    cur.execute(
        "GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA public TO consensai_limited;"
    )
    cur.execute("GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO consensai_limited;")
    cur.close()
    conn.close()

    yield

    conn2 = psycopg2.connect(**kwargs)
    conn2.autocommit = True
    cur2 = conn2.cursor()
    cur2.execute("DROP OWNED BY consensai_limited;")
    cur2.execute("DROP ROLE IF EXISTS consensai_limited;")
    cur2.close()
    conn2.close()


@pytest.fixture(scope="function")
def restricted_conn(db_url, setup_restricted_role):
    """Connection as consensai_limited — cannot UPDATE/DELETE on REVOKE-protected tables."""
    kwargs = _parse_url(db_url)
    kwargs["user"] = "consensai_limited"
    kwargs["password"] = "limitedpass"
    conn = psycopg2.connect(**kwargs)
    conn.autocommit = False
    yield conn
    conn.rollback()
    conn.close()


@pytest.fixture(scope="function")
def restricted_cursor(restricted_conn):
    cur = restricted_conn.cursor()
    yield cur
    cur.close()
