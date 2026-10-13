"""Provision the SELECT-only API role in an explicitly isolated test database.

Requires DATABASE_URL == TEST_DATABASE_URL and API_READONLY_DATABASE_URL naming
that same endpoint/database. Only databases with an underscore-delimited `test`
or `audit` component are accepted. Never drops data, resets passwords, or grants
write privileges. Intended for disposable CI databases, after Alembic upgrade.
"""

from __future__ import annotations

import json
import os
import re
from contextlib import closing

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import parse_dsn


def _scalar(cursor):
    row = cursor.fetchone()
    if row is None:
        raise RuntimeError("Expected one database validation row")
    return row[0]


def provision() -> dict:
    admin_url = os.environ.get("DATABASE_URL", "")
    if not admin_url or admin_url != os.environ.get("TEST_DATABASE_URL"):
        raise RuntimeError("DATABASE_URL and TEST_DATABASE_URL must name the same test database")
    readonly_url = os.environ.get("API_READONLY_DATABASE_URL", "")
    if not readonly_url:
        raise RuntimeError("API_READONLY_DATABASE_URL is required")
    admin, readonly = parse_dsn(admin_url), parse_dsn(readonly_url)
    database = admin.get("dbname", "")
    if not re.search(r"(^|_)(test|audit)(_|$)", database):
        raise RuntimeError("Database name must have an explicit _test or _audit component")
    for key, default in (("host", ""), ("hostaddr", ""), ("port", "5432"), ("dbname", "")):
        if admin.get(key, default) != readonly.get(key, default):
            raise RuntimeError("API read-only role must target the same test database endpoint")
    role = readonly.get("user", "")
    password = readonly.get("password", "")
    if not re.fullmatch(r"blackrabbit_[a-z0-9_]{1,48}", role) or role == admin.get("user"):
        raise RuntimeError("API role must be a distinct blackrabbit_ test role")
    if not password:
        raise RuntimeError("API test role requires a password")
    with closing(psycopg2.connect(admin_url, connect_timeout=5)) as conn, conn:
        with conn.cursor() as cur:
            cur.execute("SELECT current_database()")
            if _scalar(cur) != database:
                raise RuntimeError("Connected database does not match the requested test database")
            cur.execute("SELECT version_num FROM alembic_version")
            if _scalar(cur) != "030_arc_failure_alert_type":
                raise RuntimeError("Migrate the isolated database to head before provisioning")
            cur.execute(
                "SELECT rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls "
                "FROM pg_roles WHERE rolname=%s",
                (role,),
            )
            existing = cur.fetchone()
            if existing is not None and any(existing):
                raise RuntimeError(
                    "Existing API role has elevated privileges; refusing to modify it"
                )
            if existing is None:
                cur.execute(
                    sql.SQL(
                        "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB "
                        "NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD %s"
                    ).format(sql.Identifier(role)),
                    (password,),
                )
            cur.execute(
                "SELECT EXISTS(SELECT 1 FROM pg_auth_members m JOIN pg_roles r "
                "ON r.oid=m.member WHERE r.rolname=%s)",
                (role,),
            )
            if _scalar(cur):
                raise RuntimeError("Existing API role inherits privileges; refusing to modify it")
            cur.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    sql.Identifier(database), sql.Identifier(role)
                )
            )
            cur.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(role)))
            cur.execute(
                sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA public TO {}").format(
                    sql.Identifier(role)
                )
            )
            cur.execute(
                """SELECT EXISTS(SELECT 1 FROM information_schema.tables
                WHERE table_schema='public'
                AND has_table_privilege(%s, quote_ident(table_schema)||'.'||quote_ident(table_name),
                    'INSERT,UPDATE,DELETE,TRUNCATE'))""",
                (role,),
            )
            if _scalar(cur):
                raise RuntimeError("API role has write privileges; refusing to accept it")
    # Verify the actual password/connection instead of only catalog grants.
    with closing(psycopg2.connect(readonly_url, connect_timeout=5)) as conn, conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM sessions")
            cur.fetchone()
            cur.execute("SELECT has_table_privilege(current_user,'sessions','INSERT')")
            if _scalar(cur):
                raise RuntimeError("API connection unexpectedly permits session writes")
    return {"database": database, "api_role": role, "select_only": True}


if __name__ == "__main__":
    print(json.dumps(provision()))
