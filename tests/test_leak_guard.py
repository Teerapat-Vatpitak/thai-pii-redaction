"""Shared outbound leak scan (extracted from ai_client for web/CLI reuse)."""

import time
import uuid

import pytest

import pii_redactor.leak_guard as leak_guard_module
from pii_redactor.leak_guard import (
    OutboundGuardContext,
    OutboundPolicyError,
    enforce_outbound_policy,
    scan_obfuscated_structured_entities,
    scan_outbound_leaks,
    scan_residual_signals,
)
from pii_redactor.models import Entity, VaultRecord
from pii_redactor.session_vault import SessionVault


def _vault(pairs):
    v = SessionVault()
    for data_type, original, pseudonym in pairs:
        v.write(
            VaultRecord(
                entity_id=str(uuid.uuid4()),
                original=original,
                pseudonym=pseudonym,
                type="FP" if data_type not in ("NAME", "ADDRESS") else "TB",
                data_type=data_type,
                span=(0, 1),
                timestamp=time.monotonic(),
            )
        )
    return v


def test_scan_clean_pseudonymized_text_returns_empty():
    vault = _vault([("NAME", "สมชาย ใจดี", "บุญชัย"), ("PHONE", "081-234-5678", "098-625-9566")])
    text = "ผมชื่อ บุญชัย เบอร์ 098-625-9566 ขอลางาน 3 วันครับ"
    assert scan_outbound_leaks(text, vault) == []


def test_scan_flags_real_thai_id():
    vault = _vault([("NAME", "สมชาย ใจดี", "บุญชัย")])
    text = "ผมชื่อ บุญชัย เลขบัตรประชาชน 1101700230708"
    leaks = scan_outbound_leaks(text, vault)
    assert any(e.data_type == "THAI_ID" for e in leaks)


def test_scan_flags_cue_split_name():
    vault = _vault([("NAME", "สมชาย ใจดี", "บุญชัย")])
    text = "เรียน นาย บุญชัย วิชัย ทองแท้ ครับ"
    leaks = scan_outbound_leaks(text, vault)
    assert any(e.data_type == "NAME" for e in leaks)


def test_scan_allows_exact_trusted_pseudonym_alone():
    pseudonym = "eve.2068@example.com"
    vault = _vault([("EMAIL", "synthetic-source", pseudonym)])

    assert scan_outbound_leaks(pseudonym, vault) == []


def test_scan_flags_larger_email_containing_trusted_pseudonym():
    pseudonym = "eve.2068@example.com"
    text = "x" + pseudonym
    vault = _vault([("EMAIL", "synthetic-source", pseudonym)])

    leaks = scan_outbound_leaks(text, vault)

    assert any(entity.data_type == "EMAIL" for entity in leaks)
    assert all(entity.original_text == text[slice(*entity.span)] for entity in leaks)


def test_scan_flags_postcode_beside_trusted_address():
    pseudonym = "556 เขตสาทร"
    text = f"{pseudonym} 10110"
    vault = _vault([("ADDRESS", "synthetic-source", pseudonym)])

    leaks = scan_outbound_leaks(text, vault)

    assert any(entity.data_type == "POSTAL_CODE" for entity in leaks)
    assert all(entity.original_text == text[slice(*entity.span)] for entity in leaks)


def test_scan_never_raises_on_empty_vault():
    assert isinstance(scan_outbound_leaks("ข้อความธรรมดา", SessionVault()), list)


def test_scan_residual_digits_excuses_only_process_minted_replacement():
    vault = _vault([("ID_NUMBER", "synthetic-source", "6801234")])
    assert scan_residual_signals("ส่งต่อ 6801234", vault) == []


def test_identity_or_embedded_original_record_is_never_trusted():
    original = "1101700230708"
    for pseudonym in (original, f"[MASK-{original}]"):
        vault = _vault([("THAI_ID", original, pseudonym)])

        assert scan_outbound_leaks(pseudonym, vault)
        assert scan_residual_signals(pseudonym, vault)


def test_scan_residual_digits_keeps_exact_negative_boundaries():
    vault = SessionVault()
    assert scan_residual_signals("ยอดขาย 100,000 บาท", vault) == []
    assert scan_residual_signals("อ้างอิง REF-004-512", vault) == []
    assert scan_residual_signals("รหัสสั้น 12345", vault) == []


