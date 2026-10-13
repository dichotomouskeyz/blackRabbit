"""One capture, close, or recovery owner per session across local processes."""


class SessionBusyError(RuntimeError):
    """Another connection owns the session's capture/recovery lifecycle."""


def acquire_session_lock(conn, session_id: str) -> None:
    """Hold a PostgreSQL session lock until this connection closes.

    A session lock survives chunk commits. All lifecycle entry points share
    the same key; no application table or audit record is modified.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock(hashtextextended(%s, 0))", (session_id,))
        if not cur.fetchone()[0]:
            raise SessionBusyError("session is busy with capture, closeout, or recovery")
