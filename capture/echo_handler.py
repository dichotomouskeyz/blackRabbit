"""untitledplatform_1a — ECHO Marker Stream handler.

Listens on the LSL Marker Stream for proximity state events sent by the
coordinator's tablet. Each button press on the tablet produces one LSL
marker string. This handler decodes the string, validates it, and writes
a row to echo_events with the LSL-sourced timestamp.

In 1a all events carry source='manual_logging'. The schema accommodates
source='imu_derived' (1b hardware inference) without a migration.

Marker format
-------------
Every valid marker is a pipe-delimited string with exactly 5 fields:

    ECHO|<event_type>|<actor_id>|<actor_role>|<zone_label>

Example:
    ECHO|proximity_state_change|therapist_01|therapist|arms_reach

Fields:
    event_type  — always 'proximity_state_change' in 1a
    actor_id    — unique label for the person being logged (e.g. therapist_01)
    actor_role  — therapist | facilitator | coordinator | observer
    zone_label  — arms_reach | in_room | leaving_room | out_of_room

Malformed or unrecognised markers are logged as warnings and skipped.
The biosignal capture threads are unaffected if this stream is absent.
"""

import threading

import psycopg2

from capture.logger import get_logger
from config import settings

log = get_logger("echo_handler")

MARKER_PREFIX = "ECHO"
_SEP = "|"
_FIELD_COUNT = 5

VALID_ZONE_LABELS: frozenset[str] = frozenset(
    {"arms_reach", "in_room", "leaving_room", "out_of_room"}
)
VALID_ACTOR_ROLES: frozenset[str] = frozenset(
    {"therapist", "facilitator", "coordinator", "observer"}
)
VALID_EVENT_TYPES: frozenset[str] = frozenset({"proximity_state_change"})

_BUFFER_MAX = 100

_ECHO_INSERT = """
    INSERT INTO echo_events (
        session_id, participant_id, site_id, sponsor_id,
        event_type, source, actor_id, actor_role,
        zone_label, lsl_timestamp
    ) VALUES (
        %(session_id)s, %(participant_id)s, %(site_id)s, %(sponsor_id)s,
        %(event_type)s, 'manual_logging', %(actor_id)s, %(actor_role)s,
        %(zone_label)s, %(lsl_timestamp)s
    )
"""


def parse_echo_marker(marker: str) -> dict | None:
    """Parse a ECHO pipe-delimited marker string into a field dict.

    Returns a dict with event_type, actor_id, actor_role, zone_label on
    success. Returns None for any malformed or unrecognised input —
    caller is responsible for logging.
    """
    if not marker.startswith(MARKER_PREFIX + _SEP):
        return None

    parts = marker.split(_SEP)
    if len(parts) != _FIELD_COUNT:
        return None

    _, event_type, actor_id, actor_role, zone_label = parts

    if event_type not in VALID_EVENT_TYPES:
        return None
    if not actor_id.strip():
        return None
    if actor_role not in VALID_ACTOR_ROLES:
        return None
    if zone_label not in VALID_ZONE_LABELS:
        return None

    return {
        "event_type": event_type,
        "actor_id": actor_id.strip(),
        "actor_role": actor_role,
        "zone_label": zone_label,
    }


