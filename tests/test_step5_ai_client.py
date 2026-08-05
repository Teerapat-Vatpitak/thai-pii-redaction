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
    ProviderCallError,
    send_to_ai,
)
from pii_redactor.models import AIResponse, EntityRegistry, VaultRecord
from pii_redactor.session_vault import SessionVault, VaultTimeoutError

SYNTHETIC_AUTHORIZATION = "Bearer synthetic-provider-credential"
SYNTHETIC_OUTBOUND_TEXT = "synthetic-outbound-text"
SYNTHETIC_PROVIDER_BODY = "synthetic-provider-body"
SYNTHETIC_SYSTEM_PROMPT = "synthetic-system-prompt"
SYNTHETIC_VAULT_ORIGINAL = "synthetic-vault-original@example.invalid"


class _CredentialBearingProviderError(RuntimeError):
    def __init__(self, request: httpx.Request):
        self.request = request
        self.authorization = SYNTHETIC_AUTHORIZATION
        self.body = SYNTHETIC_PROVIDER_BODY
        super().__init__("provider call failed")


def _credentialed_http_status_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request(
        "POST",
        "https://provider.invalid/v1/complete",
        headers={"Authorization": SYNTHETIC_AUTHORIZATION},
        content=SYNTHETIC_PROVIDER_BODY.encode(),
    )
    response = httpx.Response(
        status,
        request=request,
        content=SYNTHETIC_PROVIDER_BODY.encode(),
    )
    return httpx.HTTPStatusError(
        "provider rejected request",
        request=request,
        response=response,
    )


def _credentialed_http_status_error_without_response() -> httpx.HTTPStatusError:
    request = httpx.Request(
        "POST",
        "https://provider.invalid/v1/complete",
        headers={"Authorization": SYNTHETIC_AUTHORIZATION},
        content=SYNTHETIC_PROVIDER_BODY.encode(),
    )
    return httpx.HTTPStatusError(
        "provider failed without a response",
        request=request,
        response=None,  # type: ignore[arg-type]
    )


def _credential_exception_group(
    message: str,
) -> tuple[ExceptionGroup, _CredentialBearingProviderError]:
    child = _CredentialBearingProviderError(
        httpx.Request(
            "POST",
            "https://provider.invalid/v1/complete",
            headers={"Authorization": SYNTHETIC_AUTHORIZATION},
            content=SYNTHETIC_PROVIDER_BODY.encode(),
        )
    )
    try:
        raise child
    except _CredentialBearingProviderError as error:
        return ExceptionGroup(message, [error]), child


def _exception_graph(error: BaseException) -> tuple[list[BaseException], str]:
    nodes: list[BaseException] = []
    material: list[str] = []
    pending: list[BaseException] = [error]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        nodes.append(current)
        material.extend((repr(current.args), repr(vars(current))))
        for linked in (current.__cause__, current.__context__):
            if linked is not None:
                pending.append(linked)
        if isinstance(current, BaseExceptionGroup):
            pending.extend(current.exceptions)
        for value in vars(current).values():
            if isinstance(value, BaseException):
                pending.append(value)
        if isinstance(current, httpx.HTTPError):
            request = current.request
            material.extend(
                (
                    str(request.url),
                    repr(dict(request.headers)),
                    repr(request.content),
                )
            )
            response = getattr(current, "response", None)
            if response is not None:
                material.append(repr(response.content))
    return nodes, "\n".join(material)


def _product_traceback_locals(error: BaseException) -> list[dict[str, object]]:
    frames = []
    traceback = error.__traceback__
    while traceback is not None:
        module = traceback.tb_frame.f_globals.get("__name__", "")
        if module.startswith(("pii_redactor.", "app.")):
            frames.append(dict(traceback.tb_frame.f_locals))
        traceback = traceback.tb_next
    return frames


def _assert_exception_graph_discarded(error: BaseException) -> None:
    pending = [error]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        assert current.__traceback__ is None
        assert current.__cause__ is None
        assert current.__context__ is None
        if isinstance(current, BaseExceptionGroup):
            pending.extend(current.exceptions)


