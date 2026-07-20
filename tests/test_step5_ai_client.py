"""Tests for Step 5 AI client integration."""
import time
import uuid
from abc import ABC

import httpx
import pytest

from pii_redactor.ai_client import (
    AIProvider,
    FakeLLMProvider,
    PreSendValidationError,
    send_to_ai,
)
from pii_redactor.models import AIResponse, EntityRegistry, VaultRecord
from pii_redactor.session_vault import SessionVault, VaultTimeoutError


def _make_vault_with_record(original: str = "test@example.com", pseudonym: str = "fake@test.com") -> tuple:
    """Create a vault with a single test record."""
    vault = SessionVault()
    entity_id = str(uuid.uuid4())
    vault.write(VaultRecord(
        entity_id=entity_id,
        original=original,
        pseudonym=pseudonym,
        type="FP",
        data_type="EMAIL",
        span=(0, len(original)),
        timestamp=time.monotonic(),
    ))
    return vault, entity_id


def test_fake_llm_returns_prompt():
    """Test that FakeLLMProvider returns the user prompt unchanged."""
    provider = FakeLLMProvider()
    result = provider.complete("system", "hello world")
    assert result == "hello world"


def test_send_to_ai_returns_ai_response():
    """Test that send_to_ai returns an AIResponse object."""
    vault = SessionVault()
    registry = EntityRegistry(entities=[], fp_count=0, tb_count=0)
    provider = FakeLLMProvider()
    result = send_to_ai("safe text with no PII", registry, vault, provider)
    assert isinstance(result, AIResponse)
    assert isinstance(result.text, str)
    assert isinstance(result.request_id, str)
    assert result.latency >= 0.0


def test_send_to_ai_fake_provider_echoes():
    """Test that send_to_ai with FakeLLMProvider echoes the input."""
    vault = SessionVault()
    registry = EntityRegistry(entities=[], fp_count=0, tb_count=0)
    provider = FakeLLMProvider()
    result = send_to_ai("pseudonymized text here", registry, vault, provider)
    assert result.text == "pseudonymized text here"


def test_send_to_ai_vault_snapshot_restored_on_fatal_error():
    """Test that vault is restored to snapshot on fatal error."""
    vault, entity_id = _make_vault_with_record()
    registry = EntityRegistry(entities=[], fp_count=0, tb_count=0)

    class BrokenProvider(AIProvider):
        def complete(self, system, user, *, timeout=30.0):
            raise RuntimeError("Fatal failure")

    original_table_size = len(vault._table)
    with pytest.raises(RuntimeError):
        send_to_ai("text", registry, vault, BrokenProvider())
    # Vault should be restored
    assert len(vault._table) == original_table_size


def test_provider_is_abc():
    """Test that AIProvider is an ABC and FakeLLMProvider is a subclass."""
    assert issubclass(FakeLLMProvider, AIProvider)
    assert issubclass(AIProvider, ABC)


def test_send_to_ai_request_id_is_uuid():
    """Test that the request_id is a valid UUID."""
    vault = SessionVault()
    registry = EntityRegistry(entities=[], fp_count=0, tb_count=0)
    provider = FakeLLMProvider()
    result = send_to_ai("text", registry, vault, provider)
    parsed = uuid.UUID(result.request_id)
    assert str(parsed) == result.request_id


def test_pre_send_validation_idle_timeout():
    """Test that idle timeout is checked before sending."""
    vault = SessionVault(idle_timeout_s=0)
    vault._last_access = time.monotonic() - 10
    registry = EntityRegistry(entities=[], fp_count=0, tb_count=0)
    provider = FakeLLMProvider()
    with pytest.raises(VaultTimeoutError):
        send_to_ai("text", registry, vault, provider)


def _vault_with(records: dict[str, tuple[str, str]]) -> SessionVault:
    """Vault from {data_type: (original, pseudonym)}."""
    vault = SessionVault()
    for data_type, (original, pseudonym) in records.items():
        vault.write(VaultRecord(
            entity_id=str(uuid.uuid4()),
            original=original,
            pseudonym=pseudonym,
            type="TB" if data_type in ("NAME", "ADDRESS") else "FP",
            data_type=data_type,
            span=(0, len(original)),
            timestamp=time.monotonic(),
        ))
    return vault


