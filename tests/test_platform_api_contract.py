"""Executable contract for the five stable platform HTTP endpoints."""

import logging

import pytest

try:
    from fastapi.testclient import TestClient

    import app.server as server

    DEPS = True
except ImportError:
    DEPS = False

pytestmark = pytest.mark.skipif(not DEPS, reason="fastapi not installed")

API_KEY = "platform-key-under-test-0123456789abcdef"
PRIVATE_TEXT = "ข้อมูลลับ 0812345678"


def _client():
    return TestClient(server.app, base_url="http://localhost")


@pytest.fixture
def open_client(monkeypatch, tmp_path):
    """The unset-key grace path is the existing localhost API behavior."""
    monkeypatch.setattr(server, "_API_KEY", None)
    monkeypatch.setattr(server, "_get_audit_log_dir", lambda: str(tmp_path))
    return _client()


def test_health_contract_shape_and_version(open_client):
    response = open_client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert {"status", "version", "contract_version", "capabilities"} <= body.keys()
    assert body["status"] == "ok"
    assert isinstance(body["version"], str)
    assert body["contract_version"] == 1
    assert isinstance(body["contract_version"], int)
    assert isinstance(body["capabilities"], dict)


def test_health_stays_open_when_api_key_is_configured(monkeypatch):
    monkeypatch.setattr(server, "_API_KEY", API_KEY)

    response = _client().get("/api/health")

    assert response.status_code == 200
    assert response.json()["contract_version"] == 1


def test_sanitize_contract_shape_has_no_mapping(open_client):
    response = open_client.post("/api/sanitize", json={"text": "โทร 0812345678"})

    assert response.status_code == 200
    body = response.json()
    assert {
        "session_id",
        "original_text",
        "sanitized_text",
        "entities",
        "entity_type_counts",
        "section26",
        "warnings",
        "guard",
    } <= body.keys()
    assert isinstance(body["session_id"], str)
    assert isinstance(body["sanitized_text"], str)
    assert isinstance(body["entities"], list)
    assert isinstance(body["entity_type_counts"], dict)
    assert "mapping" not in body


def test_reidentify_contract_shape_has_no_mapping(open_client):
    sanitized = open_client.post("/api/sanitize", json={"text": "โทร 0812345678"}).json()
    response = open_client.post(
        "/api/reidentify",
        json={
            "session_id": sanitized["session_id"],
            "text": sanitized["sanitized_text"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert {
        "restored_text",
        "replaced",
        "replaced_count",
        "leftover_tokens",
        "warnings",
    } <= body.keys()
    assert isinstance(body["restored_text"], str)
    assert isinstance(body["replaced"], list)
    assert isinstance(body["replaced_count"], int)
    assert isinstance(body["leftover_tokens"], list)
    assert "mapping" not in body


def test_analyze_contract_shape_has_no_mapping(open_client):
    response = open_client.post("/api/analyze", json={"text": "เอกสารทั่วไป"})

    assert response.status_code == 200
    body = response.json()
    assert {
        "overall_score",
        "overall_grade",
        "risk_label",
        "direct_pii_count",
        "fp_count",
        "tb_count",
        "section26",
        "reid",
        "breakdown",
        "recommendations",
    } <= body.keys()
    assert isinstance(body["reid"], dict)
    assert isinstance(body["breakdown"], list)
    assert isinstance(body["recommendations"], list)
    assert "mapping" not in body


def test_guard_contract_shape_has_no_mapping(open_client):
    response = open_client.post("/api/guard", json={"text": "สรุปเอกสารนี้"})

    assert response.status_code == 200
    body = response.json()
    assert {"guard", "flagged"} <= body.keys()
    assert isinstance(body["guard"], list)
    assert isinstance(body["flagged"], bool)
    assert "mapping" not in body


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/api/sanitize", {"text": PRIVATE_TEXT}),
        ("/api/reidentify", {"session_id": "unknown", "text": PRIVATE_TEXT}),
        ("/api/analyze", {"text": PRIVATE_TEXT}),
        ("/api/guard", {"text": PRIVATE_TEXT}),
    ],
)
@pytest.mark.parametrize("headers", [{}, {"X-AIGuard-Key": "wrong-key"}])
def test_configured_api_key_rejects_missing_or_wrong_header_without_leaks(
    monkeypatch, caplog, path, payload, headers
):
    monkeypatch.setattr(server, "_API_KEY", API_KEY)
    caplog.clear()

    with caplog.at_level(logging.WARNING):
        response = _client().post(path, json=payload, headers=headers)

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid or missing API key"}
    assert PRIVATE_TEXT not in response.text
    assert PRIVATE_TEXT not in caplog.text
    assert API_KEY not in response.text
    assert API_KEY not in caplog.text


def test_api_key_rejection_happens_before_request_body_parsing(monkeypatch):
    monkeypatch.setattr(server, "_API_KEY", API_KEY)

    response = _client().post(
        "/api/sanitize",
        content=f"not-json-{PRIVATE_TEXT}",
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid or missing API key"}
    assert PRIVATE_TEXT not in response.text


def test_correct_api_key_authorizes_all_four_declared_post_endpoints(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "_API_KEY", API_KEY)
    monkeypatch.setattr(server, "_get_audit_log_dir", lambda: str(tmp_path))
    client = _client()
    headers = {"X-AIGuard-Key": API_KEY}

    sanitized_response = client.post(
        "/api/sanitize", json={"text": "โทร 0812345678"}, headers=headers
    )
    assert sanitized_response.status_code == 200
    sanitized = sanitized_response.json()

    reidentify_response = client.post(
        "/api/reidentify",
        json={
            "session_id": sanitized["session_id"],
            "text": sanitized["sanitized_text"],
        },
        headers=headers,
    )
    assert reidentify_response.status_code == 200
    assert (
        client.post("/api/analyze", json={"text": "เอกสารทั่วไป"}, headers=headers).status_code == 200
    )
    assert (
        client.post("/api/guard", json={"text": "สรุปเอกสารนี้"}, headers=headers).status_code == 200
    )


def test_api_key_check_uses_constant_time_comparison(monkeypatch):
    monkeypatch.setattr(server, "_API_KEY", API_KEY)
    original_compare_digest = server.secrets.compare_digest
    calls = []

    def recording_compare_digest(supplied, expected):
        calls.append((supplied, expected))
        return original_compare_digest(supplied, expected)

    monkeypatch.setattr(server.secrets, "compare_digest", recording_compare_digest)

    response = _client().post(
        "/api/guard",
        json={"text": "สรุปเอกสารนี้"},
        headers={"X-AIGuard-Key": API_KEY},
    )

    assert response.status_code == 200
    assert calls == [(API_KEY, API_KEY)]


def test_unset_api_key_emits_pii_free_warning(monkeypatch, caplog):
    monkeypatch.setattr(server, "_API_KEY", None)
    caplog.clear()

    with caplog.at_level(logging.WARNING, logger="app.server"):
        server._warn_if_api_key_unset()

    assert "AIGUARD_API_KEY is not configured" in caplog.text
    assert PRIVATE_TEXT not in caplog.text
    assert API_KEY not in caplog.text


def test_configured_api_key_emits_no_warning(monkeypatch, caplog):
    monkeypatch.setattr(server, "_API_KEY", API_KEY)
    caplog.clear()

    with caplog.at_level(logging.WARNING, logger="app.server"):
        server._warn_if_api_key_unset()

    assert caplog.text == ""
