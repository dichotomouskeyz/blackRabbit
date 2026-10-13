"""Server-side dependency wiring for the operator API.

Tenancy (`sponsor_id`, `site_id`) is resolved here from `config.settings`
(INV-001) — never from the request body/query or a model tool arg. The read
path connects as a GRANT SELECT-only Postgres role via
`API_READONLY_DATABASE_URL` (INV-002).

All config is read via `from config import settings` (PAT-002 / INV-011); the
API never reads process environment variables directly.
"""

from typing import Any, NamedTuple

import psycopg2

from config import settings


class ConfigurationError(Exception):
    """Raised when a request cannot proceed because server config is missing.

    Mapped to a 503 by an app-level exception handler (INV-001 fail-closed). The
    UI vars stay optional in `settings.validate()` (INV-015): import/validate
    succeed with them unset; only a request that needs them fails — never a
    silent fallthrough to a `sponsor_id=None` wrapped call.
    """


class TenantContext:
    """Server-injected tenant identity (INV-001).

    Resolved from `settings.*`, never from the request. In M0 this is a
    correctness scaffold for the future multi-tenant model (EA-001/EA-003).
    """

    def __init__(self, sponsor_id: str | None = None, site_id: str | None = None) -> None:
        self.sponsor_id = sponsor_id
        self.site_id = site_id


def get_tenant_context() -> TenantContext:
    """Resolve tenancy from settings.* (INV-001).

    Tests override this FastAPI dependency via `app.dependency_overrides`
    (EA-003's single-sponsor default must be overridable). Production reads the
    named `settings.API_SPONSOR_ID` / `settings.API_SITE_ID` values.

    This returns the resolved context (possibly carrying None values) and does
    NOT raise: input validation (INV-004) must be able to run and return 422
    before tenancy is enforced. The fail-closed None-tenancy check lives in
    `require_tenant`, which routes call AFTER input validation but BEFORE any DB
    connection or wrapped contract call.
    """
    return TenantContext(
        sponsor_id=settings.API_SPONSOR_ID,
        site_id=settings.API_SITE_ID,
    )


class ValidatedTenantContext(NamedTuple):
    """Non-empty server tenancy returned only after runtime validation."""

    sponsor_id: str
    site_id: str


def require_tenant(tenant: TenantContext) -> ValidatedTenantContext:
    """Enforce non-null tenancy fail-closed (INV-001 / QA-004).

    Called by tenancy-scoped routes AFTER input validation (INV-004 keeps a 422
    on bad input ahead of any tenancy/DB work) and BEFORE any DB connection or
    wrapped contract call. If `sponsor_id`/`site_id` is unset, raise
    `ConfigurationError` (mapped to a 503 `tenancy_not_configured`) so no route
    ever runs with `sponsor_id=None`. The vars remain optional in
    `settings.validate()` (INV-015): only requests fail, not import/validate.
    """
    if not tenant.sponsor_id or not tenant.site_id:
        raise ConfigurationError("API tenancy not configured: set API_SPONSOR_ID/API_SITE_ID.")
    return ValidatedTenantContext(tenant.sponsor_id, tenant.site_id)


def _readonly_url() -> str:
    """Return the read-only DB role URL (INV-002).

    Prefers `API_READONLY_DATABASE_URL`. The connection must be a
    GRANT SELECT-only role so any write raises InsufficientPrivilege.
    """
    url = settings.API_READONLY_DATABASE_URL
    if not url:
        # No silent fallback to a write-capable URL: fail loud so a
        # misconfigured deployment cannot issue writes through the API path.
        raise ConfigurationError(
            "API_READONLY_DATABASE_URL is not set; the API read path requires a "
            "GRANT SELECT-only Postgres role (INV-002)."
        )
    return url


def get_readonly_connection() -> Any:
    """Open a connection on the read-only API DB role (INV-002).

    All direct reads in `api/` use this connection. The role is SELECT-only, so
    any write raises `psycopg2.errors.InsufficientPrivilege` at the driver.
    """
    conn = psycopg2.connect(_readonly_url())
    conn.set_session(isolation_level="REPEATABLE READ", autocommit=False)
    return conn