def test_scan_residual_digits_covers_contiguous_thai_digits():
    assert scan_residual_signals("เอกสารหมายเลข ๖๘๐๑๒๓๔", SessionVault())


@pytest.mark.parametrize(
    "hidden",
    [
        "\u00ad",
        "\u200b",
        "\u200c",
        "\u200d",
        "\u202e",
        "\u2060",
        "\u2066",
        "\ufeff",
    ],
)
@pytest.mark.parametrize(
    ("template", "expected_type"),
    [
        ("โทร 081{hidden}-234-5678", "PHONE"),
        ("เลข 1101{hidden}700230708", "THAI_ID"),
        ("อีเมล synthetic.user{hidden}@example.com", "EMAIL"),
    ],
)
def test_scan_residual_structured_pii_through_embedded_format_controls(
    hidden,
    template,
    expected_type,
):
    signals = scan_residual_signals(
        template.format(hidden=hidden),
        OutboundGuardContext(),
    )

    assert f"obfuscated_structured:{expected_type}" in signals


def test_obfuscated_structured_entity_maps_back_to_exact_source_span():
    private_value = "081\u202e-234-5678"
    text = f"โทร {private_value} ตอนนี้"

    entities = scan_obfuscated_structured_entities(text)

    phone = next(entity for entity in entities if entity.data_type == "PHONE")
    assert text[phone.span[0] : phone.span[1]] == private_value
    assert phone.original_text == private_value


def test_scan_residual_detects_checksum_valid_single_spaced_iban():
    text = "IBAN GB82 WEST 1234 5698 7654 32"

    entities = scan_obfuscated_structured_entities(text)

    iban = next(entity for entity in entities if entity.data_type == "IBAN")
    assert text[iban.span[0] : iban.span[1]] == "GB82 WEST 1234 5698 7654 32"
    assert "obfuscated_structured:IBAN" in scan_residual_signals(
        text,
        OutboundGuardContext(),
    )


def test_spaced_iban_scan_bounds_group_matching(monkeypatch):
    real_pattern = leak_guard_module._SPACED_IBAN_GROUP_RE

    class CountingPattern:
        def __init__(self):
            self.calls = 0

        def match(self, text, pos=0):
            self.calls += 1
            return real_pattern.match(text, pos)

    counting_pattern = CountingPattern()
    monkeypatch.setattr(
        leak_guard_module,
        "_SPACED_IBAN_GROUP_RE",
        counting_pattern,
    )
    group_count = 160

    assert leak_guard_module._single_spaced_iban_views(" ".join(["AA00"] * group_count)) == []
    assert counting_pattern.calls <= group_count * 9


def test_spaced_iban_scan_finds_valid_value_after_long_invalid_prefix():
    valid = "GB82 WEST 1234 5698 7654 32"
    text = " ".join([*(["AA00"] * 160), valid])

    entities = scan_obfuscated_structured_entities(text)

    iban = next(entity for entity in entities if entity.data_type == "IBAN")
    assert text[iban.span[0] : iban.span[1]] == valid


def test_scan_residual_ignores_checksum_invalid_single_spaced_iban_shape():
    text = "รหัสกลุ่ม GB00 TEST 1234 5678 9012 34"

    assert scan_obfuscated_structured_entities(text) == []
    assert scan_residual_signals(text, OutboundGuardContext()) == []


@pytest.mark.parametrize(
    ("text", "expected_type"),
    [
        ("โทร 081  234  5678", "PHONE"),
        ("เลข 1101  7002  30708", "THAI_ID"),
    ],
)
def test_scan_residual_structured_pii_through_repeated_internal_spaces(
    text,
    expected_type,
):
    assert f"obfuscated_structured:{expected_type}" in scan_residual_signals(
        text, OutboundGuardContext()
    )