def _assert_public_failure_scrubbed(
    error: BaseException,
    *,
    forbidden_objects: tuple[object, ...],
    forbidden_text: tuple[str, ...],
) -> None:
    nodes, graph_text = _exception_graph(error)
    assert nodes == [error]
    assert error.__cause__ is None
    assert error.__context__ is None

    frame_locals = _product_traceback_locals(error)
    assert frame_locals
    for forbidden in forbidden_objects:
        assert all(forbidden is not value for frame in frame_locals for value in frame.values())
    retained = graph_text + repr(frame_locals)
    for text in forbidden_text:
        assert text not in retained


def _write_synthetic_record(vault: SessionVault) -> None:
    vault.write(
        VaultRecord(
            entity_id="synthetic-vault-record",
            original=SYNTHETIC_VAULT_ORIGINAL,
            pseudonym="masked@example.invalid",
            type="FP",
            data_type="EMAIL",
            span=(0, len(SYNTHETIC_VAULT_ORIGINAL)),
            timestamp=time.monotonic(),
        )
    )


def _make_vault_with_record(
    original: str = "test@example.com", pseudonym: str = "fake@test.com"
) -> tuple:
    """Create a vault with a single test record."""
    vault = SessionVault()
    entity_id = str(uuid.uuid4())
    vault.write(
        VaultRecord(
            entity_id=entity_id,
            original=original,
            pseudonym=pseudonym,
            type="FP",
            data_type="EMAIL",
            span=(0, len(original)),
            timestamp=time.monotonic(),
        )
    )
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


def test_provider_rollback_cannot_resurrect_a_cleared_vault():
    vault, _ = _make_vault_with_record()
    registry = EntityRegistry(entities=[], fp_count=0, tb_count=0)

    class ClearingBrokenProvider(AIProvider):
        def complete(self, system, user, *, timeout=30.0):
            vault.clear()
            raise RuntimeError("Fatal failure")

    with pytest.raises(ProviderCallError, match="AI provider call failed"):
        send_to_ai("text", registry, vault, ClearingBrokenProvider())

    assert vault._table == {}
    assert vault._reverse == {}
    assert vault.audit_log()[-1]["action"] == "clear"


def test_complete_provider_call_rejects_poisoned_http_status_metadata():
    from pii_redactor.ai_client import complete_provider_call

    private_number = 1101700230708
    request = httpx.Request("POST", "https://provider.invalid/v1/complete")
    response = httpx.Response(private_number, request=request)
    retained_error = httpx.HTTPStatusError(
        "synthetic provider status",
        request=request,
        response=response,
    )

    class PoisonedStatusProvider(AIProvider):
        def complete(self, _system, _user, *, timeout=30.0):
            raise retained_error

    with pytest.raises(ProviderCallError) as excinfo:
        complete_provider_call(
            PoisonedStatusProvider(),
            "system",
            "masked",
        )

    assert excinfo.value.category == "http"
    assert excinfo.value.error_type == "HTTPError"
    assert excinfo.value.status_code is None
    assert str(private_number) not in str(excinfo.value)
    assert retained_error.__traceback__ is None
    assert retained_error.args == ()
    assert retained_error.__dict__ == {}


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
        vault.write(
            VaultRecord(
                entity_id=str(uuid.uuid4()),
                original=original,
                pseudonym=pseudonym,
                type="TB" if data_type in ("NAME", "ADDRESS") else "FP",
                data_type=data_type,
                span=(0, len(original)),
                timestamp=time.monotonic(),
            )
        )
    return vault


