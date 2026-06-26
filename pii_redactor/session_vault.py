"""Session vault for storing original↔pseudonym mappings in memory.

SECURITY-CRITICAL MODULE:
- Never write to disk
- Never send to network
- Audit log never contains original or pseudonym (only entity_id + action + timestamp)
- clear() overwrites original with null bytes before releasing reference
"""

import time
import uuid

from pii_redactor.models import VaultRecord


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
    """

    def __init__(self, idle_timeout_s: int = 1800):
        """Initialize a new session vault.

        Args:
            idle_timeout_s: Idle timeout in seconds (default 30 minutes)
        """
        self._table: dict[str, VaultRecord] = {}      # entity_id → VaultRecord
        self._reverse: dict[str, str] = {}            # pseudonym → entity_id
        self._last_access: float = time.monotonic()
        self._idle_timeout_s = idle_timeout_s
        self.session_id: str = str(uuid.uuid4())
        self._audit_entries: list[dict] = []           # local audit log

    def write(self, record: VaultRecord) -> None:
        """Store a vault record. Updates both _table and _reverse.

        Args:
            record: VaultRecord to store
        """
        self._touch()
        # Clean up stale reverse mapping if entity_id already exists with a different pseudonym
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
        self.check_idle()
        self._touch()
        entity_id = self._reverse.get(pseudonym)
        if entity_id is None:
            return None
        self._audit("read_by_pseudonym", entity_id)
        return self._table.get(entity_id)

    def snapshot(self) -> dict:
        """Return a shallow copy of current state for rollback.

        Returns:
            Dict with '_table' and '_reverse' keys containing shallow copies
        """
        return {
            "_table": dict(self._table),
            "_reverse": dict(self._reverse),
        }

    def restore(self, snapshot: dict) -> None:
        """Restore vault to a previous snapshot state.

        Args:
            snapshot: Dict returned by snapshot()
        """
        self._table = dict(snapshot["_table"])
        self._reverse = dict(snapshot["_reverse"])
        self._audit("restore", "snapshot")

    def clear(self) -> None:
        """Overwrite all originals with null bytes before clearing.

        This reduces in-memory exposure time of PII by overwriting the string
        before releasing the reference from our dicts.
        """
        for record in self._table.values():
            record.original = '\x00' * len(record.original)
        self._table.clear()
        self._reverse.clear()
        self._audit("clear", "all")

    def is_idle(self) -> bool:
        """Return True if idle timeout has been exceeded.

        Returns:
            True if time since last access exceeds idle_timeout_s, False otherwise
        """
        return (time.monotonic() - self._last_access) > self._idle_timeout_s

    def check_idle(self) -> None:
        """Raise VaultTimeoutError if idle timeout exceeded.

        Raises:
            VaultTimeoutError: If vault idle timeout has been exceeded
        """
        if self.is_idle():
            raise VaultTimeoutError(
                f"Session vault idle timeout after {self._idle_timeout_s}s"
            )

    def audit_log(self) -> list[dict]:
        """Return a copy of the audit log entries.

        Returns:
            List of audit entries (each a dict with action, entity_id, timestamp, session_id)
        """
        return list(self._audit_entries)

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
        self._audit_entries.append({
            "action": action,
            "entity_id": entity_id,
            "timestamp": time.monotonic(),
            "session_id": self.session_id,
        })
