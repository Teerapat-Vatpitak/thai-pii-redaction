"""Session vault for storing original↔pseudonym mappings in memory.

SECURITY-CRITICAL MODULE:
- Never write to disk
- Never send to network
- Audit log never contains original or pseudonym (only entity_id + action + timestamp)
- clear() drops vault-owned references; Python immutable strings cannot be
  guaranteed to be zeroized
"""

import threading
import time
import uuid
from typing import NamedTuple

from pii_redactor.anonymizer.token_generator import (
    is_valid_token_namespace,
    new_token_namespace,
    token_namespace_from_candidate,
)
from pii_redactor.models import VaultRecord

# data_type stamped on records re-admitted through seed(). An exported mapping
# is only {pseudonym: original} — the real data_type is not recoverable — so the
# sentinel is treated as a wildcard by get_by_original(), which is the lookup
# the anonymizer uses to decide "this person already has a pseudonym".
SEEDED_DATA_TYPE = "SEEDED"
_SEED_COLLISION_ERROR = "seed pseudonym collision"


class _VaultAuditEntry(NamedTuple):
    """Immutable internal audit row; `audit_log()` retains the public dict shape."""

    action: str
    entity_id: str
    timestamp: float
    session_id: str


class VaultTimeoutError(Exception):
    """Raised when vault is accessed after idle timeout."""

    pass