def test_pre_send_allows_ner_span_swallowing_pseudonym():
    """CRF NER can emit a sloppy PERSON span that swallows words around an
    embedded pseudonym (e.g. 'หน่อยครับ\\nผมชื่อ บุญชัย'). That span is not an
    exact pseudonym match, but it is fully explained by pseudonym + ordinary
    words — the guard must not halt on it."""
    vault = _vault_with(
        {
            "NAME": ("สมชาย ใจดี", "บุญชัย"),
            "PHONE": ("081-234-5678", "098-625-9566"),
            "EMAIL": ("somchai.j@example.co.th", "eve.2068@example.com"),
        }
    )
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
    vault = _vault_with(
        {
            "ADDRESS": ("99/1 เขตบางรัก", "412 เขตพระโขนง"),
            "NAME": ("สมชาย ใจดี", "บุญชัย"),
        }
    )
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
    vault = _vault_with(
        {
            "NAME": ("วิชัย มั่งมี", "ชัยวัฒน์"),
            "THAI_ID": ("3-1009-02845-17-2", "8079110812780"),
            "ADDRESS": ("เลขที่บัญชี", "556 เขตสาทร"),
            "BANK_ACCOUNT": ("123-4-56789-0", "3548205739"),
            "PHONE": ("086-111-2233", "062-837-6229"),
        }
    )
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
    vault = _vault_with(
        {
            "NAME": ("วิชัย มั่งมี", "พิทักษ์"),
            "THAI_ID": ("3-1009-02845-17-2", "4504557656411"),
            "ADDRESS": ("เลขที่บัญชี", "927 อำเภอบางพลี"),
            "BANK_ACCOUNT": ("123-4-56789-0", "1444908633"),
            "PHONE": ("086-111-2233", "060-428-3914"),
        }
    )
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
    vault = _vault_with(
        {
            "NAME": ("สมชาย ใจดี", "บุญชัย"),
            "PHONE": ("081-234-5678", "098-625-9566"),
        }
    )
    registry = EntityRegistry(entities=[], fp_count=0, tb_count=0)
    leaky = "ผมชื่อ บุญชัย เบอร์ 098-625-9566 ส่วนหัวหน้าผมชื่อ วิชัย ทองแท้ ครับ"
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
    with pytest.raises(ProviderCallError) as excinfo:
        send_to_ai("text", registry, vault, AuthFailProvider())
    assert excinfo.value.category == "http_status"
    assert excinfo.value.status_code == 401
    assert calls["n"] == 1  # no retry on non-transient HTTP error
    assert len(vault._table) == original_table_size  # vault rolled back


@pytest.mark.parametrize(
    ("provider_error", "expected_calls"),
    [
        (_credentialed_http_status_error(401), 1),
        (_credentialed_http_status_error(500), 2),
        (_credentialed_http_status_error_without_response(), 1),
        (
            _CredentialBearingProviderError(
                httpx.Request(
                    "POST",
                    "https://provider.invalid/v1/complete",
                    headers={"Authorization": SYNTHETIC_AUTHORIZATION},
                    content=SYNTHETIC_PROVIDER_BODY.encode(),
                )
            ),
            1,
        ),
    ],
)
def test_send_to_ai_translates_provider_failures_without_retaining_raw_graph(
    monkeypatch,
    provider_error,
    expected_calls,
):
    import pii_redactor.ai_client as client_module

    monkeypatch.setattr(client_module, "_sleep", lambda _seconds: None)
    calls = 0

    class SecretProvider(AIProvider):
        def __init__(self):
            self._api_key = SYNTHETIC_AUTHORIZATION

        def complete(self, system, user, *, timeout=30.0):
            nonlocal calls
            calls += 1
            raise provider_error

    vault, _ = _make_vault_with_record(
        original=SYNTHETIC_VAULT_ORIGINAL,
        pseudonym="masked@example.invalid",
    )
    provider = SecretProvider()
    with pytest.raises(Exception) as excinfo:
        send_to_ai(
            "safe text",
            EntityRegistry(entities=[], fp_count=0, tb_count=0),
            vault,
            provider,
            max_retries=2,
        )

    nodes, graph_text = _exception_graph(excinfo.value)
    assert type(excinfo.value).__name__ == "ProviderCallError"
    assert excinfo.value.__cause__ is None
    assert excinfo.value.__context__ is None
    assert not any(
        isinstance(node, (httpx.HTTPError, _CredentialBearingProviderError)) for node in nodes
    )
    assert SYNTHETIC_AUTHORIZATION not in graph_text
    assert SYNTHETIC_PROVIDER_BODY not in graph_text
    assert calls == expected_calls
    frame_locals = _product_traceback_locals(excinfo.value)
    assert frame_locals
    assert all(provider is not value for frame in frame_locals for value in frame.values())
    assert all(vault is not value for frame in frame_locals for value in frame.values())
    assert SYNTHETIC_AUTHORIZATION not in repr(frame_locals)
    assert SYNTHETIC_VAULT_ORIGINAL not in repr(frame_locals)
    assert provider_error.__traceback__ is None
    assert provider_error.__cause__ is None
    assert provider_error.__context__ is None


