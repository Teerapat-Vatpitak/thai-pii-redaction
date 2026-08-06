"""Session facade unifying the web path onto the core pipeline components.

One brain: SessionVault + accumulated EntityRegistry + per-session salt/mode,
with the same cap/TTL policy the old app/server.py _SESSIONS dict had.
Owns session lifecycle plus the sanitize/restore flows.

SECURITY: sessions live in memory only. Dropping or replacing a published
session removes the service-owned reference and invokes the vault cleanup path;
Python immutable strings cannot be guaranteed to be zeroized.
"""

from __future__ import annotations

import hashlib
import logging
import math
import secrets
import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol, TypeVar

from pii_redactor.leak_guard import (
    OutboundPolicyError,
    scan_outbound_leaks,
    scan_residual_signals,
)
from pii_redactor.models import (
    AIResponse,
    Entity,
    EntityRegistry,
    ReplacementHighlight,
)
from pii_redactor.output_validator import PIILeakError as OutputPIILeakError
from pii_redactor.output_validator import validate_output
from pii_redactor.report import scan_section26
from pii_redactor.reverse_mapper import reverse_map
from pii_redactor.safe_errors import discard_exception_graph
from pii_redactor.session_vault import SessionVault, VaultTimeoutError
from pii_redactor.stateless import StatelessLeakError, sanitize_into_vault

_LOG = logging.getLogger(__name__)
_ResultT = TypeVar("_ResultT")
_TRUSTED_SANITIZED_DIGEST_LIMIT = 8


class SessionExpiredError(Exception):
    """Unknown or idle-expired session."""


class ModeMismatchError(Exception):
    """Requested mode conflicts with the session's locked mode."""


class SanitizeTransactionError(RuntimeError):
    """A sanitize stage failed without exposing its exception object graph."""


class RestoreTransactionError(RuntimeError):
    """A restore stage failed without exposing its exception object graph."""


class DisposalAuthorizationError(Exception):
    """A verified disposal authorization is invalid or already consumed."""


class _ExpiryTimer(Protocol):
    def start(self) -> None: ...

    def cancel(self) -> None: ...


_TimerFactory = Callable[[float, Callable[[], None]], _ExpiryTimer]


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

    def __init__(
        self,
        leak_types: list[str],
        *,
        policy_categories: list[str] | set[str] | tuple[str, ...] = (),
    ):
        normalized = OutboundPolicyError(
            leak_types,
            policy_categories=policy_categories,
        )
        self.leak_types = normalized.leak_types
        self.policy_categories = normalized.policy_categories
        self.category_count = normalized.category_count
        self.policy_category_count = self.category_count
        super().__init__(f"outbound residual risk: {self.leak_types}")


@dataclass
class SanitizeOutcome:
    session_id: str
    original_text: str
    sanitized_text: str
    entities: list[dict]
    entity_type_counts: dict[str, int]
    section26: list[dict]
    warnings: list[str]
    replacement_highlights: tuple[ReplacementHighlight, ...] = ()


def _identity_finalize(outcome: SanitizeOutcome) -> SanitizeOutcome:
    return outcome


@dataclass
class RestoreOutcome:
    restored_text: str
    replaced_count: int
    leftover_tokens: list[str]
    warnings: list[str]
    generated_pii_count: int = 0
    foreign_replacement_count: int = 0


@dataclass
class _Session:
    vault: SessionVault
    mode: str
    salt: str
    created: float
    last_access: float
    entities: list[Entity] = field(default_factory=list)
    trusted_sanitized_digests: tuple[bytes, ...] = ()


def _sanitized_digest(text: str) -> bytes:
    return hashlib.sha256(text.encode("utf-8")).digest()


