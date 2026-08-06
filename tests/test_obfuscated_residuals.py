"""Fail-closed coverage for structured PII split by ignorable characters."""

from __future__ import annotations

import pytest

from pii_redactor.ai_client import AIProvider, PreSendValidationError, send_to_ai
from pii_redactor.leak_guard import OutboundGuardContext, scan_residual_signals
from pii_redactor.models import EntityRegistry
from pii_redactor.session_vault import SessionVault
from pii_redactor.stateless import (
    StatelessLeakError,
    StatelessSanitizeResult,
    restore_stateless,
    sanitize_stateless,
)

SINGLE_SPACED_IBAN = "IBAN GB82 WEST 1234 5698 7654 32"
OBFUSCATED_STRUCTURED_PII = [
    "โทร 081\u200b-234-5678",
    "เลข 1101\ufeff700230708",
    "อีเมล synthetic.user\u200d@example.com",
    "โทร 081  234  5678",
    "เลข 1101  7002  30708",
    SINGLE_SPACED_IBAN,
]


class _SpyProvider(AIProvider):
    def __init__(self, calls: list[str]):
        self._calls = calls

    def complete(self, system: str, user: str, *, timeout: float = 60.0) -> str:
        del system, timeout
        self._calls.append(user)
        return user


class _FixedProvider(AIProvider):
    def __init__(self, response: str, calls: list[str]):
        self._response = response
        self._calls = calls

    def complete(self, system: str, user: str, *, timeout: float = 60.0) -> str:
        del system, timeout
        self._calls.append(user)
        return self._response


@pytest.mark.parametrize("text", OBFUSCATED_STRUCTURED_PII)
def test_stateless_sanitize_masks_or_blocks_obfuscated_structured_pii(text):
    try:
        result = sanitize_stateless(text, mode="token", salt="synthetic-salt")
    except StatelessLeakError:
        return

    assert result.sanitized_text != text
    assert scan_residual_signals(result.sanitized_text, result.guard_context) == []


@pytest.mark.parametrize("text", OBFUSCATED_STRUCTURED_PII)
def test_cli_presend_blocks_obfuscated_structured_pii_before_provider(text):
    calls: list[str] = []

    with pytest.raises(PreSendValidationError) as excinfo:
        send_to_ai(
            text,
            EntityRegistry(entities=[], fp_count=0, tb_count=0),
            SessionVault(),
            _SpyProvider(calls),
        )

    assert excinfo.value.code == "outbound_residual"
    assert calls == []


@pytest.mark.parametrize(
    "text",
    [
        "ข้อความ\u200bทั่วไปที่เว้น  สองช่อง",
        "รหัสกลุ่ม GB00 TEST 1234 5678 9012 34",
    ],
)
def test_unrelated_hidden_characters_and_grouped_text_remain_exact(text):

    result = sanitize_stateless(text, mode="token", salt="synthetic-salt")

    assert result.sanitized_text == text
    assert result.entities == []


def test_session_sanitize_blocks_single_spaced_iban_without_publishing_state():
    from pii_redactor.session_service import OutboundLeakError, SessionService

    service = SessionService()

    with pytest.raises(OutboundLeakError):
        service.sanitize(SINGLE_SPACED_IBAN, mode="token")

    assert service.session_count == 0


def test_stateless_restore_counts_generated_single_spaced_iban():
    result = restore_stateless(
        f"ตอบกลับ {SINGLE_SPACED_IBAN}",
        mapping={},
        mode="token",
    )

    assert result.generated_pii_count == 1


