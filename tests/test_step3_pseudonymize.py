"""Tests for Step 3: pseudonymization (fp_generator, tb_generator, anonymizer)."""
import uuid

import pytest

from pii_redactor.anonymizer.fp_generator import generate_fp
from pii_redactor.anonymizer.tb_generator import generate_tb
from pii_redactor.anonymizer.anonymizer import anonymize, PIILeakError
from pii_redactor.models import Entity, EntityRegistry, PseudonymizedDocument
from pii_redactor.session_vault import SessionVault

SALT = "test-salt-abc123"


# ---------------------------------------------------------------------------
# fp_generator tests
# ---------------------------------------------------------------------------

def test_generate_fp_thai_id():
    from pii_redactor.detectors.thai_id import is_valid_thai_id
    result = generate_fp("THAI_ID", "1101200012345", salt=SALT)
    assert len(result.replace("-", "").replace(" ", "")) == 13
    assert is_valid_thai_id(result.replace("-", "").replace(" ", ""))


def test_generate_fp_deterministic():
    r1 = generate_fp("EMAIL", "real@example.com", salt=SALT)
    r2 = generate_fp("EMAIL", "real@example.com", salt=SALT)
    assert r1 == r2


def test_generate_fp_different_originals():
    r1 = generate_fp("EMAIL", "alice@example.com", salt=SALT)
    r2 = generate_fp("EMAIL", "bob@example.com", salt=SALT)
    assert r1 != r2


def test_generate_fp_different_salts():
    r1 = generate_fp("EMAIL", "same@example.com", salt="salt1")
    r2 = generate_fp("EMAIL", "same@example.com", salt="salt2")
    assert r1 != r2


def test_generate_fp_phone():
    result = generate_fp("PHONE", "081-234-5678", salt=SALT)
    assert isinstance(result, str)
    assert len(result) > 0


def test_generate_fp_credit_card_luhn():
    from pii_redactor.detectors.fp_detector import _luhn_check
    result = generate_fp("CREDIT_CARD", "4532015112830366", salt=SALT)
    digits = result.replace("-", "").replace(" ", "")
    assert len(digits) == 16
    assert _luhn_check(digits)


# ---------------------------------------------------------------------------
# tb_generator tests
# ---------------------------------------------------------------------------

def test_generate_tb_name():
    result = generate_tb("NAME", "นาย ___ ทำงาน", salt=SALT, original="สมชาย")
    assert isinstance(result, str)
    assert len(result) > 0
    assert "___" not in result


def test_generate_tb_deterministic():
    r1 = generate_tb("NAME", "context ___", salt=SALT, original="สมชาย")
    r2 = generate_tb("NAME", "context ___", salt=SALT, original="สมชาย")
    assert r1 == r2


def test_generate_tb_address():
    result = generate_tb("ADDRESS", "อยู่ที่ ___", salt=SALT, original="123 ถนนสุขุมวิท")
    assert isinstance(result, str)


# ---------------------------------------------------------------------------
# anonymizer tests
# ---------------------------------------------------------------------------

def _make_entity(
    data_type: str,
    text: str,
    start: int,
    end: int,
    redact_type: str = "FP",
) -> Entity:
    return Entity(
        entity_id=str(uuid.uuid4()),
        redact_type=redact_type,
        data_type=data_type,
        span=(start, end),
        score=1.0,
        original_text=text[start:end],
    )


def test_anonymize_replaces_email():
    text = "contact wittaya.s@company.co.th for details"
    email_start = text.index("wittaya")
    email_end = text.index(" for")
    entity = _make_entity("EMAIL", text, email_start, email_end)
    registry = EntityRegistry(entities=[entity], fp_count=1, tb_count=0)
    vault = SessionVault()
    result = anonymize(text, registry, vault, salt=SALT)
    assert "wittaya.s@company.co.th" not in result.text
    assert isinstance(result.text, str)


def test_anonymize_vault_stores_mapping():
    text = "email: test@example.com here"
    start = text.index("test@")
    end = text.index(" here")
    entity = _make_entity("EMAIL", text, start, end)
    registry = EntityRegistry(entities=[entity], fp_count=1, tb_count=0)
    vault = SessionVault()
    result = anonymize(text, registry, vault, salt=SALT)
    record = vault.get_by_entity_id(entity.entity_id)
    assert record is not None
    assert record.original == "test@example.com"


def test_anonymize_empty_registry():
    text = "no PII here"
    registry = EntityRegistry(entities=[], fp_count=0, tb_count=0)
    vault = SessionVault()
    result = anonymize(text, registry, vault, salt=SALT)
    assert result.text == text


def test_anonymize_consistency():
    text = "call 081-234-5678 or 081-234-5678"
    e1 = _make_entity("PHONE", text, 5, 17)
    e2 = _make_entity("PHONE", text, 21, 33)
    registry = EntityRegistry(entities=[e1, e2], fp_count=2, tb_count=0)
    vault = SessionVault()
    result = anonymize(text, registry, vault, salt=SALT)
    assert "081-234-5678" not in result.text


def test_anonymize_returns_pseudonymized_document():
    text = "contact test@example.com"
    start = text.index("test@")
    entity = _make_entity("EMAIL", text, start, len(text))
    registry = EntityRegistry(entities=[entity], fp_count=1, tb_count=0)
    vault = SessionVault()
    result = anonymize(text, registry, vault, salt=SALT)
    assert isinstance(result, PseudonymizedDocument)
    assert result.session_id == vault.session_id


def test_anonymize_fn_scanner_entities_get_realistic_fake_values():
    """Regression: fn_scanner-detected THAI_ID/EMAIL must route through
    generate_fp (realistic fake value), not tb_generator's literal
    "[REDACTED_x]" fallback -- fn_scanner now tags them redact_type="FP"."""
    from pii_redactor.detectors.fn_scanner import scan_fn

    text = "id 1234567890123 email foo@bar.com"
    entities = scan_fn(text, [])
    assert {e.data_type for e in entities} == {"THAI_ID", "EMAIL"}
    assert all(e.redact_type == "FP" for e in entities)

    registry = EntityRegistry(
        entities=entities,
        fp_count=len(entities),
        tb_count=0,
    )
    vault = SessionVault()
    result = anonymize(text, registry, vault, salt=SALT)
    assert "[REDACTED_THAI_ID]" not in result.text
    assert "[REDACTED_EMAIL]" not in result.text
    assert "1234567890123" not in result.text
    assert "foo@bar.com" not in result.text
