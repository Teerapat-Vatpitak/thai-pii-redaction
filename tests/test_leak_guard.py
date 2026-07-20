"""Shared outbound leak scan (extracted from ai_client for web/CLI reuse)."""

import time
import uuid

from pii_redactor.leak_guard import scan_outbound_leaks
from pii_redactor.models import VaultRecord
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