def test_send_to_ai_contains_post_provider_failure_and_rolls_back(monkeypatch):
    import pii_redactor.ai_client as client_module

    vault, _ = _make_vault_with_record(
        original=SYNTHETIC_VAULT_ORIGINAL,
        pseudonym="masked@example.invalid",
    )
    registry = EntityRegistry(entities=[], fp_count=0, tb_count=0)
    original_table = dict(vault._table)
    calls = 0
    validation_error = RuntimeError("response validation failed")
    validation_cause = _CredentialBearingProviderError(
        httpx.Request(
            "POST",
            "https://provider.invalid/v1/complete",
            headers={"Authorization": SYNTHETIC_AUTHORIZATION},
            content=SYNTHETIC_PROVIDER_BODY.encode(),
        )
    )

    class SecretProvider(AIProvider):
        def __init__(self):
            self._api_key = SYNTHETIC_AUTHORIZATION

        def complete(self, system, user, *, timeout=30.0):
            nonlocal calls
            calls += 1
            vault.write(
                VaultRecord(
                    entity_id="provider-mutation",
                    original="synthetic-provider-mutation@example.invalid",
                    pseudonym="mutated@example.invalid",
                    type="FP",
                    data_type="EMAIL",
                    span=(0, 43),
                    timestamp=time.monotonic(),
                )
            )
            return SYNTHETIC_PROVIDER_BODY

    def fail_validation(response, received_registry, received_vault):
        assert response == SYNTHETIC_PROVIDER_BODY
        assert received_registry is registry
        assert received_vault is vault
        try:
            raise validation_cause
        except _CredentialBearingProviderError:
            raise validation_error

    monkeypatch.setattr(client_module, "_validate_response", fail_validation)
    provider = SecretProvider()

    with pytest.raises(ProviderCallError) as excinfo:
        send_to_ai(
            SYNTHETIC_OUTBOUND_TEXT,
            registry,
            vault,
            provider,
            system_prompt=SYNTHETIC_SYSTEM_PROMPT,
            max_retries=3,
        )

    assert excinfo.value.category == "failed"
    assert excinfo.value.error_type == "ProviderError"
    assert excinfo.value.attempts == 1
    assert excinfo.value.__cause__ is None
    assert excinfo.value.__context__ is None
    assert calls == 1
    assert vault._table == original_table
    assert "provider-mutation" not in vault._table

    nodes, graph_text = _exception_graph(excinfo.value)
    assert nodes == [excinfo.value]
    assert SYNTHETIC_AUTHORIZATION not in graph_text
    assert SYNTHETIC_OUTBOUND_TEXT not in graph_text
    assert SYNTHETIC_PROVIDER_BODY not in graph_text
    assert SYNTHETIC_SYSTEM_PROMPT not in graph_text
    assert SYNTHETIC_VAULT_ORIGINAL not in graph_text

    frame_locals = _product_traceback_locals(excinfo.value)
    assert frame_locals
    assert all(provider is not value for frame in frame_locals for value in frame.values())
    assert all(vault is not value for frame in frame_locals for value in frame.values())
    assert all(registry is not value for frame in frame_locals for value in frame.values())
    retained_locals = repr(frame_locals)
    assert SYNTHETIC_AUTHORIZATION not in retained_locals
    assert SYNTHETIC_OUTBOUND_TEXT not in retained_locals
    assert SYNTHETIC_PROVIDER_BODY not in retained_locals
    assert SYNTHETIC_SYSTEM_PROMPT not in retained_locals
    assert SYNTHETIC_VAULT_ORIGINAL not in retained_locals
    assert validation_error.__traceback__ is None
    assert validation_error.__cause__ is None
    assert validation_error.__context__ is None
    assert validation_cause.__traceback__ is None
    assert validation_cause.__cause__ is None
    assert validation_cause.__context__ is None


