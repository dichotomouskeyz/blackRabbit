"""Bounded server-owned conversation state for the single-process local demo."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable
from uuid import uuid4

from investigation.models import InvestigationError


@dataclass
class Conversation:
    id: str
    sponsor_id: str
    site_id: str
    session_id: str
    touched: float
    tools: Any = None
    turns: list[list[Any]] = field(default_factory=list)
    busy: bool = True

    @property
    def history(self) -> list[Any]:
        return [message for turn in self.turns for message in turn]


class ConversationStore:
    """Atomic acquisition rejects overlapping turns, including during setup.

    Complete SDK turns are the retention unit. A turn exceeding the message
    budget is not retained, avoiding orphaned tool calls or results. Failed or
    cancelled conversations are discarded so a still-finishing bounded worker
    cannot race a later turn using the same evidence registry.
    """

    def __init__(
        self,
        *,
        ttl_seconds: float = 1800,
        max_conversations: int = 64,
        max_messages: int = 20,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_conversations = max_conversations
        self.max_messages = max_messages
        self.clock = clock
        self._items: dict[str, Conversation] = {}
        self._lock = threading.Lock()

    def acquire(
        self, sponsor_id: str, site_id: str, session_id: str, conversation_id: str | None = None
    ) -> Conversation:
        with self._lock:
            now = self.clock()
            self._items = {
                key: item
                for key, item in self._items.items()
                if now - item.touched < self.ttl_seconds
            }
            if conversation_id is not None:
                item = self._items.get(conversation_id)
                if item is None or (item.sponsor_id, item.site_id, item.session_id) != (
                    sponsor_id,
                    site_id,
                    session_id,
                ):
                    raise InvestigationError(
                        "conversation_not_found", "Conversation is unavailable or expired.", 404
                    )
                if item.busy:
                    raise InvestigationError(
                        "conversation_busy", "A turn is already running for this conversation."
                    )
                item.busy = True
                item.touched = now
                return item
            if len(self._items) >= self.max_conversations:
                raise InvestigationError(
                    "conversation_capacity", "Conversation capacity reached; retry later.", 503
                )
            item = Conversation(str(uuid4()), sponsor_id, site_id, session_id, now)
            self._items[item.id] = item
            return item

    def finish(self, item: Conversation, messages: list[Any]) -> None:
        with self._lock:
            item.turns.append(list(messages))
            while sum(map(len, item.turns)) > self.max_messages:
                item.turns.pop(0)
            item.touched = self.clock()
            item.busy = False

    def discard(self, item: Conversation) -> None:
        with self._lock:
            self._items.pop(item.id, None)