@pytest.mark.parametrize("text", OBFUSCATED_STRUCTURED_PII)
def test_http_sanitize_and_roundtrip_block_before_provider(text, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    import app.server as server
    from pii_redactor.session_service import SessionService

    calls: list[str] = []
    monkeypatch.setattr(server, "SERVICE", SessionService())
    monkeypatch.setitem(
        server._PROVIDER_FACTORIES,
        "obfuscated-residual-spy",
        lambda: _SpyProvider(calls),
    )
    with TestClient(
        server.app,
        base_url="http://localhost",
        headers={"X-AIGuard-Contract-Version": "2"},
    ) as client:
        sanitize_response = client.post(
            "/api/sanitize",
            json={"text": text, "mode": "token"},
        )
        roundtrip_response = client.post(
            "/api/roundtrip",
            json={
                "text": text,
                "mode": "token",
                "provider": "obfuscated-residual-spy",
            },
        )

    if sanitize_response.status_code == 422:
        assert sanitize_response.json()["error"]["code"] == "residual_pii"
        assert text not in sanitize_response.text
    else:
        assert sanitize_response.status_code == 200
        sanitized = sanitize_response.json()["sanitized_text"]
        assert sanitized != text
        assert scan_residual_signals(sanitized, OutboundGuardContext()) == []

    if roundtrip_response.status_code == 422:
        assert roundtrip_response.json()["error"]["code"] == "residual_pii"
        assert text not in roundtrip_response.text
        assert calls == []
    else:
        assert roundtrip_response.status_code == 200
        assert len(calls) == 1
        assert calls[0] != text
        assert scan_residual_signals(calls[0], OutboundGuardContext()) == []


def test_http_reidentify_warns_for_generated_obfuscated_pii(monkeypatch, tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    import app.server as server
    from pii_redactor.session_service import SessionService

    monkeypatch.setattr(server, "_API_KEY", None)
    monkeypatch.setattr(server, "_BOOT_TOKEN", None)
    monkeypatch.setattr(server, "_get_audit_log_dir", lambda: str(tmp_path))
    monkeypatch.setattr(server, "SERVICE", SessionService())
    generated = "099\u202e-999-9999"
    with TestClient(
        server.app,
        base_url="http://localhost",
        headers={"X-AIGuard-Contract-Version": "2"},
    ) as client:
        sanitized_response = client.post(
            "/api/sanitize",
            json={"text": "โทร 081-234-5678", "mode": "token"},
        )
        assert sanitized_response.status_code == 200
        sanitized = sanitized_response.json()

        response = client.post(
            "/api/reidentify",
            json={
                "session_id": sanitized["session_id"],
                "text": f"{sanitized['sanitized_text']} สำรอง {generated}",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["restored_text"].endswith(generated)
    assert body["leftover_count"] == 0
    assert body["warnings"] == [{"code": "generated_pii", "count": 1}]


def test_http_roundtrip_marks_forged_obfuscated_provider_output_unsafe(
    monkeypatch,
    tmp_path,
):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    import app.server as server
    from pii_redactor.session_service import SessionService

    calls: list[str] = []
    generated = "ตอบกลับ 099\u2066-999-9999"
    monkeypatch.setattr(server, "_API_KEY", None)
    monkeypatch.setattr(server, "_BOOT_TOKEN", None)
    monkeypatch.setattr(server, "_get_audit_log_dir", lambda: str(tmp_path))
    monkeypatch.setattr(server, "SERVICE", SessionService())
    monkeypatch.setitem(
        server._PROVIDER_FACTORIES,
        "obfuscated-generated-spy",
        lambda: _FixedProvider(generated, calls),
    )
    with TestClient(
        server.app,
        base_url="http://localhost",
        headers={"X-AIGuard-Contract-Version": "2"},
    ) as client:
        response = client.post(
            "/api/roundtrip",
            json={
                "text": "synthetic safe source",
                "mode": "token",
                "provider": "obfuscated-generated-spy",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert calls == ["synthetic safe source"]
    assert body["ai_response_masked"] == generated
    assert body["restored_text"] == generated
    assert body["warnings"] == [{"code": "generated_pii", "count": 1}]
    assert body["restoration"]["status"] == "unsafe"


@pytest.mark.parametrize(
    "text",
    [
        "ยอดขาย 12  345  678 บาท.",
        "ordinary\u202e text remains exact.",
    ],
)
def test_http_reidentify_preserves_safe_security_view_negatives(
    text,
    monkeypatch,
    tmp_path,
):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    import app.server as server
    from pii_redactor.session_service import SessionService

    monkeypatch.setattr(server, "_API_KEY", None)
    monkeypatch.setattr(server, "_BOOT_TOKEN", None)
    monkeypatch.setattr(server, "_get_audit_log_dir", lambda: str(tmp_path))
    monkeypatch.setattr(server, "SERVICE", SessionService())
    with TestClient(
        server.app,
        base_url="http://localhost",
        headers={"X-AIGuard-Contract-Version": "2"},
    ) as client:
        sanitized_response = client.post(
            "/api/sanitize",
            json={"text": "synthetic safe source", "mode": "token"},
        )
        assert sanitized_response.status_code == 200
        session_id = sanitized_response.json()["session_id"]

        response = client.post(
            "/api/reidentify",
            json={"session_id": session_id, "text": text},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["restored_text"] == text
    assert body["warnings"] == []


@pytest.mark.parametrize("text", OBFUSCATED_STRUCTURED_PII)
def test_worker_post_sanitize_guard_blocks_forged_output_before_handoff(text, monkeypatch):
    import app.worker.handler as handler

    calls: list[str] = []
    forged = StatelessSanitizeResult(
        sanitized_text=text,
        mapping={},
        entities=[],
        entity_type_counts={},
        section26=[],
        warnings=[],
    )
    monkeypatch.setattr(handler, "sanitize_stateless", lambda *_args, **_kwargs: forged)
    monkeypatch.setitem(
        handler._PROVIDER_FACTORIES,
        "obfuscated-residual-spy",
        lambda: _SpyProvider(calls),
    )

    result = handler.handle_job(
        {
            "job_id": "synthetic-obfuscated-residual",
            "operation": "roundtrip",
            "payload": {
                "text": "synthetic safe source",
                "mode": "token",
                "provider": "obfuscated-residual-spy",
            },
        }
    )

    assert result["status"] == "error"
    assert result["error"] == {
        "type": "residual_pii",
        "message": "outbound residual detected",
    }
    assert text not in str(result)
    assert calls == []
