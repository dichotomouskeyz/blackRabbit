"""DB helpers shared across watchdog test modules."""

import os

import psycopg2

_SITE_UUID = "f1d00009-0000-4444-cccc-000000000001"
_SPONSOR_UUID = "f1d00009-0000-4444-dddd-000000000001"
_PART_UUID = "f1d00009-0000-4444-bbbb-000000000001"


def _direct_conn() -> psycopg2.extensions.connection:
    url = os.getenv("TEST_DATABASE_URL", "")
    url = url.replace("postgresql://", "")
    user_pass, rest = url.split("@")
    user, password = user_pass.split(":")
    host_port, dbname = rest.split("/")
    host, port = host_port.split(":")
    return psycopg2.connect(host=host, port=int(port), dbname=dbname, user=user, password=password)


def _insert_session(session_id: str, status: str = "active") -> None:
    conn = _direct_conn()
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO sessions (id, site_id, sponsor_id, participant_id,
                                  compound, status)
            VALUES (%s, %s::uuid, %s::uuid, %s::uuid,
                    'psilocybin', %s::session_status)
            ON CONFLICT (id) DO NOTHING
            """,
            (session_id, _SITE_UUID, _SPONSOR_UUID, _PART_UUID, status),
        )
    conn.close()


def _cleanup_session(session_id: str) -> None:
    conn = _direct_conn()
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("DELETE FROM audit_events WHERE session_id = %s", (session_id,))
        cur.execute("DELETE FROM alert_events WHERE session_id = %s", (session_id,))
        cur.execute("DELETE FROM sessions WHERE id = %s", (session_id,))
    conn.close()


def _get_status(session_id: str) -> str | None:
    conn = _direct_conn()
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("SELECT status FROM sessions WHERE id = %s", (session_id,))
        row = cur.fetchone()
    conn.close()
    return str(row[0]) if row else None


def _get_audit_types(session_id: str) -> list[str]:
    conn = _direct_conn()
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(
            "SELECT event_type FROM audit_events WHERE session_id = %s ORDER BY id",
            (session_id,),
        )
        rows = cur.fetchall()
    conn.close()
    return [r[0] for r in rows]
