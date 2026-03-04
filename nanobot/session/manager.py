"""In-memory session management for conversation turns.

Legacy file-based JSONL persistence has been removed.
Cognee is now the single source of truth for long-lived memory.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Session:
    """A runtime conversation session."""

    key: str  # channel:chat_id
    messages: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)
    last_consolidated: int = 0

    def add_message(self, role: str, content: str, **kwargs: Any) -> None:
        msg = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
            **kwargs,
        }
        self.messages.append(msg)
        self.updated_at = datetime.now()

    def get_history(self, max_messages: int = 500) -> list[dict[str, Any]]:
        """Return in-memory recent history aligned to a user turn."""
        sliced = self.messages[-max_messages:]

        for i, m in enumerate(sliced):
            if m.get("role") == "user":
                sliced = sliced[i:]
                break

        out: list[dict[str, Any]] = []
        for m in sliced:
            entry: dict[str, Any] = {"role": m["role"], "content": m.get("content", "")}
            for k in ("tool_calls", "tool_call_id", "name"):
                if k in m:
                    entry[k] = m[k]
            out.append(entry)
        return out

    def clear(self) -> None:
        self.messages = []
        self.last_consolidated = 0
        self.updated_at = datetime.now()


class SessionManager:
    """In-memory session manager.

    Persistence for memory is handled by Cognee.
    """

    def __init__(self, _workspace):
        self._cache: dict[str, Session] = {}

    def get_or_create(self, key: str) -> Session:
        if key not in self._cache:
            self._cache[key] = Session(key=key)
        return self._cache[key]

    def save(self, session: Session) -> None:
        # No file-based persistence.
        self._cache[session.key] = session

    def invalidate(self, key: str) -> None:
        self._cache.pop(key, None)

    def list_sessions(self) -> list[dict[str, Any]]:
        sessions = []
        for key, session in self._cache.items():
            sessions.append(
                {
                    "key": key,
                    "created_at": session.created_at.isoformat(),
                    "updated_at": session.updated_at.isoformat(),
                    "path": "",
                }
            )
        return sorted(sessions, key=lambda x: x.get("updated_at", ""), reverse=True)