class SessionVault:
    """In-memory vault for original↔pseudonym mappings.

    Design:
    - _table: entity_id → VaultRecord (forward lookup)
    - _reverse: pseudonym → entity_id (reverse lookup)
    - _last_access: monotonic time, reset on each touch()
    - _idle_timeout_s: timeout threshold in seconds
    - session_id: UUID string for audit trail
    - _audit_entries: local audit log (never contains PII)
    - _clear_epoch: prevents stale rollback snapshots from reviving cleared data
    - _token_namespace: non-secret generation tag for token-mode identity
    - _lifecycle_lock: serializes snapshot/restore/clear generation decisions
    """

    def __init__(
        self,
        idle_timeout_s: float | None = 1800,
        *,
        token_namespace: str | None = None,
    ):
        """Initialize a new session vault.

        Args:
            idle_timeout_s: Standalone idle timeout in seconds (default 30
                minutes). ``None`` delegates expiry to a lifecycle manager.
            token_namespace: Existing stateless-chain namespace to continue
        """
        if token_namespace is not None and not is_valid_token_namespace(token_namespace):
            raise ValueError("invalid token namespace")
        self._table: dict[str, VaultRecord] = {}  # entity_id → VaultRecord
        self._reverse: dict[str, str] = {}  # pseudonym → entity_id
        self._last_access: float = time.monotonic()
        self._idle_timeout_s = idle_timeout_s
        self.session_id: str = str(uuid.uuid4())
        self._token_namespace: str | None = token_namespace or new_token_namespace()
        self._audit_entries: list[_VaultAuditEntry] = []  # local audit log
        self._clear_epoch = 0
        self._lifecycle_lock = threading.RLock()

    @property
    def token_namespace(self) -> str:
        """Return the generation tag for tokens minted by this vault."""
        with self._lifecycle_lock:
            if self._token_namespace is None:
                self._token_namespace = new_token_namespace()
            return self._token_namespace

    def adopt_token_namespace(self, namespace: str) -> bool:
        """Continue a seeded stateless token chain before minting new tokens."""
        if not is_valid_token_namespace(namespace):
            raise ValueError("invalid token namespace")
        with self._lifecycle_lock:
            generated_namespaces = {
                candidate_namespace
                for entity_id, record in self._table.items()
                if record.data_type != SEEDED_DATA_TYPE
                and self._reverse.get(record.pseudonym) == entity_id
                and (candidate_namespace := token_namespace_from_candidate(record.pseudonym))
                is not None
            }
            if generated_namespaces and generated_namespaces != {namespace}:
                return False
            self._token_namespace = namespace
            return True

    def write(self, record: VaultRecord) -> None:
        """Store a vault record. Updates both _table and _reverse.

        Args:
            record: VaultRecord to store

        Raises:
            ValueError: if the pseudonym is already mapped to a different
                original — a silent reverse-index overwrite would restore
                the wrong person's data.
        """
        with self._lifecycle_lock:
            self._touch()
            existing_owner_id = self._reverse.get(record.pseudonym)
            if existing_owner_id is not None and existing_owner_id != record.entity_id:
                existing_owner = self._table.get(existing_owner_id)
                if existing_owner is not None and existing_owner.original != record.original:
                    # SECURITY: no pseudonym/original in the message (audit-safe)
                    raise ValueError(
                        f"pseudonym collision: entity {record.entity_id[:8]} "
                        f"vs {existing_owner_id[:8]}"
                    )
            # Clean up stale reverse mapping if entity_id already exists with a
            # different pseudonym.
            if record.entity_id in self._table:
                old_pseudonym = self._table[record.entity_id].pseudonym
                if old_pseudonym != record.pseudonym:
                    self._reverse.pop(old_pseudonym, None)
            self._table[record.entity_id] = record
            self._reverse[record.pseudonym] = record.entity_id
            self._audit("write", record.entity_id)

    def get_by_entity_id(self, entity_id: str) -> VaultRecord | None:
        """Lookup by entity_id. Returns None if not found. Touches idle timer.

        Args:
            entity_id: The entity ID to look up

        Returns:
            VaultRecord if found, None otherwise

        Raises:
            VaultTimeoutError: If vault has been idle past timeout threshold
        """
        with self._lifecycle_lock:
            self.check_idle()
            self._touch()
            record = self._table.get(entity_id)
            self._audit("read_by_id", entity_id)
            return record

    def get_by_pseudonym(self, pseudonym: str) -> VaultRecord | None:
        """Lookup by pseudonym. Returns None if not found. Touches idle timer.

        Args:
            pseudonym: The pseudonym to look up

        Returns:
            VaultRecord if found, None otherwise

        Raises:
            VaultTimeoutError: If vault has been idle past timeout threshold
        """
        with self._lifecycle_lock:
            self.check_idle()
            self._touch()
            entity_id = self._reverse.get(pseudonym)
            if entity_id is None:
                return None
            self._audit("read_by_pseudonym", entity_id)
            return self._table.get(entity_id)

    def get_by_original(self, original: str, data_type: str | None = None) -> VaultRecord | None:
        """Lookup by original value (optionally narrowed by data_type).

        Linear scan — vaults are per-session and small. Used by token-mode
        pseudonym reuse so the same original gets the same token across turns.

        A seed()-ed record matches ANY requested data_type: an exported mapping
        is only {pseudonym: original}, so the real data_type cannot be recovered
        on re-admission, and a strict match would make the caller-held mapping
        useless for reuse (the same person would be issued a second token every
        turn). Exact data_type matches still take priority, so a real record
        always wins over a seeded one.

        Raises:
            VaultTimeoutError: If vault has been idle past timeout threshold
        """
        with self._lifecycle_lock:
            self.check_idle()
            self._touch()
            seeded_match: VaultRecord | None = None
            for record in self._table.values():
                if record.original != original:
                    continue
                if data_type is None or record.data_type == data_type:
                    self._audit("read_by_original", record.entity_id)
                    return record
                if record.data_type == SEEDED_DATA_TYPE and seeded_match is None:
                    seeded_match = record
            if seeded_match is not None:
                self._audit("read_by_original", seeded_match.entity_id)
            return seeded_match

    def export_mapping(self) -> dict[str, str]:
        """Return {pseudonym: original} to an in-process stateless adapter.

        Hosted roundtrip consumes the value inside one request. Only the legacy
        worker-v1 opt-in path exports it; the accepted HTTP v2 wire does not.
        """
        with self._lifecycle_lock:
            out: dict[str, str] = {}
            for pseudonym, entity_id in self._reverse.items():
                record = self._table.get(entity_id)
                if record is not None:
                    out[pseudonym] = record.original
            return out

    def trusted_pseudonyms(self) -> set[str]:
        """Pseudonyms this vault minted itself, excluding caller-supplied ones.

        SECURITY BOUNDARY. `_reverse` mixes two populations: values written by
        the anonymizer (trustworthy — this process generated them) and values
        re-admitted through seed() from a caller-held mapping (a stranger's
        claim on the platform path). The outbound leak guard excuses anything
        it believes is a pseudonym, so treating the two alike let a caller
        declare a real, checksum-valid national ID to be "their pseudonym" and
        have the guard fall silent on it. Empty values and replacements that
        contain their own original are also never trusted. Callers that need
        the full set for positional bookkeeping still read `_reverse` directly.
        """
        with self._lifecycle_lock:
            return {
                record.pseudonym
                for record in self._table.values()
                if record.data_type != SEEDED_DATA_TYPE
                and record.pseudonym
                and record.original not in record.pseudonym
            }

    def seed(self, pseudonym: str, original: str) -> VaultRecord:
        """Re-admit a pair from a previous turn's exported mapping.

        The pseudonym is checked directly before any record or audit row is
        added. Replaying the same pair returns its existing record without a
        new audit event. Reusing the pseudonym for a different original fails
        with a constant message and leaves the first mapping intact.

        entity_id/span are synthesised because an exported mapping does not
        carry them. The entity ID is an opaque UUID, never caller text.
        SEEDED_DATA_TYPE is the safe provenance marker that get_by_original()
        treats as a wildcard for data-type-narrowed reuse.

        Returns:
            The existing or newly created seeded record.

        Raises:
            ValueError: If the pseudonym is already owned by another original
                or the existing owner cannot be verified.
        """
        with self._lifecycle_lock:
            existing_id = self._reverse.get(pseudonym)
            if existing_id is not None:
                existing = self._table.get(existing_id)
                if existing is None or existing.original != original:
                    raise ValueError(_SEED_COLLISION_ERROR)
                return existing

            record = VaultRecord(
                entity_id=f"seed:{uuid.uuid4()}",
                original=original,
                pseudonym=pseudonym,
                type="FP",
                data_type=SEEDED_DATA_TYPE,
                span=(0, 0),
                timestamp=time.monotonic(),
            )
            prior_access = self._last_access
            prior_audit_length = len(self._audit_entries)
            try:
                self._touch()
                self._table[record.entity_id] = record
                self._reverse[record.pseudonym] = record.entity_id
                self._audit("seed", record.entity_id)
            except BaseException:
                self._table.pop(record.entity_id, None)
                if self._reverse.get(record.pseudonym) == record.entity_id:
                    self._reverse.pop(record.pseudonym, None)
                del self._audit_entries[prior_audit_length:]
                self._last_access = prior_access
                raise
            return record

    def clone(self) -> "SessionVault":
        """Return a complete detached copy for an unpublished transaction.

        The constructor is deliberately bypassed so cloning does not generate a
        new vault ID or access timestamp. Immutable records and audit entries
        are shared behind detached lookup/list containers. Clearing or mutating
        those containers cannot affect live state.
        """
        with self._lifecycle_lock:
            clone = object.__new__(type(self))
            clone._table = dict(self._table)
            clone._reverse = dict(self._reverse)
            clone._last_access = self._last_access
            clone._idle_timeout_s = self._idle_timeout_s
            clone.session_id = self.session_id
            clone._token_namespace = self._token_namespace
            # Entries are immutable tuples, so the detached list can share them
            # safely. Staged actions append only to the clone's list.
            clone._audit_entries = list(self._audit_entries)
            clone._clear_epoch = self._clear_epoch
            clone._lifecycle_lock = threading.RLock()
        return clone

    def snapshot(self) -> dict:
        """Return a shallow copy of current state for rollback.

        Returns:
            Detached indexes plus the clear epoch that authorizes restoration.
        """
        with self._lifecycle_lock:
            return {
                "_table": dict(self._table),
                "_reverse": dict(self._reverse),
                "_token_namespace": self._token_namespace,
                "_clear_epoch": self._clear_epoch,
            }

    def restore(self, snapshot: dict) -> bool:
        """Restore vault to a previous snapshot state.

        Args:
            snapshot: Dict returned by snapshot()

        Returns:
            True when restored. False when clear() invalidated the snapshot.
        """
        with self._lifecycle_lock:
            if snapshot.get("_clear_epoch") != self._clear_epoch:
                return False
            self._table = dict(snapshot["_table"])
            self._reverse = dict(snapshot["_reverse"])
            self._token_namespace = snapshot["_token_namespace"]
            self._audit("restore", "snapshot")
            return True

    def clear(self) -> None:
        """Drop the vault-owned lookup references.

        Python strings and immutable records cannot be overwritten. External
        references can outlive this vault, so this is exposure reduction rather
        than a secure-zeroization guarantee.
        """
        with self._lifecycle_lock:
            self._clear_epoch += 1
            self._table.clear()
            self._reverse.clear()
            # A reused vault must never mint a token that can mean something
            # from the cleared generation. Create the next tag lazily.
            self._token_namespace = None
            self._audit("clear", "all")

    def is_idle(self) -> bool:
        """Return True at or beyond the standalone idle timeout.

        Returns:
            True if age is at least idle_timeout_s, False when managed elsewhere
        """
        with self._lifecycle_lock:
            return (
                self._idle_timeout_s is not None
                and (time.monotonic() - self._last_access) >= self._idle_timeout_s
            )

    def check_idle(self) -> None:
        """Raise VaultTimeoutError if idle timeout exceeded.

        Raises:
            VaultTimeoutError: If vault idle timeout has been exceeded
        """
        with self._lifecycle_lock:
            if self.is_idle():
                assert self._idle_timeout_s is not None
                raise VaultTimeoutError(f"Session vault idle timeout after {self._idle_timeout_s}s")

    def audit_log(self) -> list[dict]:
        """Return a copy of the audit log entries.

        Returns:
            List of audit entries (each a dict with action, entity_id, timestamp, session_id)
        """
        with self._lifecycle_lock:
            return [entry._asdict() for entry in self._audit_entries]

    # ========== Private Helpers ==========

    def _touch(self) -> None:
        """Update last access time to current monotonic time."""
        self._last_access = time.monotonic()

    def _audit(self, action: str, entity_id: str) -> None:
        """Append to local audit log.

        SECURITY: Never log original or pseudonym — only entity_id + action + timestamp.

        Args:
            action: The action being audited (e.g., "write", "read_by_id", "clear")
            entity_id: The entity ID involved (or special value like "all" or "snapshot")
        """
        self._audit_entries.append(
            _VaultAuditEntry(
                action=action,
                entity_id=entity_id,
                timestamp=time.monotonic(),
                session_id=self.session_id,
            )
        )
