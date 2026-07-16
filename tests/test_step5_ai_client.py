"""Tests for Step 5 AI client integration."""
import pytest
import time
import uuid
from abc import ABC

import httpx

from pii_redactor.ai_client import (
    FakeLLMProvider,
    send_to_ai,
    PreSendValidationError,
    AIProvider,
)
from pii_redactor.models import EntityRegistry, AIResponse, Entity, VaultRecord
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