def test_send_to_ai_contains_snapshot_exception_group_before_provider_call():
    snapshot_group, snapshot_child = _credential_exception_group("snapshot failed")
    provider_calls = 0

    class SnapshotFailVault(SessionVault):
        def snapshot(self):
            raise snapshot_group

    class SecretProvider(AIProvider):
        def __init__(self):
            self._api_key = SYNTHETIC_AUTHORIZATION

        def complete(self, system, user, *, timeout=30.0):
            nonlocal provider_calls
            provider_calls += 1
            return user

    vault = SnapshotFailVault()
    _write_synthetic_record(vault)
    registry = EntityRegistry(entities=[], fp_count=0, tb_count=0)
    provider = SecretProvider()

    with pytest.raises(ProviderCallError) as excinfo:
        send_to_ai(
            SYNTHETIC_OUTBOUND_TEXT,
            registry,
            vault,
            provider,
            system_prompt=SYNTHETIC_SYSTEM_PROMPT,
        )

    assert excinfo.value.category == "failed"
    assert excinfo.value.error_type == "ProviderError"
    assert excinfo.value.attempts == 0
    assert provider_calls == 0
    _assert_public_failure_scrubbed(
        excinfo.value,
        forbidden_objects=(provider, vault, registry, snapshot_group, snapshot_child),
        forbidden_text=(
            SYNTHETIC_AUTHORIZATION,
            SYNTHETIC_OUTBOUND_TEXT,
            SYNTHETIC_PROVIDER_BODY,
            SYNTHETIC_SYSTEM_PROMPT,
            SYNTHETIC_VAULT_ORIGINAL,
        ),
    )
    _assert_exception_graph_discarded(snapshot_group)


def test_send_to_ai_contains_retry_capability_descriptor_failure():
    descriptor_error = _CredentialBearingProviderError(
        httpx.Request(
            "POST",
            "https://provider.invalid/v1/complete",
            headers={"Authorization": SYNTHETIC_AUTHORIZATION},
            content=SYNTHETIC_PROVIDER_BODY.encode(),
        )
    )
    provider_calls = 0

    class DescriptorFailProvider(AIProvider):
        def __init__(self):
            self._api_key = SYNTHETIC_AUTHORIZATION

        @property
        def handles_retries(self):
            raise descriptor_error

        def complete(self, system, user, *, timeout=30.0):
            nonlocal provider_calls
            provider_calls += 1
            return user

    vault, _ = _make_vault_with_record(original=SYNTHETIC_VAULT_ORIGINAL)
    registry = EntityRegistry(entities=[], fp_count=0, tb_count=0)
    provider = DescriptorFailProvider()

    with pytest.raises(ProviderCallError) as excinfo:
        send_to_ai(
            SYNTHETIC_OUTBOUND_TEXT,
            registry,
            vault,
            provider,
            system_prompt=SYNTHETIC_SYSTEM_PROMPT,
        )

    assert excinfo.value.category == "failed"
    assert excinfo.value.error_type == "ProviderError"
    assert excinfo.value.attempts == 0
    assert provider_calls == 0
    _assert_public_failure_scrubbed(
        excinfo.value,
        forbidden_objects=(provider, vault, registry, descriptor_error),
        forbidden_text=(
            SYNTHETIC_AUTHORIZATION,
            SYNTHETIC_OUTBOUND_TEXT,
            SYNTHETIC_PROVIDER_BODY,
            SYNTHETIC_SYSTEM_PROMPT,
            SYNTHETIC_VAULT_ORIGINAL,
        ),
    )
    _assert_exception_graph_discarded(descriptor_error)


