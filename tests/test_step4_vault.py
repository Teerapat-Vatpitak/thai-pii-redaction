"""Tests for Session Vault (Step 4)."""

import time
import uuid

import pytest

from pii_redactor.models import VaultRecord
from pii_redactor.session_vault import SessionVault, VaultTimeoutError


def _make_record(
    entity_id: str = None, original: str = "John", pseudonym: str = "Alice"
) -> VaultRecord:
    """Helper to create a VaultRecord for testing."""
    return VaultRecord(
        entity_id=entity_id or str(uuid.uuid4()),
        original=original,
        pseudonym=pseudonym,
        type="TB",
        data_type="NAME",
        span=(0, len(original)),
        timestamp=time.monotonic(),
    )


def test_vault_write_and_read_by_id():
    """Test writing a record and reading it back by entity_id."""
    vault = SessionVault()
    record = _make_record()
    vault.write(record)
    result = vault.get_by_entity_id(record.entity_id)
    assert result is record


def test_vault_write_and_read_by_pseudonym():
    """Test writing a record and reading it back by pseudonym."""
    vault = SessionVault()
    record = _make_record(pseudonym="FakeName123")
    vault.write(record)
    result = vault.get_by_pseudonym("FakeName123")
    assert result is record


def test_vault_write_rejects_pseudonym_collision_between_people():
    """One pseudonym must never map to two different originals: the reverse
    index would silently point at the last writer and restore the wrong person."""
    vault = SessionVault()
    vault.write(_make_record(original="สมชาย ใจดี", pseudonym="บุญชัย"))
    with pytest.raises(ValueError):
        vault.write(_make_record(original="วิชัย ทองแท้", pseudonym="บุญชัย"))
    # first mapping must be intact
    assert vault.get_by_pseudonym("บุญชัย").original == "สมชาย ใจดี"


def test_vault_write_allows_same_pseudonym_for_same_original():
    """Consistency path: two entities for the SAME original may share the
    pseudonym (repeated mentions of one person)."""
    vault = SessionVault()
    vault.write(_make_record(original="สมชาย ใจดี", pseudonym="บุญชัย"))
    vault.write(_make_record(original="สมชาย ใจดี", pseudonym="บุญชัย"))
    assert vault.get_by_pseudonym("บุญชัย").original == "สมชาย ใจดี"


def test_vault_get_missing_returns_none():
    """Test that get returns None for nonexistent entries."""
    vault = SessionVault()
    assert vault.get_by_entity_id("nonexistent") is None
    assert vault.get_by_pseudonym("no_such_pseudonym") is None


def test_vault_snapshot_and_restore():
    """Test snapshot and restore functionality."""
    vault = SessionVault()
    record = _make_record()
    vault.write(record)
    snap = vault.snapshot()
    # Clear vault
    vault._table.clear()
    vault._reverse.clear()
    # Restore
    vault.restore(snap)
    assert vault.get_by_entity_id(record.entity_id) is not None


def test_vault_clear_removes_all():
    """Test that clear() removes all entries."""
    vault = SessionVault()
    vault.write(_make_record())
    vault.write(_make_record(original="Jane", pseudonym="Bob"))
    vault.clear()
    # After clear, nothing should be found
    # (idle check bypassed by using _table directly)
    assert len(vault._table) == 0
    assert len(vault._reverse) == 0


def test_vault_clear_overwrites_original():
    """Test that clear() overwrites original with null bytes."""
    vault = SessionVault()
    record = _make_record(original="RealSecret")
    vault.write(record)
    vault.clear()
    # Original should be overwritten with null bytes
    assert record.original == "\x00" * len("RealSecret")


def test_vault_idle_timeout():
    """Test that idle timeout raises VaultTimeoutError."""
    vault = SessionVault(idle_timeout_s=0)
    # Force idle by manipulating last access time
    vault._last_access = time.monotonic() - 10  # 10 seconds ago
    assert vault.is_idle() is True
    with pytest.raises(VaultTimeoutError):
        vault.get_by_entity_id("any")


def test_vault_not_idle_when_active():
    """Test that is_idle returns False when vault is active."""
    vault = SessionVault(idle_timeout_s=3600)
    assert vault.is_idle() is False


def test_vault_audit_log_no_original_or_pseudonym():
    """Test that audit log never contains original or pseudonym values."""
    vault = SessionVault()
    record = _make_record(original="RealSecret", pseudonym="FakeName")
    vault.write(record)
    vault.get_by_entity_id(record.entity_id)
    log = vault.audit_log()
    assert len(log) >= 2
    for entry in log:
        assert "RealSecret" not in str(entry)
        assert "FakeName" not in str(entry)
        assert "action" in entry
        assert "entity_id" in entry
        assert "timestamp" in entry


def test_vault_session_id_is_uuid():
    """Test that session_id is a valid UUID."""
    vault = SessionVault()
    # Should be a valid UUID string
    parsed = uuid.UUID(vault.session_id)
    assert str(parsed) == vault.session_id


def test_vault_multiple_writes_same_entity():
    """Test that multiple writes to same entity_id overwrite previous."""
    vault = SessionVault()
    entity_id = str(uuid.uuid4())
    r1 = _make_record(entity_id=entity_id, original="A", pseudonym="X")
    r2 = _make_record(entity_id=entity_id, original="A_updated", pseudonym="Y")
    vault.write(r1)
    vault.write(r2)
    # Second write should overwrite first
    result = vault.get_by_entity_id(entity_id)
    assert result.pseudonym == "Y"
    # Old pseudonym must NOT point to anything (stale reverse mapping cleared)
    old = vault.get_by_pseudonym("X")
    assert old is None or old.pseudonym != "Y"
    # New pseudonym must work
    new = vault.get_by_pseudonym("Y")
    assert new is not None
    assert new.entity_id == entity_id