class ECHOThread(threading.Thread):
    """LSL Marker Stream listener — writes proximity state events to echo_events.

    Follows the same buffer-on-drop and reconnect pattern as the biosignal
    _StreamThread in lsl_forwarder. Every marker is written to XDF first,
    then to the DB — so events are never lost even if the DB is temporarily
    unavailable. If the marker stream is not found on startup (e.g. tablet
    not connected), the thread exits after the resolve timeout and biosignal
    capture continues unaffected.
    """

    def __init__(self, cfg, stop_event: threading.Event, xdf_writer) -> None:
        super().__init__(name="fwd_echo", daemon=True)
        self._cfg = cfg
        self._stop_event = stop_event
        self._xdf = xdf_writer
        self._buffer: list[dict] = []
        self._event_count = 0

    def run(self) -> None:
        try:
            self._run()
        except Exception as exc:
            log.error(
                "ECHO thread crashed — biosignal capture unaffected",
                extra={"error": str(exc)},
            )

    def _run(self) -> None:
        import pylsl  # deferred so import errors don't kill other threads

        log.info("ECHO thread starting")

        inlet = self._resolve_inlet(pylsl)
        if inlet is None:
            log.warning(
                "ECHO marker stream not found — thread exiting; "
                "no proximity events will be recorded for this session",
                extra={"stream_name": settings.LSL_STREAM_MARKER},
            )
            return

        conn = self._connect_db()
        if conn is None:
            log.error("ECHO could not establish DB connection — thread exiting")
            return

        while not self._stop_event.is_set():
            sample, lsl_ts = inlet.pull_sample(timeout=1.0)
            if not sample:
                continue

            raw = sample[0] if isinstance(sample, list) else sample
            parsed = parse_echo_marker(raw)

            if parsed is None:
                log.warning(
                    "ECHO unrecognised marker — skipped",
                    extra={"raw_marker": raw[:200]},
                )
                continue

            row = {
                "session_id": self._cfg.session_id,
                "participant_id": self._cfg.participant_id,
                "site_id": self._cfg.site_id,
                "sponsor_id": self._cfg.sponsor_id,
                "lsl_timestamp": lsl_ts,
                **parsed,
            }

            log.info(
                "ECHO proximity event",
                extra={
                    "zone_label": parsed["zone_label"],
                    "actor_id": parsed["actor_id"],
                    "actor_role": parsed["actor_role"],
                    "lsl_timestamp": round(lsl_ts, 6),
                    "session_id": self._cfg.session_id,
                },
            )

            # XDF write first — preserves the event even if DB is down
            self._xdf.write_marker(raw, lsl_ts)

            if conn is not None:
                if self._buffer:
                    conn = self._flush_buffer(conn)
                if conn is not None:
                    conn = self._write_row(conn, row)

            if conn is None:
                if len(self._buffer) < _BUFFER_MAX:
                    self._buffer.append(row)
                else:
                    log.error(
                        "ECHO buffer full — oldest event dropped",
                        extra={"buffer_depth": len(self._buffer)},
                    )
                    self._buffer.pop(0)
                    self._buffer.append(row)
                conn = self._try_reconnect()

        if conn and self._buffer:
            self._flush_buffer(conn)
        if conn:
            conn.close()
        log.info(
            "ECHO thread stopped",
            extra={"total_events": self._event_count},
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_inlet(self, pylsl):
        log.info(
            "ECHO resolving marker stream",
            extra={
                "stream_name": settings.LSL_STREAM_MARKER,
                "timeout_s": settings.LSL_RESOLVE_TIMEOUT,
            },
        )
        streams = pylsl.resolve_byprop(
            "name", settings.LSL_STREAM_MARKER, timeout=settings.LSL_RESOLVE_TIMEOUT
        )
        if not streams:
            return None
        inlet = pylsl.StreamInlet(streams[0])
        info = inlet.info()
        log.info(
            "ECHO inlet connected",
            extra={
                "stream_name": info.name(),
                "stream_type": info.type(),
                "simulation_mode": settings.SIMULATION_MODE,
            },
        )
        return inlet

    def _connect_db(self):
        backoff = 1.0
        while not self._stop_event.is_set():
            try:
                conn = psycopg2.connect(settings.DATABASE_URL)
                conn.autocommit = False
                log.info("ECHO DB connection established")
                return conn
            except psycopg2.OperationalError as exc:
                log.warning(
                    "ECHO DB connection failed — retrying",
                    extra={"retry_in_s": backoff, "error": str(exc)},
                )
                self._stop_event.wait(backoff)
                backoff = min(backoff * 2, 30.0)
        return None

    def _try_reconnect(self):
        try:
            conn = psycopg2.connect(settings.DATABASE_URL)
            conn.autocommit = False
            log.info(
                "ECHO DB reconnected",
                extra={"buffered_events": len(self._buffer)},
            )
            return conn
        except psycopg2.OperationalError:
            return None

    def _write_row(self, conn, row: dict):
        try:
            with conn.cursor() as cur:
                cur.execute(_ECHO_INSERT, row)
            conn.commit()
            self._event_count += 1
            return conn
        except psycopg2.OperationalError as exc:
            log.error(
                "ECHO DB write failed — connection dropped",
                extra={"error": str(exc)},
            )
            try:
                conn.close()
            except Exception:
                pass
            self._buffer.append(row)
            return None
        except psycopg2.Error as exc:
            log.error(
                "ECHO DB insert error",
                extra={"error": str(exc), "zone_label": row.get("zone_label")},
            )
            try:
                conn.rollback()
            except Exception:
                pass
            return conn

    def _flush_buffer(self, conn):
        flushed = 0
        while self._buffer and conn is not None:
            row = self._buffer[0]
            conn = self._write_row(conn, row)
            if conn is not None:
                self._buffer.pop(0)
                flushed += 1
        if flushed:
            log.info(
                "ECHO buffer flushed",
                extra={
                    "events_flushed": flushed,
                    "events_remaining": len(self._buffer),
                },
            )
        return conn