class SessionService:
    def __init__(
        self,
        *,
        cap: int = 200,
        ttl_s: int = 1800,
        now_fn: Callable[[], float] = time.monotonic,
        timer_factory: _TimerFactory | None = None,
    ):
        self._sessions: dict[str, _Session] = {}
        self._cap = cap
        self._ttl_s = ttl_s
        self._now = now_fn
        self._timer_factory = timer_factory
        self._expiry_timer: _ExpiryTimer | None = None
        self._timer_generation = 0
        self._closed = False
        self._used_disposal_authorizations: OrderedDict[bytes, int] = OrderedDict()
        self._authorization_cache_limit = max(256, cap * 4)
        self._lifecycle_tombstones: OrderedDict[bytes, None] = OrderedDict()
        self._tombstone_limit = max(256, cap * 4)
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

    @staticmethod
    def _is_expired(session: _Session, now: float, ttl_s: int) -> bool:
        return now - session.last_access >= ttl_s

    def _ensure_open_locked(self) -> None:
        if self._closed:
            raise SessionExpiredError("Session service is closed")

    def _cancel_expiry_timer_locked(self) -> _ExpiryTimer | None:
        timer = self._expiry_timer
        self._expiry_timer = None
        self._timer_generation += 1
        if timer is not None:
            try:
                timer.cancel()
            except Exception as error:
                discard_exception_graph(error)
                _LOG.error("Session expiry timer cancellation did not complete")
        return timer

    def _fail_closed_locked(self) -> list[_Session]:
        """Close lifecycle admission and detach all retained session state."""
        doomed = list(self._sessions.values())
        self._sessions = {}
        self._expiry_timer = None
        self._closed = True
        self._timer_generation += 1
        self._used_disposal_authorizations.clear()
        self._lifecycle_tombstones.clear()
        return doomed

    def _reschedule_expiry_locked(self) -> None:
        self._cancel_expiry_timer_locked()
        if self._closed or self._timer_factory is None or not self._sessions:
            return

        try:
            deadlines = [session.last_access + self._ttl_s for session in self._sessions.values()]
            if any(
                isinstance(deadline, bool)
                or not isinstance(deadline, (int, float))
                or not math.isfinite(deadline)
                for deadline in deadlines
            ):
                raise ValueError("invalid lifecycle deadline")
            next_deadline = min(deadlines)
            now = self._now()
            if isinstance(now, bool) or not isinstance(now, (int, float)) or not math.isfinite(now):
                raise ValueError("invalid lifecycle clock")
            delay = max(0.0, next_deadline - now)
            if not math.isfinite(delay):
                raise ValueError("invalid lifecycle delay")
            generation = self._timer_generation
            timer = self._timer_factory(
                delay,
                lambda: self._expiry_timer_fired(generation),
            )
            self._expiry_timer = timer
            timer.start()
        except Exception as error:
            discard_exception_graph(error)
            doomed = self._fail_closed_locked()
            for session in doomed:
                self._discard_detached(session)
            _LOG.error("Session expiry scheduling failed; service closed")
            raise SessionExpiredError("Session service is closed") from None

    def _take_expired_locked(self, now: float) -> list[_Session]:
        expired_ids = [
            session_id
            for session_id, session in self._sessions.items()
            if self._is_expired(session, now, self._ttl_s)
        ]
        if not expired_ids:
            return []
        next_sessions = dict(self._sessions)
        expired = [next_sessions.pop(session_id) for session_id in expired_ids]
        for session_id in expired_ids:
            self._remember_tombstone_locked(session_id)
        self._sessions = next_sessions
        return expired

    def _remember_tombstone_locked(self, session_id: str) -> None:
        key = hashlib.sha256(b"aiguard-session-tombstone\0" + session_id.encode("utf-8")).digest()
        self._lifecycle_tombstones[key] = None
        self._lifecycle_tombstones.move_to_end(key)
        while len(self._lifecycle_tombstones) > self._tombstone_limit:
            self._lifecycle_tombstones.popitem(last=False)

    def _has_tombstone_locked(self, session_id: str) -> bool:
        key = hashlib.sha256(b"aiguard-session-tombstone\0" + session_id.encode("utf-8")).digest()
        return key in self._lifecycle_tombstones

    def _expiry_timer_fired(self, generation: int) -> None:
        expired: list[_Session] = []
        try:
            with self._lock:
                if (
                    self._closed
                    or generation != self._timer_generation
                    or self._expiry_timer is None
                ):
                    return
                try:
                    self._expiry_timer = None
                    now = self._now()
                    if (
                        isinstance(now, bool)
                        or not isinstance(now, (int, float))
                        or not math.isfinite(now)
                    ):
                        raise ValueError("invalid lifecycle clock")
                    expired = self._take_expired_locked(now)
                    self._reschedule_expiry_locked()
                except Exception as error:
                    discard_exception_graph(error)
                    if not self._closed:
                        expired.extend(self._fail_closed_locked())
                        _LOG.error("Session expiry callback failed; service closed")
        finally:
            for session in expired:
                self._discard_detached(session)

    def expire_due(self) -> int:
        """Expire every due session now without waiting for a client request."""
        expired: list[_Session] = []
        try:
            with self._lock:
                if self._closed:
                    return 0
                expired = self._take_expired_locked(self._now())
                self._reschedule_expiry_locked()
        finally:
            for session in expired:
                self._discard_detached(session)
        return len(expired)

    def close(self) -> None:
        """Cancel lifecycle work and release every session-owned reference."""
        with self._lock:
            if (
                self._closed
                and not self._sessions
                and not self._used_disposal_authorizations
                and not self._lifecycle_tombstones
            ):
                return
            self._closed = True
            self._cancel_expiry_timer_locked()
            sessions = list(self._sessions.values())
            self._sessions = {}
            self._used_disposal_authorizations.clear()
            self._lifecycle_tombstones.clear()
        for session in sessions:
            self._discard_detached(session)

    def _get_or_create(self, session_id: str | None, mode: str | None) -> tuple[str, _Session]:
        with self._lock:
            return self._get_or_create_locked(session_id, mode)

    def _get_or_create_locked(
        self, session_id: str | None, mode: str | None
    ) -> tuple[str, _Session]:
        self._ensure_open_locked()
        if session_id is not None:
            session, admitted_at = self._get_existing_locked(session_id, mode)
            session.last_access = admitted_at
            self._reschedule_expiry_locked()
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
        # The service is the sole TTL authority for managed vaults. Standalone
        # SessionVault instances retain their own idle expiry.
        session = _Session(
            vault=SessionVault(idle_timeout_s=None),
            mode=resolved_mode,
            salt=secrets.token_hex(16),
            created=now,
            last_access=now,
        )
        self._sessions[sid] = session
        self._reschedule_expiry_locked()
        return sid, session

    def _get_existing_locked(
        self,
        session_id: str,
        mode: str | None,
    ) -> tuple[_Session, float]:
        """Admit an existing session without refreshing its deadline."""
        self._ensure_open_locked()
        session = self._sessions.get(session_id)
        now = self._now()
        if session is None or self._is_expired(session, now, self._ttl_s):
            if session is not None:
                self.drop(session_id)
            raise SessionExpiredError("Session not found or expired")
        if mode is not None and mode != session.mode:
            raise ModeMismatchError(f"session mode is '{session.mode}', got '{mode}'")
        return session, now

    def drop(self, session_id: str) -> bool:
        session = None
        try:
            with self._lock:
                session = self._sessions.pop(session_id, None)
                if session is None:
                    return False
                self._remember_tombstone_locked(session_id)
                self._reschedule_expiry_locked()
        finally:
            if session is not None:
                self._discard_detached(session)
        return True

    def dispose_authenticated(
        self,
        session_id: str,
        *,
        authorization_fingerprint: bytes,
        authorization_expires_at_ms: int,
        authorization_now_ms_fn: Callable[[], float],
    ) -> bool:
        """Consume one verified authority and dispose only its target session."""
        if (
            not isinstance(authorization_fingerprint, bytes)
            or len(authorization_fingerprint) != hashlib.sha256().digest_size
            or type(authorization_expires_at_ms) is not int
            or not callable(authorization_now_ms_fn)
        ):
            raise DisposalAuthorizationError("invalid disposal authorization")

        expired: list[_Session] = []
        disposed = None
        unknown_target = False
        try:
            with self._lock:
                self._ensure_open_locked()
                try:
                    authorization_now_ms = authorization_now_ms_fn()
                except Exception as error:
                    discard_exception_graph(error)
                    raise DisposalAuthorizationError("invalid disposal authorization") from None
                if (
                    isinstance(authorization_now_ms, bool)
                    or not isinstance(authorization_now_ms, (int, float))
                    or not math.isfinite(authorization_now_ms)
                    or authorization_expires_at_ms <= authorization_now_ms
                ):
                    raise DisposalAuthorizationError("invalid disposal authorization")
                expired_keys = [
                    fingerprint
                    for fingerprint, expires_at in (self._used_disposal_authorizations.items())
                    if expires_at <= authorization_now_ms
                ]
                for fingerprint in expired_keys:
                    self._used_disposal_authorizations.pop(fingerprint, None)
                if authorization_fingerprint in self._used_disposal_authorizations:
                    raise DisposalAuthorizationError("disposal authorization replayed")
                if len(self._used_disposal_authorizations) >= self._authorization_cache_limit:
                    raise DisposalAuthorizationError("disposal authorization cache full")
                self._used_disposal_authorizations[authorization_fingerprint] = (
                    authorization_expires_at_ms
                )

                expired = self._take_expired_locked(self._now())
                disposed = self._sessions.pop(session_id, None)
                if disposed is not None:
                    self._remember_tombstone_locked(session_id)
                elif not self._has_tombstone_locked(session_id):
                    unknown_target = True
                self._reschedule_expiry_locked()
        finally:
            for session in expired:
                self._discard_detached(session)
            if disposed is not None:
                self._discard_detached(disposed)
        if unknown_target:
            raise SessionExpiredError("Session not found or expired")
        return disposed is not None

    def sanitize(
        self,
        text: str,
        *,
        mode: str | None = None,
        session_id: str | None = None,
    ) -> SanitizeOutcome:
        failure_kind = None
        failure = None
        try:
            return self.sanitize_transaction(
                text,
                mode=mode,
                session_id=session_id,
                finalize=_identity_finalize,
            )
        except OutboundLeakError as error:
            failure_kind = "residual"
            failure = (list(error.leak_types), list(error.policy_categories))
            discard_exception_graph(error)
        except SessionExpiredError as error:
            failure_kind = "expired"
            discard_exception_graph(error)
        except ModeMismatchError as error:
            failure_kind = "mode"
            discard_exception_graph(error)
        except SanitizeTransactionError as error:
            failure_kind = "failed"
            discard_exception_graph(error)
        self = None
        text = ""
        mode = None
        session_id = None
        if failure_kind == "residual":
            safe_leak_types, safe_categories = failure
            raise OutboundLeakError(
                safe_leak_types,
                policy_categories=safe_categories,
            )
        if failure_kind == "expired":
            raise SessionExpiredError("Session not found or expired")
        if failure_kind == "mode":
            raise ModeMismatchError("session mode mismatch")
        raise SanitizeTransactionError("sanitize transaction failed")

    def sanitize_transaction(
        self,
        text: str,
        *,
        mode: str | None = None,
        session_id: str | None = None,
        detection_text: str | None = None,
        finalize: Callable[[SanitizeOutcome], _ResultT],
    ) -> _ResultT:
        """Run a sanitize turn while containing every failed stage."""
        failure_kind = None
        failure = None
        try:
            return self._sanitize_transaction_impl(
                text,
                mode=mode,
                session_id=session_id,
                detection_text=detection_text,
                finalize=finalize,
            )
        except OutboundLeakError as error:
            failure_kind = "residual"
            failure = (list(error.leak_types), list(error.policy_categories))
            discard_exception_graph(error)
        except SessionExpiredError as error:
            failure_kind = "expired"
            discard_exception_graph(error)
        except ModeMismatchError as error:
            failure_kind = "mode"
            discard_exception_graph(error)
        except Exception as error:
            failure_kind = "failed"
            discard_exception_graph(error)

        self = None
        text = ""
        detection_text = None
        mode = None
        session_id = None
        finalize = None
        if failure_kind == "residual":
            safe_leak_types, safe_categories = failure
            raise OutboundLeakError(
                safe_leak_types,
                policy_categories=safe_categories,
            )
        if failure_kind == "expired":
            raise SessionExpiredError("Session not found or expired")
        if failure_kind == "mode":
            raise ModeMismatchError("session mode mismatch")
        raise SanitizeTransactionError("sanitize transaction failed")

    def _sanitize_transaction_impl(
        self,
        text: str,
        *,
        mode: str | None = None,
        session_id: str | None = None,
        detection_text: str | None = None,
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
            residual_failure = None
            core = None
            outcome = None
            prepared = None
            discarded = None
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
                        detection_text=detection_text,
                        scan_leaks=scan_outbound_leaks,
                        scan_residual=scan_residual_signals,
                    )
                except StatelessLeakError as error:
                    residual_failure = (
                        list(error.leak_types),
                        list(error.policy_categories),
                    )
                    discard_exception_graph(error)
                except VaultTimeoutError:
                    # Confirm provenance before treating this exception name as
                    # lifecycle expiry. An injected detector/finalizer can
                    # coincidentally raise the same public exception type.
                    if not staged.vault.is_idle():
                        raise
                    if not is_new:
                        self.drop(sid)
                    raise SessionExpiredError("Session not found or expired") from None

                if residual_failure is None:
                    assert core is not None
                    staged.entities.extend(core.detected)
                    outcome = SanitizeOutcome(
                        session_id=sid,
                        original_text=text,
                        sanitized_text=core.sanitized_text,
                        entities=core.entities,
                        entity_type_counts=core.entity_type_counts,
                        section26=scan_section26(text),
                        warnings=core.warnings,
                        replacement_highlights=core.replacement_highlights,
                    )
                    prepared = finalize(outcome)
                    digest = _sanitized_digest(core.sanitized_text)
                    prior_digests = tuple(
                        item for item in staged.trusted_sanitized_digests if item != digest
                    )
                    staged.trusted_sanitized_digests = (prior_digests + (digest,))[
                        -_TRUSTED_SANITIZED_DIGEST_LIMIT:
                    ]
                    # A request that acquired the lifecycle lock before expiry
                    # stays active for one full TTL after its successful commit.
                    staged.last_access = self._now()
                    discarded = self._publish_sanitize_locked(sid, staged, is_new=is_new)
            except Exception:
                self._discard_detached(staged)
                raise

            if residual_failure is not None:
                self._discard_detached(staged)
                safe_leak_types, safe_categories = residual_failure
                self = None
                text = ""
                detection_text = None
                mode = None
                session_id = None
                finalize = None
                sid = ""
                staged = None
                core = None
                outcome = None
                prepared = None
                discarded = None
                raise OutboundLeakError(
                    safe_leak_types,
                    policy_categories=safe_categories,
                )

            if discarded is not None:
                self._discard_detached(discarded)
            return prepared

    def _stage_sanitize_locked(
        self,
        session_id: str | None,
        mode: str | None,
    ) -> tuple[str, _Session, bool]:
        """Build a detached target without touching or evicting live state."""
        self._ensure_open_locked()
        now = self._now()
        if session_id is not None:
            published = self._sessions.get(session_id)
            if published is None or self._is_expired(published, now, self._ttl_s):
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
                trusted_sanitized_digests=published.trusted_sanitized_digests,
            )
            return session_id, staged, False

        resolved_mode = mode or "token"
        if resolved_mode not in ("token", "surrogate"):
            raise ModeMismatchError(f"unknown mode '{resolved_mode}'")
        sid = str(uuid.uuid4())
        staged = _Session(
            vault=SessionVault(idle_timeout_s=None),
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
                self._remember_tombstone_locked(lru)
        else:
            discarded = next_sessions.get(sid)
        next_sessions[sid] = staged
        self._sessions = next_sessions
        try:
            self._reschedule_expiry_locked()
        except BaseException:
            if discarded is not None:
                self._discard_detached(discarded)
            raise
        return discarded

    @staticmethod
    def _discard_detached(session: _Session) -> None:
        """Release every session-owned reference without changing outcomes."""
        try:
            session.vault.clear()
        except Exception as error:
            discard_exception_graph(error)
            # The service reference is already absent (or was never published).
            # Do not turn a completed commit into a caller-visible failure.
            _LOG.error("Session vault cleanup did not complete")
        finally:
            session.entities.clear()
            session.trusted_sanitized_digests = ()
            session.salt = ""

    def restore(self, session_id: str, text: str) -> RestoreOutcome:
        failure_kind = None
        try:
            with self._lock:
                return self._restore_locked(session_id, text)
        except SessionExpiredError as error:
            failure_kind = "expired"
            discard_exception_graph(error)
        except Exception as error:
            failure_kind = "failed"
            discard_exception_graph(error)

        self = None
        session_id = ""
        text = ""
        if failure_kind == "expired":
            raise SessionExpiredError("Session not found or expired")
        raise RestoreTransactionError("restore failed")

    def _restore_locked(self, session_id: str, text: str) -> RestoreOutcome:
        failure_kind = None
        try:
            result = self._restore_locked_impl(session_id, text)
            session = self._sessions.get(session_id)
            if session is not None:
                session.last_access = self._now()
                self._reschedule_expiry_locked()
            return result
        except VaultTimeoutError as error:
            failure_kind = "vault_expired"
            discard_exception_graph(error)
        except SessionExpiredError as error:
            failure_kind = "expired"
            discard_exception_graph(error)
        except Exception as error:
            failure_kind = "failed"
            discard_exception_graph(error)

        if failure_kind == "vault_expired":
            try:
                self.drop(session_id)
            except Exception as error:
                failure_kind = "failed"
                discard_exception_graph(error)

        self = None
        session_id = ""
        text = ""
        if failure_kind in {"vault_expired", "expired"}:
            raise SessionExpiredError("Session not found or expired")
        raise RestoreTransactionError("restore failed")

    def _restore_locked_impl(self, session_id: str, text: str) -> RestoreOutcome:
        session, _admitted_at = self._get_existing_locked(session_id, None)
        sid = session_id
        if not text or not text.strip():
            return RestoreOutcome(
                restored_text=text,
                replaced_count=0,
                leftover_tokens=[],
                warnings=[],
            )
        registry = EntityRegistry(
            entities=session.entities,
            fp_count=sum(1 for e in session.entities if e.redact_type == "FP"),
            tb_count=sum(1 for e in session.entities if e.redact_type == "TB"),
        )
        response = AIResponse(text=text, request_id=sid, latency=0.0)
        trusted_sanitized_input = _sanitized_digest(text) in session.trusted_sanitized_digests
        reverse_result = reverse_map(
            response,
            registry,
            session.vault,
            mode=session.mode,
        )

        warnings = [f for f in reverse_result.flags if not f.startswith(_NOISY_PREFIXES)]
        generated_pii_count = 0
        if not trusted_sanitized_input:
            try:
                validation = validate_output(reverse_result, registry, session.vault)
                warnings.extend(
                    f
                    for f in validation.flags
                    if f not in warnings and not f.startswith(_NOISY_PREFIXES)
                )
            except OutputPIILeakError as error:
                generated_pii_count = error.count
                discard_exception_graph(error)
                # inbound direction: the AI fabricated PII-looking data — warn only
                warnings.append("ai_generated_pii")

        replaced_count = int(reverse_result.audit_summary.get("replaced_count", 0))

        leftover = [p for p in session.vault._reverse if p in reverse_result.text]
        return RestoreOutcome(
            restored_text=reverse_result.text,
            replaced_count=replaced_count,
            leftover_tokens=leftover,
            warnings=warnings,
            generated_pii_count=generated_pii_count,
            foreign_replacement_count=int(
                reverse_result.audit_summary.get("foreign_token_count", 0)
            ),
        )
