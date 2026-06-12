"""Fixtures for operator-API tests.

Reuses the root `tests/conftest.py` DB fixtures (db_conn, cursor, db_url) and
its dotenv load. Adds a TestClient, a tenancy override hook, a readonly-role
connection, and DB seeding for tenancy/watermark integration tests.
"""

import os

import psycopg2
import pytest

from tests.api_tests.support import (
    _INT_DEVICE,
    _INT_PARTICIPANT,
    _INT_SESSION_FAILED,
    _INT_SESSION_INPROGRESS,
    _INT_SESSION_NOTSTARTED,
    _INT_SESSION_OTHER_SPONSOR,
    _INT_SESSION_VERIFIED,
    _INT_SITE_A,
    _INT_SITE_B,
    _INT_SPONSOR_A,
    _INT_SPONSOR_B,
)


@pytest.fixture
def app():
    """Build a fresh operator-API app for each test."""
    from api.app import create_app

    return create_app()


@pytest.fixture
def client(app):
    """A raw TestClient over the real app (no agent in the loop)."""
    from fastapi.testclient import TestClient

    return TestClient(app)


@pytest.fixture
def override_tenant(app):
    """Return a setter that injects a server tenant context into the app.

    Lets a test construct one or two server contexts directly (EA-003's
    single-sponsor default must be overridable in tests — spec). GREEN exposes
    `api.deps.get_tenant_context`; this overrides FastAPI's dependency for it.
    """
    from api import deps

    def _set(sponsor_id: str, site_id: str):
        ctx = deps.TenantContext(sponsor_id=sponsor_id, site_id=site_id)
        app.dependency_overrides[deps.get_tenant_context] = lambda: ctx
        return ctx

    yield _set
    app.dependency_overrides.clear()


# --- Read-only API role connection (INV-002) --------------------------------
@pytest.fixture
def readonly_url():
    url = os.getenv("API_READONLY_DATABASE_URL")
    if not url:
        pytest.skip("API_READONLY_DATABASE_URL not set in .env")
    return url


@pytest.fixture
def readonly_conn(readonly_url):
    conn = psycopg2.connect(readonly_url)
    conn.autocommit = False
    yield conn
    conn.rollback()
    conn.close()


# --- Seeding for tenancy + watermark integration tests ----------------------
def _insert_session(cursor, session_id, sponsor_id, site_id, status_literal):
    cursor.execute(
        """
        INSERT INTO sessions
            (id, site_id, sponsor_id, participant_id, capture_source,
             compound, status, started_at)
        VALUES
            (%(id)s::uuid, %(site)s::uuid, %(sponsor)s::uuid, %(participant)s::uuid,
             'simulated', 'psilocybin', %(status)s::session_status, NOW())
        """,
        {
            "id": session_id,
            "site": site_id,
            "sponsor": sponsor_id,
            "participant": _INT_PARTICIPANT,
            "status": status_literal,
        },
    )


def _transition(cursor, session_id, status_literal):
    """Drive a real status transition so the watermark trigger fires."""
    cursor.execute(
        "UPDATE sessions SET status = %(status)s::session_status, closed_at = NOW() "
        "WHERE id = %(id)s::uuid",
        {"status": status_literal, "id": session_id},
    )


_ALL_SEED_IDS = (
    _INT_SESSION_VERIFIED,
    _INT_SESSION_INPROGRESS,
    _INT_SESSION_FAILED,
    _INT_SESSION_NOTSTARTED,
    _INT_SESSION_OTHER_SPONSOR,
)


@pytest.fixture
def seeded_sessions(cursor, db_conn):
    """Seed sessions across watermark states + two sponsors, committed.

    - verified  : sponsor A, transitioned active->closed (watermark_verified)
    - inprogress: sponsor A, status 'active' (no terminal watermark)
    - failed    : sponsor A, transitioned active->failed (watermark_failed)
    - notstarted: sponsor A, status 'initializing'
    - other     : sponsor B, verified (must be filtered out for sponsor A)
    """
    # Clean any stragglers first.
    for sid in _ALL_SEED_IDS:
        cursor.execute("DELETE FROM sessions WHERE id = %s::uuid", (sid,))

    _insert_session(cursor, _INT_SESSION_VERIFIED, _INT_SPONSOR_A, _INT_SITE_A, "active")
    _transition(cursor, _INT_SESSION_VERIFIED, "closed")

    _insert_session(cursor, _INT_SESSION_INPROGRESS, _INT_SPONSOR_A, _INT_SITE_A, "active")

    _insert_session(cursor, _INT_SESSION_FAILED, _INT_SPONSOR_A, _INT_SITE_A, "active")
    _transition(cursor, _INT_SESSION_FAILED, "failed")

    _insert_session(cursor, _INT_SESSION_NOTSTARTED, _INT_SPONSOR_A, _INT_SITE_A, "initializing")

    _insert_session(cursor, _INT_SESSION_OTHER_SPONSOR, _INT_SPONSOR_B, _INT_SITE_B, "active")
    _transition(cursor, _INT_SESSION_OTHER_SPONSOR, "closed")

    db_conn.commit()
    yield {
        "sponsor_a": _INT_SPONSOR_A,
        "site_a": _INT_SITE_A,
        "sponsor_b": _INT_SPONSOR_B,
        "site_b": _INT_SITE_B,
        "verified": _INT_SESSION_VERIFIED,
        "inprogress": _INT_SESSION_INPROGRESS,
        "failed": _INT_SESSION_FAILED,
        "notstarted": _INT_SESSION_NOTSTARTED,
        "other_sponsor": _INT_SESSION_OTHER_SPONSOR,
        "device": _INT_DEVICE,
    }
    db_conn.rollback()
    for sid in _ALL_SEED_IDS:
        cursor.execute("DELETE FROM sessions WHERE id = %s::uuid", (sid,))
    db_conn.commit()
