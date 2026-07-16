"""Session facade unifying the web path onto the core pipeline components.

One brain: SessionVault + accumulated EntityRegistry + per-session salt/mode,
with the same cap/TTL policy the old app/server.py _SESSIONS dict had.
Sanitize/restore logic arrives in later tasks; this module owns lifecycle.

SECURITY: sessions live in memory only; dropping/evicting a session always
null-byte-clears its vault first.
"""
from __future__ import annotations

import secrets
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable

from pii_redactor.models import Entity
from pii_redactor.session_vault import SessionVault


class SessionExpiredError(Exception):
    """Unknown or idle-expired session."""


class ModeMismatchError(Exception):
    """Requested mode conflicts with the session's locked mode."""


@dataclass
class _Session:
    vault: SessionVault
    mode: str
    salt: str
    created: float
    last_access: float
    entities: list[Entity] = field(default_factory=list)


class SessionService:
    def __init__(
        self,
        *,
        cap: int = 200,
        ttl_s: int = 1800,
        now_fn: Callable[[], float] = time.monotonic,
    ):
        self._sessions: dict[str, _Session] = {}
        self._cap = cap
        self._ttl_s = ttl_s
        self._now = now_fn

    @property
    def session_count(self) -> int:
        return len(self._sessions)

    def _get_or_create(
        self, session_id: str | None, mode: str | None
    ) -> tuple[str, _Session]:
        if session_id is not None:
            session = self._sessions.get(session_id)
            if session is None or self._now() - session.last_access > self._ttl_s:
                if session is not None:
                    self.drop(session_id)
                raise SessionExpiredError("Session not found or expired")
            if mode is not None and mode != session.mode:
                raise ModeMismatchError(
                    f"session mode is '{session.mode}', got '{mode}'"
                )
            session.last_access = self._now()
            return session_id, session

        if len(self._sessions) >= self._cap:
            oldest = min(self._sessions, key=lambda k: self._sessions[k].created)
            self.drop(oldest)
        sid = str(uuid.uuid4())
        now = self._now()
        # vault idle timeout mirrors the service TTL; the service check fires
        # first in practice because both reset on access
        resolved_mode = mode or "token"
        if resolved_mode not in ("token", "surrogate"):
            raise ModeMismatchError(f"unknown mode '{resolved_mode}'")
        session = _Session(
            vault=SessionVault(idle_timeout_s=self._ttl_s),
            mode=resolved_mode,
            salt=secrets.token_hex(16),
            created=now,
            last_access=now,
        )
        self._sessions[sid] = session
        return sid, session

    def drop(self, session_id: str) -> bool:
        session = self._sessions.pop(session_id, None)
        if session is None:
            return False
        session.vault.clear()
        return True
