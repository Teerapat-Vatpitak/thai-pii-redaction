"""Shared outbound leak scan (extracted from ai_client for web/CLI reuse)."""

import time
import uuid

import pytest

from pii_redactor.leak_guard import (
    OutboundGuardContext,
    OutboundPolicyError,
    enforce_outbound_policy,
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
