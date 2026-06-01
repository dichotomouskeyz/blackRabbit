# Fixture Patterns and Conftest Structure

## Dependency Injection (mandatory)

All test files use dependency injection. No monkey patching. No reaching into private
attributes. This was decided in the test audit (May 2026) — Option A.

The principle: production code constructors accept factory functions as parameters.
In production, the real factory is passed. In tests, a test factory is passed. The
object calls whatever it was handed without caring what it is.

```python
# Production usage
forwarder = LSLForwarder(db_factory=psycopg2.connect, inlet_factory=pylsl.StreamInlet)

# Test usage
forwarder = LSLForwarder(db_factory=mock_db_connect, inlet_factory=mock_inlet)
```

---

## Root conftest.py (`tests/conftest.py`)

Provides these shared fixtures for all domains:

```python
@pytest.fixture(scope="session")
def db_url():
    """Return the test database URL from TEST_DATABASE_URL env var.
    Skips the test if the DB is unavailable rather than failing hard.
    """
    ...

@pytest.fixture(scope="function")
def db_conn(db_url):
    """Open a psycopg2 connection, yield it, then ROLLBACK and close.
    Rollback on teardown keeps the test DB clean without manual deletes.
    scope=function means a fresh connection per test.
    """
    conn = psycopg2.connect(db_url)
    conn.autocommit = False
    yield conn
    conn.rollback()
    conn.close()

@pytest.fixture(scope="function")
def cursor(db_conn):
    """Return a cursor for the current test connection."""
    cur = db_conn.cursor()
    yield cur
    cur.close()

@pytest.fixture(scope="session")
def restricted_role(db_url):
    """Create the low-privilege role used by append-only schema tests."""
    ...

@pytest.fixture(scope="function")
def restricted_conn(db_url, restricted_role): ...
@pytest.fixture(scope="function")
def restricted_cursor(restricted_conn): ...
```

Integration tests (those requiring a real DB) must be marked `@pytest.mark.integration`.
The root conftest auto-skips them if `TEST_DATABASE_URL` is not set.

---

## Domain conftest.py

Each domain under `tests/capture_tests/<domain>/` may have its own `conftest.py` for
domain-specific seed data fixtures. Pattern:

```python
# tests/capture_tests/<domain>/conftest.py
import pytest
from tests.capture_tests.<domain>.support import SESSION_ID, PARTICIPANT_ID, SITE_ID, SPONSOR_ID

@pytest.fixture
def seeded_session(cursor, db_conn):
    """Insert a minimal valid session and commit. Yield, then let db_conn rollback."""
    cursor.execute(
        """
        INSERT INTO sessions (id, site_id, sponsor_id, participant_id, compound, status)
        VALUES (%s, %s::uuid, %s::uuid, %s::uuid, 'psilocybin', 'closed'::session_status)
        """,
        (SESSION_ID, SITE_ID, SPONSOR_ID, PARTICIPANT_ID),
    )
    db_conn.commit()
    yield
```

---

## support.py

Each domain has a `support.py` with fixed UUIDs and constants used across test files
in that domain. Do not generate random UUIDs in support files — fixed values make
failures reproducible.

```python
# tests/capture_tests/<domain>/support.py
SESSION_ID     = "aaaa0000-0000-0000-0000-000000000001"
PARTICIPANT_ID = "bbbb0000-0000-0000-0000-000000000001"
SITE_ID        = "cccc0000-0000-0000-0000-000000000001"
SPONSOR_ID     = "dddd0000-0000-0000-0000-000000000001"
DEVICE_ID      = "eeee0000-0000-0000-0000-000000000001"
LSL_TIMESTAMP  = 12345.678901
```

Use the `ffff` prefix range for schema tests, `eeee` for reconciliation, etc.
Pick a distinct prefix range per domain so UUIDs from different domains never collide.

---

## Module-Specific Fixtures

Each test file adds fixtures for its module's constructor dependencies:

```python
@pytest.fixture
def config_path(tmp_path):
    """Write a minimal valid TOML config and return its path."""
    p = tmp_path / "arc_watchdog.toml"
    p.write_text("""
config_version = "test-001"
config_role = "arc_watchdog"
[baseline]
window_duration_s = 10.0
...
""")
    return p

@pytest.fixture
def module_under_test(db_conn, config_path):
    """Construct the module with injected dependencies."""
    return ModuleName(db_conn=db_conn, config_path=str(config_path))
```

---

## File Layout

```
tests/
  conftest.py                              # shared: db_url, db_conn, cursor, restricted_*
  capture_tests/
    <domain>/
      __init__.py
      support.py                           # constants (UUIDs, timestamps)
      conftest.py                          # domain seed-data fixtures (optional)
      test_<module>.py
    arc/
      test_arc_processor.py
      test_arc_windows.py
      test_arc_preflight.py
      test_arc_models.py
      test_baseline.py                     # Phase 3b
      test_convergence_e2e.py              # Category 5b — pipeline integration
```
