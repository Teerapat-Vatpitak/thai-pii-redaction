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

from pii_redactor.anonymizer.anonymizer import PIILeakError, anonymize
from pii_redactor.detectors.aggregate import detect_all
from pii_redactor.leak_guard import scan_outbound_leaks
from pii_redactor.models import Entity, EntityRegistry
from pii_redactor.report import scan_section26
from pii_redactor.session_vault import SessionVault


class SessionExpiredError(Exception):
    """Unknown or idle-expired session."""


class ModeMismatchError(Exception):
    """Requested mode conflicts with the session's locked mode."""


class OutboundLeakError(Exception):
    """Anonymization could not guarantee a leak-free output. NO PII in message."""

    def __init__(self, leak_types: list[str]):
        self.leak_types = leak_types
        super().__init__(f"outbound leak risk: {leak_types}")


@dataclass
class SanitizeOutcome:
    session_id: str
    original_text: str
    sanitized_text: str
    entities: list[dict]
    entity_type_counts: dict[str, int]
    section26: list[dict]
    warnings: list[str]


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

        # Validate mode BEFORE eviction so malformed requests have no side effects.
        resolved_mode = mode or "token"
        if resolved_mode not in ("token", "surrogate"):
            raise ModeMismatchError(f"unknown mode '{resolved_mode}'")

        if len(self._sessions) >= self._cap:
            oldest = min(self._sessions, key=lambda k: self._sessions[k].created)
            self.drop(oldest)
        sid = str(uuid.uuid4())
        now = self._now()
        # vault idle timeout mirrors the service TTL; the service check fires
        # first in practice because both reset on access
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

    def sanitize(
        self,
        text: str,
        *,
        mode: str | None = None,
        session_id: str | None = None,
    ) -> SanitizeOutcome:
        sid, session = self._get_or_create(session_id, mode)

        turn_entities = detect_all(text)
        registry = EntityRegistry(
            entities=turn_entities,
            fp_count=sum(1 for e in turn_entities if e.redact_type == "FP"),
            tb_count=sum(1 for e in turn_entities if e.redact_type == "TB"),
        )
        try:
            pseudo = anonymize(
                text, registry, session.vault,
                salt=session.salt, mode=session.mode,
            )
        except (PIILeakError, ValueError) as e:
            # mask failed — never return the text
            raise OutboundLeakError([type(e).__name__]) from e

        warnings: list[str] = []
        leaks = scan_outbound_leaks(pseudo.text, session.vault)
        fp_leaks = [e for e in leaks if e.redact_type == "FP"]
        if fp_leaks:
            raise OutboundLeakError(sorted({e.data_type for e in fp_leaks}))
        # only register this turn once the guard has cleared the output
        session.entities.extend(turn_entities)
        warnings.extend(
            f"possible_tb_leak:{e.data_type}"
            for e in leaks if e.redact_type != "FP"
        )

        out_entities = []
        for e in turn_entities:
            record = session.vault.get_by_entity_id(e.entity_id)
            out_entities.append({
                "start": e.span[0], "end": e.span[1],
                "data_type": e.data_type, "redact_type": e.redact_type,
                "token": record.pseudonym if record else "",
            })
        type_counts: dict[str, int] = {}
        for e in out_entities:
            type_counts[e["data_type"]] = type_counts.get(e["data_type"], 0) + 1

        return SanitizeOutcome(
            session_id=sid,
            original_text=text,
            sanitized_text=pseudo.text,
            entities=out_entities,
            entity_type_counts=type_counts,
            section26=scan_section26(text),
            warnings=warnings,
        )