def test_pre_send_allows_ner_span_swallowing_pseudonym():
    """CRF NER can emit a sloppy PERSON span that swallows words around an
    embedded pseudonym (e.g. 'หน่อยครับ\\nผมชื่อ บุญชัย'). That span is not an
    exact pseudonym match, but it is fully explained by pseudonym + ordinary
    words — the guard must not halt on it."""
    vault = _vault_with({
        "NAME": ("สมชาย ใจดี", "บุญชัย"),
        "PHONE": ("081-234-5678", "098-625-9566"),
        "EMAIL": ("somchai.j@example.co.th", "eve.2068@example.com"),
    })
    registry = EntityRegistry(entities=[], fp_count=0, tb_count=0)
    pseudonymized = (
        "ช่วยร่างอีเมลแจ้งลาป่วยให้หน่อยครับ\n"
        "ผมชื่อ บุญชัย รหัสพนักงาน EMP-10234\n"
        "เบอร์ติดต่อ 098-625-9566 อีเมล eve.2068@example.com\n"
        "ขอลา 3 วันตั้งแต่วันจันทร์หน้า ส่งถึงหัวหน้าแผนกให้ดูเป็นทางการหน่อยครับ"
    )
    result = send_to_ai(pseudonymized, registry, vault, FakeLLMProvider())
    assert result.text == pseudonymized


def test_pre_send_allows_fragment_inside_pseudonym():
    """NER can also re-detect a FRAGMENT of a pseudonym (e.g. the district part
    of a fake address). A span lying inside a pseudonym occurrence is not a leak."""
    vault = _vault_with({
        "ADDRESS": ("99/1 เขตบางรัก", "412 เขตพระโขนง"),
        "NAME": ("สมชาย ใจดี", "บุญชัย"),
    })
    registry = EntityRegistry(entities=[], fp_count=0, tb_count=0)
    pseudonymized = "ผมชื่อ บุญชัย อยู่บ้านเลขที่ 412 เขตพระโขนง มาหลายปีแล้วครับ"
    result = send_to_ai(pseudonymized, registry, vault, FakeLLMProvider())
    assert result.text == pseudonymized


def test_pre_send_allows_span_straddling_pseudonym_fragment():
    """NER can emit a span covering a FRAGMENT of one pseudonym plus a whole
    neighbouring pseudonym (e.g. 'เขตสาทร 3548205739' out of the address
    pseudonym '556 เขตสาทร' followed by a bank pseudonym). The remainder must
    be computed positionally — string-stripping whole pseudonyms leaves the
    fragment behind and re-flags it as ADDRESS."""
    vault = _vault_with({
        "NAME": ("วิชัย มั่งมี", "ชัยวัฒน์"),
        "THAI_ID": ("3-1009-02845-17-2", "8079110812780"),
        "ADDRESS": ("เลขที่บัญชี", "556 เขตสาทร"),
        "BANK_ACCOUNT": ("123-4-56789-0", "3548205739"),
        "PHONE": ("086-111-2233", "062-837-6229"),
    })
    registry = EntityRegistry(entities=[], fp_count=0, tb_count=0)
    pseudonymized = (
        "ช่วยเขียนคำร้องเรียนถึงธนาคารให้หน่อย\n"
        "ผมชื่อ ชัยวัฒน์ เลขบัตรประชาชน 8079110812780\n"
        "556 เขตสาทร 3548205739 เบอร์โทร 062-837-6229\n"
        "ถูกหักค่าธรรมเนียมผิดปกติ 3 ครั้งในเดือนนี้ ขอให้ตรวจสอบและคืนเงินด้วยครับ"
    )
    result = send_to_ai(pseudonymized, registry, vault, FakeLLMProvider())
    assert result.text == pseudonymized


def test_pre_send_remainder_segments_scanned_separately():
    """Joining uncovered segments fabricates adjacency the text never had:
    'ผมชื่อ <pseudonym> เลขบัตรประชาชน' yields segments 'ผมชื่อ ' and
    ' เลขบัตรประชาชน' — glued together the name-cue booster reads
    'เลขบัตรประชาชน' as a name after the cue. Each segment must be scanned
    on its own."""
    vault = _vault_with({
        "NAME": ("วิชัย มั่งมี", "พิทักษ์"),
        "THAI_ID": ("3-1009-02845-17-2", "4504557656411"),
        "ADDRESS": ("เลขที่บัญชี", "927 อำเภอบางพลี"),
        "BANK_ACCOUNT": ("123-4-56789-0", "1444908633"),
        "PHONE": ("086-111-2233", "060-428-3914"),
    })
    registry = EntityRegistry(entities=[], fp_count=0, tb_count=0)
    pseudonymized = (
        "ช่วยเขียนคำร้องเรียนถึงธนาคารให้หน่อย\n"
        "ผมชื่อ พิทักษ์ เลขบัตรประชาชน 4504557656411\n"
        "927 อำเภอบางพลี 1444908633 เบอร์โทร 060-428-3914\n"
        "ถูกหักค่าธรรมเนียมผิดปกติ 3 ครั้งในเดือนนี้ ขอให้ตรวจสอบและคืนเงินด้วยครับ"
    )
    result = send_to_ai(pseudonymized, registry, vault, FakeLLMProvider())
    assert result.text == pseudonymized