@pytest.mark.parametrize(
    ("text", "expected_type"),
    [
        ("บัตร 4111\u200b-1111-1111-1111", "CREDIT_CARD"),
        ("IBAN GB82\u200bWEST12345698765432", "IBAN"),
        ("บัญชี 123\u200b-4-56789-0", "BANK_ACCOUNT"),
        ("หนังสือเดินทาง AA12\u200b34567", "PASSPORT"),
        ("รหัสนักศึกษา 6501\u200b4477", "STUDENT_ID"),
        ("HN 12\u200b3456", "MEDICAL_ID"),
        ("ทะเบียนรถ ขก\u200b 4471", "VEHICLE_PLATE"),
        ("ที่อยู่ 12\u200b/3 ถนนสุขุมวิท", "ADDRESS"),
        ("ที่อยู่กรุงเทพ 10\u200b100", "POSTAL_CODE"),
        ("วันเกิด 01\u200b/02/2540", "DATE_OF_BIRTH"),
    ],
)
def test_scan_residual_covers_other_detector_confirmed_structured_types(
    text,
    expected_type,
):
    assert f"obfuscated_structured:{expected_type}" in scan_residual_signals(
        text, OutboundGuardContext()
    )


@pytest.mark.parametrize(
    "text",
    [
        "ข้อความ\u200bทั่วไป",
        "ข้อความ\u200cทั่วไป",
        "ข้อความ\u200dทั่วไป",
        "ข้อความ\u202eทั่วไป",
        "ข้อความ\u2060ทั่วไป",
        "ข้อความ\u2066ทั่วไป",
        "ข้อความ\u00adทั่วไป",
        "ข้อความ\ufeffทั่วไป",
        "เว้น  สองช่องในข้อความทั่วไป",
        "ยอดขาย 12  345  678 บาท",
        "ยอดขาย 100  000 บาท",
    ],
)
def test_scan_residual_ignores_unrelated_format_controls_and_repeated_spaces(text):
    assert scan_residual_signals(text, OutboundGuardContext()) == []


def test_scan_residual_obfuscated_structured_value_excuses_only_trusted_pseudonym():
    pseudonym = "081\u200b-234-5678"
    vault = _vault([("PHONE", "synthetic-source", pseudonym)])

    assert scan_residual_signals(f"ส่งต่อ {pseudonym}", vault) == []
    assert scan_residual_signals(pseudonym, OutboundGuardContext())


def test_policy_reports_only_safe_type_for_obfuscated_structured_value():
    private_value = "4111\u200b-1111-1111-1111"

    with pytest.raises(OutboundPolicyError) as excinfo:
        enforce_outbound_policy(
            f"บัตร {private_value}",
            guard_context=OutboundGuardContext(),
        )

    assert excinfo.value.leak_types == ["CREDIT_CARD"]
    assert excinfo.value.policy_categories == ["structured"]
    assert private_value not in str(excinfo.value)
    assert private_value not in str(vars(excinfo.value))


def test_policy_error_retains_only_safe_types_and_distinct_categories():
    structured_secret = "synthetic-structured-secret"
    text_secret = "synthetic-text-secret"
    leaks = [
        Entity(
            entity_id="structured",
            redact_type="FP",
            data_type="THAI_ID",
            span=(0, 1),
            score=1.0,
            original_text=structured_secret,
        ),
        Entity(
            entity_id="text",
            redact_type="TB",
            data_type="NAME",
            span=(2, 3),
            score=0.9,
            original_text=text_secret,
        ),
    ]

    with pytest.raises(OutboundPolicyError) as excinfo:
        enforce_outbound_policy(
            "masked output",
            guard_context=OutboundGuardContext(),
            scan_leaks=lambda _text, _context: leaks,
            scan_residual=lambda _text, _context: ["orphan_digits:7"],
        )

    error = excinfo.value
    assert error.leak_types == ["NAME", "ORPHAN_DIGITS", "THAI_ID"]
    assert error.policy_categories == [
        "detector_independent",
        "structured",
        "text",
    ]
    assert error.category_count == 3
    assert structured_secret not in str(error)
    assert text_secret not in str(vars(error))


def test_policy_error_replaces_pii_shaped_injected_type_label():
    injected = "PII_1101700230708"

    error = OutboundPolicyError(
        ["THAI_ID", injected],
        policy_categories=["structured"],
    )

    assert error.leak_types == ["THAI_ID", "UNCLASSIFIED_RESIDUAL"]
    assert injected not in str(error)
    assert injected not in str(vars(error))
