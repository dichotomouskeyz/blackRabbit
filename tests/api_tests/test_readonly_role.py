"""INV-002 — API wraps backend contracts; direct SQL runs on a read-only role.

- The LOAD-BEARING test obtains the connection via the REAL production factory
  `api.deps.get_readonly_connection()` (B2 fix): a SELECT works and an
  INSERT/UPDATE raises InsufficientPrivilege. This proves the API's own
  connection path — not just the test fixture URL — is read-only.
- One fixture-URL test is kept (marked infra-only) to prove the DB role grant
  itself; it does NOT prove the api/ factory and must not be the only check.
- api/ read SQL constants match ^(SELECT|WITH) with no write token
  (closed-SQL positive scan over the read module).
"""

import importlib
import pkgutil

import psycopg2.errors
import pytest

from tests.api_tests.support import READ_PREFIX_RE, WRITE_TOKEN_RE


def _iter_api_sql_constants():
    """Yield (module_name, const_name, sql) for every uppercase *_SQL str
    constant defined across ALL submodules of the `api` package (QA-002).

    Generic discovery so no api/ module that defines SQL can escape the
    read-only / no-write / no-audit-table assertions — including api.arc
    (WATERMARK_EVENTS_FOR_ARC_SQL) and any future module.
    """
    import api

    for info in pkgutil.iter_modules(api.__path__, prefix="api."):
        mod = importlib.import_module(info.name)
        for name, val in vars(mod).items():
            if name.isupper() and name.endswith("SQL") and isinstance(val, str):
                yield info.name, name, val


# --- B2 load-bearing: the REAL production factory must be read-only -----------


@pytest.mark.integration
def test_api_factory_connection_allows_select(readonly_url):
    # Tests INV-002 [integration]: a SELECT works on the connection produced by
    # api.deps.get_readonly_connection() (the production path, not the fixture).
    from api import deps

    conn = deps.get_readonly_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            assert cur.fetchone()[0] == 1
    finally:
        conn.rollback()
        conn.close()


@pytest.mark.integration
def test_api_factory_connection_insert_raises_insufficient_privilege(readonly_url):
    # Tests INV-002 [integration]: a write through the REAL factory connection
    # raises InsufficientPrivilege. This is the load-bearing INV-002 check —
    # it exercises api.deps.get_readonly_connection(), not the fixture URL.
    from api import deps

    conn = deps.get_readonly_connection()
    try:
        with conn.cursor() as cur:
            with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                cur.execute(
                    """
                    INSERT INTO sessions
                        (id, site_id, sponsor_id, participant_id, capture_source,
                         compound, status, started_at)
                    VALUES
                        (gen_random_uuid(), gen_random_uuid(), gen_random_uuid(),
                         gen_random_uuid(), 'simulated', 'psilocybin',
                         'active'::session_status, NOW())
                    """
                )
    finally:
        conn.rollback()
        conn.close()


@pytest.mark.integration
def test_api_factory_connection_update_raises_insufficient_privilege(readonly_url):
    # Tests INV-002 [integration]: UPDATE through the real factory is also denied.
    from api import deps

    conn = deps.get_readonly_connection()
    try:
        with conn.cursor() as cur:
            with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                cur.execute("UPDATE sessions SET status = 'failed'::session_status WHERE FALSE")
    finally:
        conn.rollback()
        conn.close()


# --- Infra-only: proves the DB role grant via the fixture URL -----------------
# INTENT: this exercises the raw API_READONLY_DATABASE_URL fixture connection,
# NOT api.deps. It proves the Postgres GRANT is set up correctly but does not
# prove the api/ factory connects as that role. Kept as a backstop only.


@pytest.mark.integration
def test_fixture_url_role_insert_raises_insufficient_privilege(readonly_conn):
    # Tests INV-002 [integration, infra-only]: the read-only DB role itself denies
    # writes. Backstop for the grant; the load-bearing check is the factory above.
    with readonly_conn.cursor() as cur:
        with pytest.raises(psycopg2.errors.InsufficientPrivilege):
            cur.execute("UPDATE sessions SET status = 'failed'::session_status WHERE FALSE")


def test_read_sql_constants_are_read_only():
    # Tests INV-002 / PAT-003 [unit]: closed-SQL positive scan over ALL api.*
    # submodules generically (QA-002), not a hardcoded module list. A write token
    # in ANY api/ module's *_SQL constant fails — including api.arc.
    found = list(_iter_api_sql_constants())
    assert found, "api/ must expose read SQL as module-level *_SQL constants"

    # The scan must cover api.arc's WATERMARK_EVENTS_FOR_ARC_SQL specifically
    # (the QA-002 mock-gap): assert it was discovered.
    discovered = {(mod, name) for mod, name, _ in found}
    assert ("api.arc", "WATERMARK_EVENTS_FOR_ARC_SQL") in discovered, (
        "generic scan must cover api.arc.WATERMARK_EVENTS_FOR_ARC_SQL (QA-002)"
    )

    for mod_name, name, sql in found:
        assert READ_PREFIX_RE.match(sql), f"{mod_name}.{name} must start with SELECT/WITH: {sql!r}"
        assert not WRITE_TOKEN_RE.search(sql), f"{mod_name}.{name} contains a write token: {sql!r}"
