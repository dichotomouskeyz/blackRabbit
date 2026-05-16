"""Buffered ECHO event database writer."""

from collections import deque
from typing import Any

from capture.echo_handler import db
from capture.logger import get_logger

log = get_logger("echo_handler")

BUFFER_MAX = 100


class ECHOWriter:
    def __init__(self) -> None:
        self.buffer: deque[dict[str, Any]] = deque(maxlen=BUFFER_MAX)
        self.event_count = 0

    def write_or_buffer(self, conn, row: dict[str, Any]):
        if conn is not None:
            if self.buffer:
                conn = self.flush_buffer(conn)
            if conn is not None:
                conn = self.write_row(conn, row)

        if conn is None:
            self.buffer_row(row)
        return conn

    def buffer_row(self, row: dict[str, Any]) -> None:
        dropped = len(self.buffer) == self.buffer.maxlen
        if dropped:
            log.error(
                "ECHO buffer full — oldest event dropped",
                extra={"buffer_depth": len(self.buffer)},
            )
        self.buffer.append(row)

    def write_row(self, conn, row: dict):
        conn, wrote = db.write_row(conn, row)
        if wrote:
            self.event_count += 1
        return conn

    def flush_buffer(self, conn):
        flushed = 0
        while self.buffer and conn is not None:
            row = self.buffer[0]
            conn = self.write_row(conn, row)
            if conn is not None:
                self.buffer.popleft()
                flushed += 1
        if flushed:
            log.info(
                "ECHO buffer flushed",
                extra={
                    "events_flushed": flushed,
                    "events_remaining": len(self.buffer),
                },
            )
        return conn
