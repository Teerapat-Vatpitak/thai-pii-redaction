"""Tests for Step 6: Reverse Mapping (de-anonymization)."""

import time
import uuid
import pytest
from pii_redactor.reverse_mapper import reverse_map
from pii_redactor.models import (
    AIResponse,
    EntityRegistry,
    Entity,
    VaultRecord,
    ReverseResult,
)
from pii_redactor.session_vault import SessionVault, VaultTimeoutError


def _make_ai_response(text: str) -> AIResponse:
    """Create an AIResponse for testing."""
    return AIResponse(text=text, request_id=str(uuid.uuid4()), latency=0.1)


def _make_vault_with_mapping(
    pseudonym: str, original: str, data_type: str = "EMAIL"
) -> SessionVault:
    """Create a vault with a single pseudonym mapping."""
    vault = SessionVault()
    entity_id = str(uuid.uuid4())
    vault.write(
        VaultRecord(
            entity_id=entity_id,
            original=original,
            pseudonym=pseudonym,
            type="FP",
            data_type=data_type,
            span=(0, len(original)),
            timestamp=time.monotonic(),
        )
    )
    return vault


def test_reverse_map_basic():
    """Test basic reverse mapping of a single pseudonym."""
    vault = _make_vault_with_mapping("fake@test.com", "real@example.com")
    ai_response = _make_ai_response("Please contact fake@test.com for info.")
    registry = EntityRegistry(entities=[], fp_count=0, tb_count=0)
    result = reverse_map(ai_response, registry, vault)
    assert isinstance(result, ReverseResult)
    assert "real@example.com" in result.text
    assert "fake@test.com" not in result.text


def test_reverse_map_returns_reverse_result():
    """Test that reverse_map returns a ReverseResult with required attributes."""
    vault = _make_vault_with_mapping("0812345678", "0919876543", data_type="PHONE")
    ai_response = _make_ai_response("Call 0812345678.")
    registry = EntityRegistry(entities=[], fp_count=0, tb_count=0)
    result = reverse_map(ai_response, registry, vault)
    assert hasattr(result, "text")
    assert hasattr(result, "flags")
    assert hasattr(result, "audit_summary")
    assert isinstance(result.flags, list)
    assert isinstance(result.audit_summary, dict)


def test_reverse_map_multiple_pseudonyms():
    """Test reverse mapping with multiple pseudonyms."""
    vault = SessionVault()
    entity_id_1 = str(uuid.uuid4())
    entity_id_2 = str(uuid.uuid4())
    vault.write(
        VaultRecord(
            entity_id=entity_id_1,
            original="สมชาย",
            pseudonym="วิทยา",
            type="TB",
            data_type="NAME",
            span=(0, 6),
            timestamp=time.monotonic(),
        )
    )
    vault.write(
        VaultRecord(
            entity_id=entity_id_2,
            original="real@example.com",
            pseudonym="fake@test.com",
            type="FP",
            data_type="EMAIL",
            span=(7, 23),
            timestamp=time.monotonic(),
        )
    )
    ai_response = _make_ai_response("วิทยา contacted fake@test.com.")
    registry = EntityRegistry(entities=[], fp_count=0, tb_count=0)
    result = reverse_map(ai_response, registry, vault)
    assert "สมชาย" in result.text
    assert "real@example.com" in result.text
    assert "วิทยา" not in result.text
    assert "fake@test.com" not in result.text


def test_reverse_map_empty_vault():
    """Test reverse mapping with an empty vault."""
    vault = SessionVault()
    ai_response = _make_ai_response("No pseudonyms here.")
    registry = EntityRegistry(entities=[], fp_count=0, tb_count=0)
    result = reverse_map(ai_response, registry, vault)
    assert result.text == "No pseudonyms here."


def test_reverse_map_empty_response_raises():
    """Test that empty response raises ValueError."""
    vault = SessionVault()
    ai_response = _make_ai_response("")
    registry = EntityRegistry(entities=[], fp_count=0, tb_count=0)
    with pytest.raises(ValueError):
        reverse_map(ai_response, registry, vault)


def test_reverse_map_idle_vault_raises():
    """Test that idle vault raises VaultTimeoutError."""
    vault = SessionVault(idle_timeout_s=0)
    vault._last_access = time.monotonic() - 10
    ai_response = _make_ai_response("text")
    registry = EntityRegistry(entities=[], fp_count=0, tb_count=0)
    with pytest.raises(VaultTimeoutError):
        reverse_map(ai_response, registry, vault)


def test_reverse_map_no_match_no_flags():
    """Test reverse mapping when pseudonym is not in response."""
    vault = _make_vault_with_mapping("fake@test.com", "real@example.com")
    # Response doesn't contain the pseudonym
    ai_response = _make_ai_response("This response has no pseudonyms.")
    registry = EntityRegistry(entities=[], fp_count=0, tb_count=0)
    result = reverse_map(ai_response, registry, vault)
    # Should not have residue flag since pseudonym wasn't in text
    assert result.text == "This response has no pseudonyms."


def test_reverse_map_audit_summary_keys():
    """Test that audit summary contains required keys."""
    vault = _make_vault_with_mapping("fake@test.com", "real@example.com")
    ai_response = _make_ai_response("email: fake@test.com")
    registry = EntityRegistry(entities=[], fp_count=0, tb_count=0)
    result = reverse_map(ai_response, registry, vault)
    assert "total_entities" in result.audit_summary
    assert "replaced_count" in result.audit_summary
    assert "request_id" in result.audit_summary
    assert result.audit_summary["request_id"] == ai_response.request_id


def test_reverse_map_longest_first():
    """Longer pseudonyms replaced before shorter ones to avoid partial matches."""
    vault = SessionVault()
    eid1 = str(uuid.uuid4())
    eid2 = str(uuid.uuid4())
    # Shorter string is a substring of longer
    vault.write(
        VaultRecord(
            entity_id=eid1,
            original="orig1",
            pseudonym="alice",
            type="FP",
            data_type="NAME",
            span=(0, 5),
            timestamp=time.monotonic(),
        )
    )
    vault.write(
        VaultRecord(
            entity_id=eid2,
            original="orig2",
            pseudonym="alice.100@example.com",
            type="FP",
            data_type="EMAIL",
            span=(6, 11),
            timestamp=time.monotonic(),
        )
    )
    # "alice" is a prefix of "alice.100@example.com"
    ai_response = _make_ai_response("alice.100@example.com and alice")
    registry = EntityRegistry(entities=[], fp_count=0, tb_count=0)
    result = reverse_map(ai_response, registry, vault)
    assert "orig1" in result.text
    assert "orig2" in result.text
    assert "alice" not in result.text
