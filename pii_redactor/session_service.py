"""Session facade unifying the web path onto the core pipeline components.

One brain: SessionVault + accumulated EntityRegistry + per-session salt/mode,
with the same cap/TTL policy the old app/server.py _SESSIONS dict had.
Owns session lifecycle plus the sanitize/restore flows.

SECURITY: sessions live in memory only. Dropping or replacing a published
session removes the service-owned reference and invokes the vault cleanup path;
Python immutable strings cannot be guaranteed to be zeroized.
"""

from __future__ import annotations

import logging
import secrets
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TypeVar

from pii_redactor.leak_guard import scan_outbound_leaks
from pii_redactor.models import AIResponse, Entity, EntityRegistry
from pii_redactor.output_validator import PIILeakError as OutputPIILeakError
from pii_redactor.output_validator import validate_output
from pii_redactor.report import scan_section26
from pii_redactor.reverse_mapper import reverse_map
from pii_redactor.session_vault import SessionVault, VaultTimeoutError
from pii_redactor.stateless import StatelessLeakError, sanitize_into_vault

_LOG = logging.getLogger(__name__)
_ResultT = TypeVar("_ResultT")


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


def _identity_finalize(outcome: SanitizeOutcome) -> SanitizeOutcome:
    return outcome


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
        # point serializes on this lock: without it, drop/evict can clear vault
        # lookup state while another thread is mid-restore. RLock because sanitize/
        # restore call drop() on their expiry paths while already holding it.
        # Deliberately coarse — it serializes heavy NER work across sessions,
        # but only the localhost extension (one user) goes through this class;
        # the concurrent-traffic paths (/api/roundtrip, the platform worker)
        # are stateless and never touch it. A per-session lock would add
        # deadlock surface for no real-world gain.
        self._lock = threading.RLock()

    @property
    def session_count(self) -> int:
        with self._lock:
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
        return self.sanitize_transaction(
            text,
            mode=mode,
            session_id=session_id,
            finalize=_identity_finalize,
        )

    def sanitize_transaction(
        self,
        text: str,
        *,
        mode: str | None = None,
        session_id: str | None = None,
        finalize: Callable[[SanitizeOutcome], _ResultT],
    ) -> _ResultT:
        """Prepare, finalize, then atomically publish one sanitize turn.

        `finalize` runs under the same coarse lock and receives only the public
        outcome. A caller can finish response projection, encoding, and required
        audit work there. Any exception before the final dictionary assignment
        leaves the published session graph unchanged, except that a genuine
        staged-vault expiry disposes the expired published session. The callback
        must not re-enter this service or mutate its private session graph.
        """
        with self._lock:
            sid, staged, is_new = self._stage_sanitize_locked(session_id, mode)
            try:
                try:
                    # Same body the platform's stateless entry point runs; the
                    # detached vault becomes live only after every later stage
                    # succeeds. This module's guard reference stays injectable.
                    core = sanitize_into_vault(
                        text,
                        staged.vault,
                        mode=staged.mode,
                        salt=staged.salt,
                        scan_leaks=scan_outbound_leaks,
                    )
                except StatelessLeakError as e:
                    raise OutboundLeakError(e.leak_types) from e
                except VaultTimeoutError:
                    # Confirm provenance before treating this exception name as
                    # lifecycle expiry. An injected detector/finalizer can
                    # coincidentally raise the same public exception type.
                    if not staged.vault.is_idle():
                        raise
                    if not is_new:
                        self.drop(sid)
                    raise SessionExpiredError("Session not found or expired") from None

                staged.entities.extend(core.detected)
                outcome = SanitizeOutcome(
                    session_id=sid,
                    original_text=text,
                    sanitized_text=core.sanitized_text,
                    entities=core.entities,
                    entity_type_counts=core.entity_type_counts,
                    section26=scan_section26(text),
                    warnings=core.warnings,
                )
                prepared = finalize(outcome)
                discarded = self._publish_sanitize_locked(sid, staged, is_new=is_new)
            except Exception:
                self._discard_detached(staged)
                raise

            if discarded is not None:
                self._discard_detached(discarded)
            return prepared

    def _stage_sanitize_locked(
        self,
        session_id: str | None,
        mode: str | None,
    ) -> tuple[str, _Session, bool]:
        """Build a detached target without touching or evicting live state."""
        now = self._now()
        if session_id is not None:
            published = self._sessions.get(session_id)
            if published is None or now - published.last_access > self._ttl_s:
                if published is not None:
                    self.drop(session_id)
                raise SessionExpiredError("Session not found or expired")
            if mode is not None and mode != published.mode:
                raise ModeMismatchError(f"session mode is '{published.mode}', got '{mode}'")
            staged = _Session(
                vault=published.vault.clone(),
                mode=published.mode,
                salt=published.salt,
                created=published.created,
                last_access=now,
                # Entity is immutable, so a detached list can safely share
                # prior records and append only this turn's detections.
                entities=list(published.entities),
            )
            return session_id, staged, False

        resolved_mode = mode or "token"
        if resolved_mode not in ("token", "surrogate"):
            raise ModeMismatchError(f"unknown mode '{resolved_mode}'")
        sid = str(uuid.uuid4())
        staged = _Session(
            vault=SessionVault(idle_timeout_s=self._ttl_s),
            mode=resolved_mode,
            salt=secrets.token_hex(16),
            created=now,
            last_access=now,
        )
        return sid, staged, True

    def _publish_sanitize_locked(
        self,
        sid: str,
        staged: _Session,
        *,
        is_new: bool,
    ) -> _Session | None:
        """Publish with one assignment after building the complete next graph."""
        next_sessions = dict(self._sessions)
        discarded: _Session | None = None
        if is_new:
            if len(next_sessions) >= self._cap:
                lru = min(self._sessions, key=lambda key: self._sessions[key].last_access)
                discarded = next_sessions.pop(lru)
        else:
            discarded = next_sessions.get(sid)
        next_sessions[sid] = staged
        self._sessions = next_sessions
        return discarded

    @staticmethod
    def _discard_detached(session: _Session) -> None:
        """Release detached or displaced vault data without changing outcomes."""
        try:
            session.vault.clear()
        except Exception:
            # The service reference is already absent (or was never published).
            # Do not turn a completed commit into a caller-visible failure.
            _LOG.error("Session vault cleanup did not complete")

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