def test_retry_validation_failure_survives_rollback_exception_group(monkeypatch):
    import pii_redactor.ai_client as client_module

    rollback_group, rollback_child = _credential_exception_group("rollback failed")
    validation_error = PreSendValidationError(
        f"unsafe validation detail: {SYNTHETIC_OUTBOUND_TEXT}",
        code="outbound_residual",
    )
    validation_calls = 0
    provider_calls = 0
    restore_calls = 0
    provider_errors = []

    class RollbackFailVault(SessionVault):
        def restore(self, snapshot):
            nonlocal restore_calls
            restore_calls += 1
            raise rollback_group

    class RetryingProvider(AIProvider):
        def __init__(self):
            self._api_key = SYNTHETIC_AUTHORIZATION

        def complete(self, system, user, *, timeout=30.0):
            nonlocal provider_calls
            provider_calls += 1
            error = _credentialed_http_status_error(500)
            provider_errors.append(error)
            raise error

    def fail_second_validation(text, received_vault):
        nonlocal validation_calls
        validation_calls += 1
        assert text == SYNTHETIC_OUTBOUND_TEXT
        assert received_vault is vault
        if validation_calls == 2:
            raise validation_error

    monkeypatch.setattr(client_module, "_validate_pre_send", fail_second_validation)
    monkeypatch.setattr(client_module, "_sleep", lambda _seconds: None)
    vault = RollbackFailVault()
    _write_synthetic_record(vault)
    registry = EntityRegistry(entities=[], fp_count=0, tb_count=0)
    provider = RetryingProvider()

    with pytest.raises(PreSendValidationError) as excinfo:
        send_to_ai(
            SYNTHETIC_OUTBOUND_TEXT,
            registry,
            vault,
            provider,
            system_prompt=SYNTHETIC_SYSTEM_PROMPT,
            max_retries=3,
        )

    assert excinfo.value.code == "outbound_residual"
    assert provider_calls == 1
    assert validation_calls == 2
    assert restore_calls == 1
    _assert_public_failure_scrubbed(
        excinfo.value,
        forbidden_objects=(
            provider,
            vault,
            registry,
            validation_error,
            rollback_group,
            rollback_child,
            *provider_errors,
        ),
        forbidden_text=(
            SYNTHETIC_AUTHORIZATION,
            SYNTHETIC_OUTBOUND_TEXT,
            SYNTHETIC_PROVIDER_BODY,
            SYNTHETIC_SYSTEM_PROMPT,
            SYNTHETIC_VAULT_ORIGINAL,
        ),
    )
    _assert_exception_graph_discarded(validation_error)
    _assert_exception_graph_discarded(rollback_group)
    for error in provider_errors:
        _assert_exception_graph_discarded(error)


def test_exhausted_retries_survive_rollback_exception_group(monkeypatch):
    import pii_redactor.ai_client as client_module

    rollback_group, rollback_child = _credential_exception_group("rollback failed")
    provider_calls = 0
    restore_calls = 0
    provider_errors = []

    class RollbackFailVault(SessionVault):
        def restore(self, snapshot):
            nonlocal restore_calls
            restore_calls += 1
            raise rollback_group

    class FailingProvider(AIProvider):
        def __init__(self):
            self._api_key = SYNTHETIC_AUTHORIZATION

        def complete(self, system, user, *, timeout=30.0):
            nonlocal provider_calls
            provider_calls += 1
            error = _credentialed_http_status_error(500)
            provider_errors.append(error)
            raise error

    monkeypatch.setattr(client_module, "_sleep", lambda _seconds: None)
    vault = RollbackFailVault()
    _write_synthetic_record(vault)
    registry = EntityRegistry(entities=[], fp_count=0, tb_count=0)
    provider = FailingProvider()

    with pytest.raises(ProviderCallError) as excinfo:
        send_to_ai(
            SYNTHETIC_OUTBOUND_TEXT,
            registry,
            vault,
            provider,
            system_prompt=SYNTHETIC_SYSTEM_PROMPT,
            max_retries=2,
        )

    assert excinfo.value.category == "http_status"
    assert excinfo.value.error_type == "HTTPStatusError"
    assert excinfo.value.status_code == 500
    assert excinfo.value.attempts == 2
    assert provider_calls == 2
    assert restore_calls == 1
    _assert_public_failure_scrubbed(
        excinfo.value,
        forbidden_objects=(
            provider,
            vault,
            registry,
            rollback_group,
            rollback_child,
            *provider_errors,
        ),
        forbidden_text=(
            SYNTHETIC_AUTHORIZATION,
            SYNTHETIC_OUTBOUND_TEXT,
            SYNTHETIC_PROVIDER_BODY,
            SYNTHETIC_SYSTEM_PROMPT,
            SYNTHETIC_VAULT_ORIGINAL,
        ),
    )
    _assert_exception_graph_discarded(rollback_group)
    for error in provider_errors:
        _assert_exception_graph_discarded(error)


