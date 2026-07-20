"""Tests for Step 6: Reverse Mapping (de-anonymization)."""

import time
import uuid

import pytest

from pii_redactor.models import (
    AIResponse,
    Entity,
    EntityRegistry,
    ReverseResult,
    VaultRecord,
)
from pii_redactor.reverse_mapper import reverse_map
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


def test_reverse_map_surrogate_not_spliced_into_longer_number():
    """VAULT-1: a surrogate value that is a substring of a LONGER digit run in
    the AI reply must not be spliced — that injects the real value mid-number."""
    vault = _make_vault_with_mapping("0812345678", "0899999999", data_type="PHONE")
    ai_response = _make_ai_response("อ้างอิงเลขที่ 08123456789012 ครับ")
    registry = EntityRegistry(entities=[], fp_count=0, tb_count=0)
    result = reverse_map(ai_response, registry, vault)
    assert "0899999999" not in result.text
    assert "08123456789012" in result.text


def test_reverse_map_surrogate_not_spliced_into_thai_word():
    """VAULT-1: a surrogate name that is a substring of a longer Thai word must
    not be spliced (Thai has no word spaces, so this is common)."""
    vault = _make_vault_with_mapping("วรรณ", "สมหญิง ใจดี", data_type="NAME")
    ai_response = _make_ai_response("ผมชอบอ่านวรรณกรรมไทย")
    registry = EntityRegistry(entities=[], fp_count=0, tb_count=0)
    result = reverse_map(ai_response, registry, vault)
    assert "สมหญิง" not in result.text
    assert "วรรณกรรม" in result.text


def test_reverse_map_surrogate_not_spliced_into_latin_token():
    """VAULT-1 (Latin): Latin has word spaces, so a surrogate email/passport
    glued to a longer Latin token on EITHER side is embedded and must not be
    spliced — otherwise a real email/passport is injected mid-token silently."""
    vault = _make_vault_with_mapping("bob.99@test.co.th", "nattapong@gmail.com", data_type="EMAIL")
    ai_response = _make_ai_response("prefixbob.99@test.co.th here")
    registry = EntityRegistry(entities=[], fp_count=0, tb_count=0)
    result = reverse_map(ai_response, registry, vault)
    assert "nattapong@gmail.com" not in result.text

    vault2 = _make_vault_with_mapping("AB1234567", "CD7654321", data_type="PASSPORT")
    resp2 = _make_ai_response("refAB1234567end")
    result2 = reverse_map(resp2, registry, vault2)
    assert "CD7654321" not in result2.text


def test_reverse_map_standalone_latin_surrogate_restored():
    """VAULT-1 guard: a standalone (delimited) Latin surrogate still restores."""
    vault = _make_vault_with_mapping("bob.99@test.co.th", "nattapong@gmail.com", data_type="EMAIL")
    resp = _make_ai_response("ส่งเมลไปที่ bob.99@test.co.th นะครับ")
    registry = EntityRegistry(entities=[], fp_count=0, tb_count=0)
    result = reverse_map(resp, registry, vault)
    assert "nattapong@gmail.com" in result.text


def test_reverse_map_standalone_surrogate_still_restored():
    """VAULT-1 guard: the boundary check must still restore a standalone
    surrogate that is not glued to same-class characters."""
    vault = _make_vault_with_mapping("0812345678", "0899999999", data_type="PHONE")
    ai_response = _make_ai_response("โทร 0812345678 ได้เลย")
    registry = EntityRegistry(entities=[], fp_count=0, tb_count=0)
    result = reverse_map(ai_response, registry, vault)
    assert "0899999999" in result.text

    vault2 = _make_vault_with_mapping("วรรณ", "สมหญิง ใจดี", data_type="NAME")
    resp2 = _make_ai_response("ติดต่อคุณ วรรณ ครับ")
    result2 = reverse_map(resp2, registry, vault2)
    assert "สมหญิง ใจดี" in result2.text


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


def test_audit_summary_lists_replaced_pseudonyms():
    """Additive key used by SessionService to build the v2 replaced[] pairs."""
    import time as _t
    import uuid as _u

    from pii_redactor.models import AIResponse, EntityRegistry, VaultRecord
    from pii_redactor.reverse_mapper import reverse_map
    from pii_redactor.session_vault import SessionVault

    vault = SessionVault()
    vault.write(
        VaultRecord(
            entity_id=str(_u.uuid4()),
            original="a@b.co",
            pseudonym="[อีเมล_1]",
            type="FP",
            data_type="EMAIL",
            span=(0, 6),
            timestamp=_t.monotonic(),
        )
    )
    resp = AIResponse(text="ส่งไปที่ [อีเมล_1]", request_id="r", latency=0.0)
    result = reverse_map(resp, EntityRegistry(entities=[], fp_count=0, tb_count=0), vault)
    assert result.audit_summary["replaced_pseudonyms"] == ["[อีเมล_1]"]


def test_reverse_map_pseudonym_substring_of_original():
    """A short pseudonym that is a substring of ANOTHER entity's restored
    original must not corrupt that original. Global str.replace (even
    longest-first) re-scans already-restored text; positional replacement does
    not. Here 'abc' is a substring of the original 'contact abc123'."""
    vault = SessionVault()
    vault.write(
        VaultRecord(
            entity_id=str(uuid.uuid4()),
            original="contact abc123",
            pseudonym="xyzz",
            type="FP",
            data_type="NAME",
            span=(0, 4),
            timestamp=time.monotonic(),
        )
    )
    vault.write(
        VaultRecord(
            entity_id=str(uuid.uuid4()),
            original="REALB",
            pseudonym="abc",
            type="FP",
            data_type="NAME",
            span=(5, 8),
            timestamp=time.monotonic(),
        )
    )
    ai_response = _make_ai_response("xyzz then abc")
    registry = EntityRegistry(entities=[], fp_count=0, tb_count=0)
    result = reverse_map(ai_response, registry, vault)
    # 'abc' inside the restored 'contact abc123' must survive intact
    assert result.text == "contact abc123 then REALB"


def test_reverse_map_repeated_pii_no_false_incomplete():
    """Same person mentioned N times = N entities but ONE pseudonym. A full
    restore must NOT raise incomplete_reverse (completeness counts distinct
    pseudonyms, not raw entities)."""
    vault = SessionVault()
    eids = [str(uuid.uuid4()) for _ in range(3)]
    for eid in eids:
        vault.write(
            VaultRecord(
                entity_id=eid,
                original="สมชาย",
                pseudonym="[ชื่อ_1]",
                type="TB",
                data_type="NAME",
                span=(0, 6),
                timestamp=time.monotonic(),
            )
        )
    entities = [
        Entity(
            entity_id=eid,
            redact_type="TB",
            data_type="NAME",
            span=(0, 6),
            score=0.85,
            original_text="สมชาย",
        )
        for eid in eids
    ]
    registry = EntityRegistry(entities=entities, fp_count=0, tb_count=3)
    ai_response = _make_ai_response("[ชื่อ_1] และ [ชื่อ_1] และ [ชื่อ_1] มาพบกัน")
    result = reverse_map(ai_response, registry, vault)
    assert "[ชื่อ_1]" not in result.text
    incomplete = [f for f in result.flags if "incomplete_reverse" in f]
    assert incomplete == []