def test_get_by_original_returns_record():
    vault = SessionVault()
    rec = _make_record(original="สมชาย ใจดี", pseudonym="บุญชัย")
    vault.write(rec)
    found = vault.get_by_original("สมชาย ใจดี")
    assert found is rec


def test_get_by_original_filters_by_data_type():
    vault = SessionVault()
    a = _make_record(original="1234", pseudonym="[บัตรประชาชน_1]")
    a.data_type = "THAI_ID"
    b = _make_record(original="1234", pseudonym="[โทรศัพท์_1]")
    b.data_type = "PHONE"
    vault.write(a)
    vault.write(b)
    assert vault.get_by_original("1234", data_type="PHONE") is b
    assert vault.get_by_original("1234", data_type="THAI_ID") is a


def test_get_by_original_missing_returns_none():
    vault = SessionVault()
    assert vault.get_by_original("ไม่มี") is None


def test_get_by_original_respects_idle_timeout():
    vault = SessionVault(idle_timeout_s=0)
    vault._last_access = time.monotonic() - 10
    with pytest.raises(VaultTimeoutError):
        vault.get_by_original("x")


# ========== export_mapping / seed (stateless platform contract) ==========


def test_export_mapping_returns_pseudonym_to_original():
    vault = SessionVault()
    vault.write(_make_record(original="สมชาย ใจดี", pseudonym="[ชื่อ_1]"))
    vault.write(_make_record(original="0812345678", pseudonym="[โทรศัพท์_1]"))
    assert vault.export_mapping() == {
        "[ชื่อ_1]": "สมชาย ใจดี",
        "[โทรศัพท์_1]": "0812345678",
    }


def test_export_mapping_is_empty_for_an_empty_vault():
    assert SessionVault().export_mapping() == {}


def test_export_mapping_skips_a_pseudonym_whose_record_is_gone():
    """The reverse index is the iteration source; a dangling entry is dropped."""
    vault = SessionVault()
    vault.write(_make_record(original="สมชาย", pseudonym="[ชื่อ_1]"))
    vault._reverse["[ชื่อ_9]"] = "no-such-entity"
    assert vault.export_mapping() == {"[ชื่อ_1]": "สมชาย"}


def test_seed_readmits_a_pair_from_a_previous_turn():
    vault = SessionVault()
    vault.seed("[ชื่อ_1]", "สมชาย ใจดี")
    record = vault.get_by_pseudonym("[ชื่อ_1]")
    assert record is not None
    assert record.original == "สมชาย ใจดี"


def test_seed_round_trips_through_export_mapping():
    vault = SessionVault()
    vault.seed("[ชื่อ_1]", "สมชาย ใจดี")
    assert vault.export_mapping() == {"[ชื่อ_1]": "สมชาย ใจดี"}


def test_seed_is_idempotent_for_the_same_pair():
    vault = SessionVault()
    vault.seed("[ชื่อ_1]", "สมชาย ใจดี")
    vault.seed("[ชื่อ_1]", "สมชาย ใจดี")
    assert vault.export_mapping() == {"[ชื่อ_1]": "สมชาย ใจดี"}


def test_seed_rejects_repointing_a_pseudonym_at_a_different_original():
    """A tampered replayed mapping must not be able to swap who a token means."""
    vault = SessionVault()
    vault.write(_make_record(original="สมชาย ใจดี", pseudonym="[ชื่อ_1]"))
    with pytest.raises(ValueError):
        vault.seed("[ชื่อ_1]", "สมหญิง ร้ายกาจ")
    # the original owner is untouched
    assert vault.get_by_pseudonym("[ชื่อ_1]").original == "สมชาย ใจดี"


def test_seed_error_message_carries_no_pii():
    vault = SessionVault()
    vault.write(_make_record(original="สมชาย ใจดี", pseudonym="[ชื่อ_1]"))
    with pytest.raises(ValueError) as exc:
        vault.seed("[ชื่อ_1]", "สมหญิง ร้ายกาจ")
    assert "สมชาย" not in str(exc.value)
    assert "สมหญิง" not in str(exc.value)
    assert "[ชื่อ_1]" not in str(exc.value)


def test_seeded_record_is_reusable_by_get_by_original_regardless_of_data_type():
    """An exported mapping carries no data_type, so a seeded pair must still
    satisfy the anonymizer's data_type-narrowed reuse lookup — otherwise a
    replayed mapping would silently mint a second token for the same person."""
    vault = SessionVault()
    vault.seed("[ชื่อ_1]", "สมชาย ใจดี")
    found = vault.get_by_original("สมชาย ใจดี", data_type="NAME")
    assert found is not None
    assert found.pseudonym == "[ชื่อ_1]"


def test_a_real_record_still_wins_over_a_seeded_one_for_its_own_data_type():
    vault = SessionVault()
    vault.seed("[ชื่อ_1]", "1234")
    real = _make_record(original="1234", pseudonym="[โทรศัพท์_1]")
    real.data_type = "PHONE"
    vault.write(real)
    assert vault.get_by_original("1234", data_type="PHONE") is real