def test_send_to_ai_5xx_is_retried_and_rescanned_before_each_outer_attempt(monkeypatch):
    """Plain-provider retries get a fresh outer guard check."""
    import pii_redactor.ai_client as client_module

    vault = SessionVault()
    registry = EntityRegistry(entities=[], fp_count=0, tb_count=0)
    calls = {"n": 0}
    guard_calls = {"n": 0}
    real_enforce = client_module.enforce_outbound_policy

    def counting_enforce(*args, **kwargs):
        guard_calls["n"] += 1
        return real_enforce(*args, **kwargs)

    monkeypatch.setattr(client_module, "enforce_outbound_policy", counting_enforce)

    class FlakyProvider(AIProvider):
        def complete(self, system, user, *, timeout=30.0):
            calls["n"] += 1
            if calls["n"] == 1:
                raise _http_status_error(500)
            return user

    result = send_to_ai("text", registry, vault, FlakyProvider())
    assert calls["n"] == 2
    assert guard_calls["n"] == calls["n"]
    assert result.text == "text"


def test_send_to_ai_discards_retained_provider_call_error(monkeypatch):
    import pii_redactor.ai_client as client_module

    retained_error = ProviderCallError(
        category="timeout",
        error_type="TimeoutException",
        attempts=1,
    )

    def fail_provider(*_args, **_kwargs):
        raise retained_error

    monkeypatch.setattr(client_module, "complete_provider_call", fail_provider)
    with pytest.raises(ProviderCallError) as excinfo:
        send_to_ai(
            "text",
            EntityRegistry(entities=[], fp_count=0, tb_count=0),
            SessionVault(),
            FakeLLMProvider(),
            max_retries=1,
        )

    assert excinfo.value is not retained_error
    assert excinfo.value.category == "timeout"
    assert excinfo.value.error_type == "TimeoutException"
    assert excinfo.value.attempts == 1
    assert retained_error.__traceback__ is None
    assert retained_error.__cause__ is None
    assert retained_error.__context__ is None
    assert retained_error.args == ()
    assert retained_error.__dict__ == {}


def test_send_to_ai_clamps_poisoned_provider_failure_metadata():
    private_number = 1101700230708
    retained_error = ProviderCallError(
        category="http_status",
        error_type="HTTPStatusError",
        status_code=private_number,
        attempts=private_number,
    )

    class PoisonedCapabilityProvider(AIProvider):
        @property
        def handles_retries(self):
            raise retained_error

        def complete(self, _system, _user, *, timeout=30.0):
            raise AssertionError("provider must not be called")

    with pytest.raises(ProviderCallError) as excinfo:
        send_to_ai(
            "text",
            EntityRegistry(entities=[], fp_count=0, tb_count=0),
            SessionVault(),
            PoisonedCapabilityProvider(),
        )

    assert excinfo.value is not retained_error
    assert excinfo.value.category == "http_status"
    assert excinfo.value.error_type == "HTTPStatusError"
    assert excinfo.value.status_code is None
    assert excinfo.value.attempts == 0
    assert str(private_number) not in str(excinfo.value)
    assert retained_error.__traceback__ is None
    assert retained_error.args == ()
    assert retained_error.__dict__ == {}


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


@pytest.mark.parametrize(
    "residual",
    [
        "เลขบัตรประชาชน 1101700230708",
        "ผมชื่อ นายสมชาย ใจดี",
        "เอกสารหมายเลข 6801234",
    ],
)
def test_pre_send_blocks_every_residual_class_before_provider(residual):
    calls = []
    vault = SessionVault()
    before_audit = vault.audit_log()

    class SpyProvider(AIProvider):
        def complete(self, system, user, *, timeout=30.0):
            calls.append((system, user))
            return user

    with pytest.raises(PreSendValidationError) as excinfo:
        send_to_ai(
            residual,
            EntityRegistry(entities=[], fp_count=0, tb_count=0),
            vault,
            SpyProvider(),
        )

    assert calls == []
    assert vault.audit_log() == before_audit
    assert residual not in str(excinfo.value)


