"""Tests for Session Vault (Step 4)."""

import time
import uuid

import pytest

from pii_redactor.detectors.fp_detector import detect_fp
from pii_redactor.models import VaultRecord
from pii_redactor.session_vault import SessionVault, VaultTimeoutError


def _make_record(
    entity_id: str = None,
    original: str = "John",
    pseudonym: str = "Alice",
    data_type: str = "NAME",
) -> VaultRecord:
    """Helper to create a VaultRecord for testing."""
    return VaultRecord(
        entity_id=entity_id or str(uuid.uuid4()),
        original=original,
        pseudonym=pseudonym,
        type="TB",
        data_type=data_type,
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


def test_vault_clone_is_complete_and_mutation_is_detached():
    vault = SessionVault(idle_timeout_s=123)
    record = _make_record()
    vault.write(record)
    clone = vault.clone()

    assert clone is not vault
    assert clone._table is not vault._table
    assert clone._reverse is not vault._reverse
    assert clone._audit_entries is not vault._audit_entries
    assert clone._table[record.entity_id] is record
    assert clone._table[record.entity_id] == record
    assert clone._reverse == vault._reverse
    assert clone._last_access == vault._last_access
    assert clone._idle_timeout_s == vault._idle_timeout_s
    assert clone.session_id == vault.session_id
    assert clone._clear_epoch == vault._clear_epoch
    assert clone._lifecycle_lock is not vault._lifecycle_lock
    assert clone._audit_entries == vault._audit_entries
    assert all(
        clone_entry is live_entry
        for clone_entry, live_entry in zip(
            clone._audit_entries,
            vault._audit_entries,
            strict=True,
        )
    )
    with pytest.raises(AttributeError):
        clone._audit_entries[0].action = "mutated"
    with pytest.raises(AttributeError):
        clone._table[record.entity_id].original = "mutated"

    clone.clear()

    assert record.original != "\x00" * len(record.original)
    assert vault._table[record.entity_id] is record
    assert vault._reverse


def test_clear_invalidates_a_stale_snapshot():
    vault = SessionVault()
    vault.write(_make_record(original="RealSecret"))
    snapshot = vault.snapshot()

    vault.clear()

    assert vault.restore(snapshot) is False
    assert vault._table == {}
    assert vault._reverse == {}
    assert vault.audit_log()[-1]["action"] == "clear"


def test_clear_wins_when_restore_already_holds_the_lifecycle_lock():
    import threading

    vault = SessionVault()
    vault.write(_make_record(original="RealSecret"))
    restore_reached_assignment = threading.Event()
    release_restore = threading.Event()
    cleared = threading.Event()
    errors = []

    class PausingSnapshot(dict):
        def __getitem__(self, key):
            if key == "_table":
                restore_reached_assignment.set()
                release_restore.wait(timeout=5)
            return super().__getitem__(key)

    snapshot = PausingSnapshot(vault.snapshot())

    def restore_snapshot():
        try:
            vault.restore(snapshot)
        except Exception as exc:
            errors.append(exc)

    restorer = threading.Thread(target=restore_snapshot)
    restorer.start()
    assert restore_reached_assignment.wait(timeout=5)

    clearer = threading.Thread(target=lambda: (vault.clear(), cleared.set()))
    clearer.start()
    assert not cleared.wait(timeout=0.05)

    release_restore.set()
    restorer.join(timeout=5)
    clearer.join(timeout=5)

    assert not restorer.is_alive()
    assert not clearer.is_alive()
    assert errors == []
    assert cleared.is_set()
    assert vault._table == {}
    assert vault._reverse == {}
    assert vault.audit_log()[-1]["action"] == "clear"


def test_audit_log_returns_mutable_copies_not_internal_rows():
    vault = SessionVault()
    vault.write(_make_record())

    public_rows = vault.audit_log()
    public_rows[0]["action"] = "mutated"

    assert vault.audit_log()[0]["action"] == "write"


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


def test_vault_clear_drops_references_without_claiming_zeroization():
    """External references survive because Python strings are immutable."""
    vault = SessionVault()
    record = _make_record(original="RealSecret")
    vault.write(record)
    vault.clear()
    assert record.original == "RealSecret"
    assert vault._table == {}
    assert vault._reverse == {}


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
    a = _make_record(
        original="1234",
        pseudonym="[บัตรประชาชน_1]",
        data_type="THAI_ID",
    )
    b = _make_record(
        original="1234",
        pseudonym="[โทรศัพท์_1]",
        data_type="PHONE",
    )
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
    first = vault.seed("[ชื่อ_1]", "สมชาย ใจดี")
    audit_after_first = vault.audit_log()
    access_after_first = vault._last_access

    second = vault.seed("[ชื่อ_1]", "สมชาย ใจดี")

    assert second is first
    assert vault.export_mapping() == {"[ชื่อ_1]": "สมชาย ใจดี"}
    assert len(vault._table) == 1
    assert vault.audit_log() == audit_after_first
    assert vault._last_access == access_after_first
    assert [entry["action"] for entry in audit_after_first] == ["seed"]


def test_seed_rejects_repointing_a_previously_seeded_pseudonym():
    vault = SessionVault()
    pseudonym = "[ชื่อ_1]"
    first_original = "สมชาย ใจดี"
    conflicting_original = "สมหญิง ร้ายกาจ"
    first = vault.seed(pseudonym, first_original)
    before_table = dict(vault._table)
    before_reverse = dict(vault._reverse)
    before_audit = vault.audit_log()
    before_access = vault._last_access

    with pytest.raises(ValueError, match=r"^seed pseudonym collision$") as exc:
        vault.seed(pseudonym, conflicting_original)

    assert str(exc.value) == "seed pseudonym collision"
    assert pseudonym not in str(exc.value)
    assert first_original not in str(exc.value)
    assert conflicting_original not in str(exc.value)
    assert vault._table == before_table
    assert vault._reverse == before_reverse
    assert vault.audit_log() == before_audit
    assert vault._last_access == before_access
    assert vault._table == {first.entity_id: first}


def test_seed_same_pair_returns_an_existing_written_record_without_mutation():
    vault = SessionVault()
    written = _make_record(original="สมชาย ใจดี", pseudonym="[ชื่อ_1]")
    vault.write(written)
    before_table = dict(vault._table)
    before_reverse = dict(vault._reverse)
    before_audit = vault.audit_log()
    before_access = vault._last_access

    returned = vault.seed(written.pseudonym, written.original)

    assert returned is written
    assert vault._table == before_table
    assert vault._reverse == before_reverse
    assert vault.audit_log() == before_audit
    assert vault._last_access == before_access


def test_seed_uses_an_opaque_uuid_and_keeps_audit_safe_after_clear():
    vault = SessionVault()
    pseudonym = "1101700230708"
    original = "บุคคลทดสอบ-0812345678"
    assert any(entity.data_type == "THAI_ID" for entity in detect_fp(pseudonym))

    record = vault.seed(pseudonym, original)

    assert record.entity_id.startswith("seed:")
    assert uuid.UUID(record.entity_id.removeprefix("seed:"))
    assert record.data_type == "SEEDED"
    before_clear = vault.audit_log()
    assert len(before_clear) == 1
    assert before_clear[0]["action"] == "seed"
    assert before_clear[0]["entity_id"] == record.entity_id
    assert set(before_clear[0]) == {"action", "entity_id", "timestamp", "session_id"}

    vault.clear()

    assert vault._table == {}
    assert vault._reverse == {}
    retained_audit = vault.audit_log()
    assert [entry["action"] for entry in retained_audit] == ["seed", "clear"]
    for unsafe_value in (pseudonym, original):
        assert unsafe_value not in str(before_clear)
        assert unsafe_value not in str(retained_audit)


def test_clone_preserves_safe_seed_audit_without_sharing_mutable_state():
    vault = SessionVault()
    first = vault.seed("[ชื่อ_1]", "สมชาย ใจดี")
    original_audit = vault.audit_log()

    clone = vault.clone()
    assert clone.audit_log() == original_audit
    assert clone._table[first.entity_id] is first

    clone.seed("[ชื่อ_2]", "สมหญิง ร้ายกาจ")

    assert vault.export_mapping() == {"[ชื่อ_1]": "สมชาย ใจดี"}
    assert vault.audit_log() == original_audit
    assert clone.export_mapping() == {
        "[ชื่อ_1]": "สมชาย ใจดี",
        "[ชื่อ_2]": "สมหญิง ร้ายกาจ",
    }
    assert [entry["action"] for entry in clone.audit_log()] == ["seed", "seed"]


def test_seed_audit_failure_rolls_back_and_retry_records_once():
    vault = SessionVault()
    pseudonym = "[ชื่อ_1]"
    original = "สมชาย ใจดี"
    before_access = vault._last_access
    real_audit = vault._audit
    fail_once = True

    def injected_audit(action, entity_id):
        nonlocal fail_once
        if action == "seed" and fail_once:
            fail_once = False
            real_audit(action, entity_id)
            raise RuntimeError("injected audit failure")
        real_audit(action, entity_id)

    vault._audit = injected_audit

    with pytest.raises(RuntimeError, match="injected audit failure"):
        vault.seed(pseudonym, original)

    assert vault._table == {}
    assert vault._reverse == {}
    assert vault.audit_log() == []
    assert vault._last_access == before_access

    record = vault.seed(pseudonym, original)

    assert vault.export_mapping() == {pseudonym: original}
    assert vault.audit_log() == [
        {
            "action": "seed",
            "entity_id": record.entity_id,
            "timestamp": vault.audit_log()[0]["timestamp"],
            "session_id": vault.session_id,
        }
    ]


@pytest.mark.parametrize(
    "observer",
    [
        "get_by_entity_id",
        "get_by_pseudonym",
        "get_by_original",
        "export_mapping",
        "trusted_pseudonyms",
    ],
)
def test_failing_seed_is_not_visible_to_concurrent_observers(observer):
    import threading

    vault = SessionVault()
    pseudonym = "[ชื่อ_1]"
    original = "สมชาย ใจดี"
    seed_reached_audit = threading.Event()
    release_seed = threading.Event()
    observer_finished = threading.Event()
    real_audit = vault._audit
    published_id = {}
    seed_errors = []
    observer_errors = []
    observed = []

    def failing_audit(action, entity_id):
        real_audit(action, entity_id)
        if action == "seed":
            published_id["value"] = entity_id
            seed_reached_audit.set()
            release_seed.wait(timeout=5)
            raise RuntimeError("injected audit failure")

    vault._audit = failing_audit

    def run_seed():
        try:
            vault.seed(pseudonym, original)
        except Exception as exc:
            seed_errors.append(exc)

    def run_observer():
        try:
            if observer == "get_by_entity_id":
                result = vault.get_by_entity_id(published_id["value"])
            elif observer == "get_by_pseudonym":
                result = vault.get_by_pseudonym(pseudonym)
            elif observer == "get_by_original":
                result = vault.get_by_original(original)
            else:
                result = getattr(vault, observer)()
            observed.append(result)
        except Exception as exc:
            observer_errors.append(exc)
        finally:
            observer_finished.set()

    seeder = threading.Thread(target=run_seed)
    reader = threading.Thread(target=run_observer)
    seeder.start()
    assert seed_reached_audit.wait(timeout=5)
    reader.start()
    assert not observer_finished.wait(timeout=0.05)

    release_seed.set()
    seeder.join(timeout=5)
    reader.join(timeout=5)

    assert not seeder.is_alive()
    assert not reader.is_alive()
    assert len(seed_errors) == 1
    assert isinstance(seed_errors[0], RuntimeError)
    assert observer_errors == []
    if observer in {"export_mapping", "trusted_pseudonyms"}:
        assert observed == [{} if observer == "export_mapping" else set()]
    else:
        assert observed == [None]
    assert vault._table == {}
    assert vault._reverse == {}
    retained_audit = vault.audit_log()
    assert all(entry["action"] != "seed" for entry in retained_audit)
    assert pseudonym not in str(retained_audit)
    assert original not in str(retained_audit)


def test_concurrent_seed_and_write_cannot_claim_one_pseudonym():
    import threading

    vault = SessionVault()
    pseudonym = "[ชื่อ_1]"
    seed_reached_publish = threading.Event()
    release_seed = threading.Event()
    write_finished = threading.Event()
    real_touch = vault._touch
    seed_errors = []
    write_errors = []

    def pausing_touch():
        seed_reached_publish.set()
        release_seed.wait(timeout=5)
        real_touch()

    vault._touch = pausing_touch

    def run_seed():
        try:
            vault.seed(pseudonym, "สมชาย ใจดี")
        except Exception as exc:
            seed_errors.append(exc)

    def run_write():
        try:
            vault.write(_make_record(original="สมหญิง ร้ายกาจ", pseudonym=pseudonym))
        except Exception as exc:
            write_errors.append(exc)
        finally:
            write_finished.set()

    seeder = threading.Thread(target=run_seed)
    writer = threading.Thread(target=run_write)
    seeder.start()
    assert seed_reached_publish.wait(timeout=5)
    writer.start()
    assert not write_finished.wait(timeout=0.05)

    release_seed.set()
    seeder.join(timeout=5)
    writer.join(timeout=5)

    assert not seeder.is_alive()
    assert not writer.is_alive()
    assert seed_errors == []
    assert len(write_errors) == 1
    assert isinstance(write_errors[0], ValueError)
    assert vault.export_mapping() == {pseudonym: "สมชาย ใจดี"}
    assert len(vault._table) == 1
    assert [entry["action"] for entry in vault.audit_log()] == ["seed"]


@pytest.mark.parametrize("operation", ["clone", "snapshot", "clear"])
def test_write_blocks_lifecycle_operation_until_its_audit_finishes(operation):
    import threading

    vault = SessionVault()
    write_reached_audit = threading.Event()
    release_write = threading.Event()
    lifecycle_finished = threading.Event()
    real_audit = vault._audit
    errors = []
    outcome = {}

    def pausing_audit(action, entity_id):
        if action == "write":
            write_reached_audit.set()
            release_write.wait(timeout=5)
        real_audit(action, entity_id)

    vault._audit = pausing_audit
    record = _make_record()

    def run_write():
        try:
            vault.write(record)
        except Exception as exc:
            errors.append(exc)

    def run_lifecycle_operation():
        try:
            outcome["value"] = getattr(vault, operation)()
        except Exception as exc:
            errors.append(exc)
        finally:
            lifecycle_finished.set()

    writer = threading.Thread(target=run_write)
    lifecycle = threading.Thread(target=run_lifecycle_operation)
    writer.start()
    assert write_reached_audit.wait(timeout=5)
    lifecycle.start()
    assert not lifecycle_finished.wait(timeout=0.05)

    release_write.set()
    writer.join(timeout=5)
    lifecycle.join(timeout=5)

    assert not writer.is_alive()
    assert not lifecycle.is_alive()
    assert errors == []
    if operation == "clone":
        cloned = outcome["value"]
        assert cloned._table == {record.entity_id: record}
        assert [entry["action"] for entry in cloned.audit_log()] == ["write"]
    elif operation == "snapshot":
        snapshot = outcome["value"]
        assert snapshot["_table"] == {record.entity_id: record}
        assert snapshot["_reverse"] == {record.pseudonym: record.entity_id}
    else:
        assert outcome["value"] is None
        assert vault._table == {}
        assert vault._reverse == {}
        assert [entry["action"] for entry in vault.audit_log()] == ["write", "clear"]


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
    real = _make_record(
        original="1234",
        pseudonym="[โทรศัพท์_1]",
        data_type="PHONE",
    )
    vault.write(real)
    assert vault.get_by_original("1234", data_type="PHONE") is real
