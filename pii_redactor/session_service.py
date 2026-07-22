"""Session facade unifying the web path onto the core pipeline components.

One brain: SessionVault + accumulated EntityRegistry + per-session salt/mode,
with the same cap/TTL policy the old app/server.py _SESSIONS dict had.
Owns session lifecycle plus the sanitize/restore flows.

SECURITY: sessions live in memory only; dropping/evicting a session always
null-byte-clears its vault first.
"""

from __future__ import annotations

import secrets
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

from pii_redactor.leak_guard import scan_outbound_leaks
from pii_redactor.models import AIResponse, Entity, EntityRegistry
from pii_redactor.output_validator import PIILeakError as OutputPIILeakError
from pii_redactor.output_validator import validate_output
from pii_redactor.report import scan_section26
from pii_redactor.reverse_mapper import reverse_map
from pii_redactor.session_vault import SessionVault, VaultTimeoutError
from pii_redactor.stateless import StatelessLeakError, sanitize_into_vault


class SessionExpiredError(Exception):
    """Unknown or idle-expired session."""


class ModeMismatchError(Exception):
    """Requested mode conflicts with the session's locked mode."""


# Flags with these prefixes are informational only on the inbound (restore)
# direction — the client already gets the same signal via replaced_count/
# leftover_tokens, and both flags are noisy on a normal chat reply:
# incomplete_reverse compares unique-pseudonyms-replaced against accumulated
# entity-instance count (fires even on a perfect restore), and
# possible_truncation is a layer-3 heuristic aimed at final documents (chat
# replies routinely lack terminal punctuation).
_NOISY_PREFIXES = ("incomplete_reverse:", "possible_truncation:")


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
class RestoreOutcome:
    restored_text: str
    replaced: list[dict]  # {"token": pseudonym, "original": original} — v2 shape
    replaced_count: int
    leftover_tokens: list[str]
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
        # FastAPI runs sync endpoints in a threadpool, so every public entry
        # point serializes on this lock: without it, drop/evict null-byte-clears
        # a vault another thread is mid-restore on. RLock because sanitize/
        # restore call drop() on their expiry paths while already holding it.
        self._lock = threading.RLock()

    @property
    def session_count(self) -> int:
        return len(self._sessions)

    def _get_or_create(self, session_id: str | None, mode: str | None) -> tuple[str, _Session]:
        with self._lock:
            return self._get_or_create_locked(session_id, mode)

    def _get_or_create_locked(
        self, session_id: str | None, mode: str | None
    ) -> tuple[str, _Session]:
        if session_id is not None:
            session = self._sessions.get(session_id)
            if session is None or self._now() - session.last_access > self._ttl_s:
                if session is not None:
                    self.drop(session_id)
                raise SessionExpiredError("Session not found or expired")
            if mode is not None and mode != session.mode:
                raise ModeMismatchError(f"session mode is '{session.mode}', got '{mode}'")
            session.last_access = self._now()
            return session_id, session

        # Validate mode BEFORE eviction so malformed requests have no side effects.
        resolved_mode = mode or "token"
        if resolved_mode not in ("token", "surrogate"):
            raise ModeMismatchError(f"unknown mode '{resolved_mode}'")

        if len(self._sessions) >= self._cap:
            # LRU victim: least-recently-used, never the oldest-created — an
            # old but active session must survive (VAULT-2). A TTL-expired
            # session is by definition the least recently accessed, so it is
            # always evicted first.
            lru = min(self._sessions, key=lambda k: self._sessions[k].last_access)
            self.drop(lru)
        sid = str(uuid.uuid4())
        now = self._now()
        # vault idle timeout mirrors the service TTL as a second layer; if the
        # vault trips first (it only refreshes on vault access), sanitize/
        # restore translate it to SessionExpiredError.
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
        with self._lock:
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
        with self._lock:
            return self._sanitize_locked(text, mode=mode, session_id=session_id)

    def _sanitize_locked(
        self,
        text: str,
        *,
        mode: str | None,
        session_id: str | None,
    ) -> SanitizeOutcome:
        sid, session = self._get_or_create_locked(session_id, mode)

        try:
            try:
                # Same body the platform's stateless entry point runs; the only
                # difference is that the vault handed over here is the session's
                # and outlives the call. scan_outbound_leaks is passed
                # explicitly so this module's reference is the one used.
                core = sanitize_into_vault(
                    text,
                    session.vault,
                    mode=session.mode,
                    salt=session.salt,
                    scan_leaks=scan_outbound_leaks,
                )
            except StatelessLeakError as e:
                raise OutboundLeakError(e.leak_types) from e

            # only register this turn once the guard has cleared the output
            session.entities.extend(core.detected)

            return SanitizeOutcome(
                session_id=sid,
                original_text=text,
                sanitized_text=core.sanitized_text,
                entities=core.entities,
                entity_type_counts=core.entity_type_counts,
                section26=scan_section26(text),
                warnings=core.warnings,
            )
        except VaultTimeoutError:
            self.drop(sid)
            raise SessionExpiredError("Session not found or expired") from None

    def restore(self, session_id: str, text: str) -> RestoreOutcome:
        with self._lock:
            return self._restore_locked(session_id, text)

    def _restore_locked(self, session_id: str, text: str) -> RestoreOutcome:
        sid, session = self._get_or_create_locked(session_id, None)
        if not text or not text.strip():
            return RestoreOutcome(
                restored_text=text,
                replaced=[],
                replaced_count=0,
                leftover_tokens=[],
                warnings=[],
            )
        try:
            registry = EntityRegistry(
                entities=session.entities,
                fp_count=sum(1 for e in session.entities if e.redact_type == "FP"),
                tb_count=sum(1 for e in session.entities if e.redact_type == "TB"),
            )
            response = AIResponse(text=text, request_id=sid, latency=0.0)
            reverse_result = reverse_map(response, registry, session.vault)

            warnings = [f for f in reverse_result.flags if not f.startswith(_NOISY_PREFIXES)]
            try:
                validation = validate_output(reverse_result, registry, session.vault)
                warnings.extend(
                    f
                    for f in validation.flags
                    if f not in warnings and not f.startswith(_NOISY_PREFIXES)
                )
            except OutputPIILeakError:
                # inbound direction: the AI fabricated PII-looking data — warn only
                warnings.append("ai_generated_pii")

            replaced_pseudonyms = reverse_result.audit_summary.get("replaced_pseudonyms", [])
            replaced = []
            for pseudonym in replaced_pseudonyms:
                record = session.vault.get_by_pseudonym(pseudonym)
                if record is not None:
                    replaced.append({"token": pseudonym, "original": record.original})

            leftover = [p for p in session.vault._reverse if p in reverse_result.text]
            return RestoreOutcome(
                restored_text=reverse_result.text,
                replaced=replaced,
                replaced_count=len(replaced),
                leftover_tokens=leftover,
                warnings=warnings,
            )
        except VaultTimeoutError:
            self.drop(sid)
            raise SessionExpiredError("Session not found or expired") from None