def test_pre_send_blocks_leak_whose_cue_is_split_by_pseudonym():
    """A cue-detected span 'นาย <pseudonym> <real name>' must still halt even
    when the CRF cannot recognise the bare real name standalone: scanning the
    uncovered segments in isolation severs the title cue from the leaked name,
    so a cue-preserving re-check over the span window is required."""
    vault = _vault_with({"NAME": ("สมชาย ใจดี", "บุญชัย")})
    registry = EntityRegistry(entities=[], fp_count=0, tb_count=0)
    leaky = "เรียน นาย บุญชัย วิชัย ทองแท้ ครับ"
    with pytest.raises(PreSendValidationError):
        send_to_ai(leaky, registry, vault, FakeLLMProvider())


def test_pre_send_still_blocks_real_name_beside_pseudonyms():
    """A real (cue-detectable) name left in the outbound text must still halt
    the send even when pseudonyms are present elsewhere."""
    vault = _vault_with({
        "NAME": ("สมชาย ใจดี", "บุญชัย"),
        "PHONE": ("081-234-5678", "098-625-9566"),
    })
    registry = EntityRegistry(entities=[], fp_count=0, tb_count=0)
    leaky = (
        "ผมชื่อ บุญชัย เบอร์ 098-625-9566 "
        "ส่วนหัวหน้าผมชื่อ วิชัย ทองแท้ ครับ"
    )
    with pytest.raises(PreSendValidationError):
        send_to_ai(leaky, registry, vault, FakeLLMProvider())


def test_pre_send_still_blocks_real_thai_id_beside_pseudonyms():
    """A checksum-valid Thai ID left in the outbound text must still halt the send."""
    vault = _vault_with({"NAME": ("สมชาย ใจดี", "บุญชัย")})
    registry = EntityRegistry(entities=[], fp_count=0, tb_count=0)
    leaky = "ผมชื่อ บุญชัย เลขบัตรประชาชน 1101700230708"
    with pytest.raises(PreSendValidationError):
        send_to_ai(leaky, registry, vault, FakeLLMProvider())


def _http_status_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "http://test")
    response = httpx.Response(status, request=request)
    return httpx.HTTPStatusError(f"HTTP {status}", request=request, response=response)


def test_send_to_ai_4xx_is_fatal_no_retry():
    """Auth/bad-request errors will never succeed on retry: fail fast + rollback."""
    vault, _ = _make_vault_with_record()
    registry = EntityRegistry(entities=[], fp_count=0, tb_count=0)
    calls = {"n": 0}

    class AuthFailProvider(AIProvider):
        def complete(self, system, user, *, timeout=30.0):
            calls["n"] += 1
            raise _http_status_error(401)

    original_table_size = len(vault._table)
    with pytest.raises(httpx.HTTPStatusError):
        send_to_ai("text", registry, vault, AuthFailProvider())
    assert calls["n"] == 1  # no retry on non-transient HTTP error
    assert len(vault._table) == original_table_size  # vault rolled back


def test_send_to_ai_5xx_is_retried():
    """Server errors are transient: retry with backoff, then succeed."""
    vault = SessionVault()
    registry = EntityRegistry(entities=[], fp_count=0, tb_count=0)
    calls = {"n": 0}

    class FlakyProvider(AIProvider):
        def complete(self, system, user, *, timeout=30.0):
            calls["n"] += 1
            if calls["n"] == 1:
                raise _http_status_error(500)
            return user

    result = send_to_ai("text", registry, vault, FlakyProvider())
    assert calls["n"] == 2
    assert result.text == "text"


def test_pre_send_blocks_tb_name_leak():
    """A real Thai name left in the text must be caught before send.

    Regex/checksum (FP) does not catch names; the pre-send guard must also run
    the TB (NER) detector so a name/address leak cannot leave the device.
    """
    vault = SessionVault()  # empty: the name is not a known pseudonym
    registry = EntityRegistry(entities=[], fp_count=0, tb_count=0)
    provider = FakeLLMProvider()
    with pytest.raises(PreSendValidationError):
        send_to_ai("ผมชื่อสมชาย ใจดี ครับ", registry, vault, provider)