def test_pre_send_residual_error_graph_drops_input_vault_and_provider():
    residual = "เลขบัตรประชาชน 1101700230708"
    vault, _ = _make_vault_with_record(
        original=SYNTHETIC_VAULT_ORIGINAL,
        pseudonym="masked@example.invalid",
    )

    class SecretProvider(AIProvider):
        def __init__(self):
            self._api_key = SYNTHETIC_AUTHORIZATION

        def complete(self, system, user, *, timeout=30.0):
            raise AssertionError("provider must not be called")

    provider = SecretProvider()
    with pytest.raises(PreSendValidationError) as excinfo:
        send_to_ai(
            residual,
            EntityRegistry(entities=[], fp_count=0, tb_count=0),
            vault,
            provider,
        )

    nodes, graph_text = _exception_graph(excinfo.value)
    assert excinfo.value.code == "outbound_residual"
    assert excinfo.value.__cause__ is None
    assert excinfo.value.__context__ is None
    assert len(nodes) == 1
    assert residual not in graph_text
    assert SYNTHETIC_AUTHORIZATION not in graph_text
    assert SYNTHETIC_VAULT_ORIGINAL not in graph_text
    frame_locals = _product_traceback_locals(excinfo.value)
    assert frame_locals
    assert all(provider is not value for frame in frame_locals for value in frame.values())
    assert all(vault is not value for frame in frame_locals for value in frame.values())
    assert residual not in repr(frame_locals)
    assert SYNTHETIC_AUTHORIZATION not in repr(frame_locals)
    assert SYNTHETIC_VAULT_ORIGINAL not in repr(frame_locals)


class TestPathummaProvider:
    """Wire shape proven live 2026-07-21: form-encoded only, JSON gets a 422.

    Evidence: dev/aift-onboarding/probe_results.json (outside this repo).
    """

    def test_requires_api_key(self, monkeypatch):
        from pii_redactor.ai_client import PathummaProvider

        monkeypatch.delenv("AIFORTHAI_API_KEY", raising=False)
        with pytest.raises(ValueError):
            PathummaProvider()

    def test_complete_posts_form_data_not_json(self, monkeypatch):
        import httpx

        from pii_redactor import ai_client
        from pii_redactor.ai_client import PathummaProvider

        monkeypatch.setenv("AIFORTHAI_API_KEY", "test-key")
        captured = {}

        def fake_post(url, **kwargs):
            captured["url"] = url
            captured["kwargs"] = kwargs
            request = httpx.Request("POST", url)
            return httpx.Response(200, json={"content": "คำตอบ [ชื่อ_1]"}, request=request)

        monkeypatch.setattr(ai_client.httpx, "post", fake_post)
        out = PathummaProvider().complete("system prompt", "ผู้ใช้ [ชื่อ_1]")
        assert out == "คำตอบ [ชื่อ_1]"
        assert captured["url"] == "https://api.aiforthai.in.th/textqa/completion"
        # live-proven: the endpoint 422s on a JSON body — must send form data
        assert "json" not in captured["kwargs"]
        assert captured["kwargs"]["data"]["instruction"] == "ผู้ใช้ [ชื่อ_1]"
        assert captured["kwargs"]["data"]["system_prompt"] == "system prompt"
        assert captured["kwargs"]["headers"]["Apikey"] == "test-key"

    def test_http_error_propagates(self, monkeypatch):
        import httpx

        from pii_redactor import ai_client
        from pii_redactor.ai_client import PathummaProvider

        monkeypatch.setenv("AIFORTHAI_API_KEY", "test-key")

        def fake_post(url, **kwargs):
            request = httpx.Request("POST", url)
            return httpx.Response(429, json={"detail": "quota"}, request=request)

        monkeypatch.setattr(ai_client.httpx, "post", fake_post)
        with pytest.raises(httpx.HTTPStatusError):
            PathummaProvider().complete("s", "u")
