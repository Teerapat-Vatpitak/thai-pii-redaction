"""Tests for the FastAPI web server (Step 11: Web API)."""
import pytest

# Skip entire module if fastapi not installed
try:
    from fastapi.testclient import TestClient
    from app.server import app
    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not FASTAPI_AVAILABLE,
    reason="fastapi not installed",
)


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from app.server import app
    return TestClient(app)


def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_health_version(client):
    resp = client.get("/api/health")
    assert resp.json()["version"] == "1.0.0"


def test_sanitize_returns_session_id(client):
    resp = client.post("/api/sanitize", json={"text": "Hello world.", "provider": "fake"})
    assert resp.status_code == 200
    data = resp.json()
    assert "session_id" in data
    assert "pseudonymized_text" in data
    assert "entity_count" in data


def test_sanitize_entity_count_is_int(client):
    resp = client.post("/api/sanitize", json={"text": "Hello world.", "provider": "fake"})
    assert resp.status_code == 200
    assert isinstance(resp.json()["entity_count"], int)


def test_sanitize_with_email(client):
    resp = client.post("/api/sanitize", json={
        "text": "Contact me at user@example.com",
        "provider": "fake",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["entity_count"] >= 1
    assert "user@example.com" not in data["pseudonymized_text"]


def test_reidentify_returns_restored_text(client):
    resp = client.post("/api/reidentify", json={
        "text": "Call 081-234-5678 please.",
        "provider": "fake",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "restored_text" in data
    assert "081-234-5678" in data["restored_text"]


def test_reidentify_returns_flags(client):
    resp = client.post("/api/reidentify", json={
        "text": "Hello world.",
        "provider": "fake",
    })
    assert resp.status_code == 200
    assert "flags" in resp.json()
    assert isinstance(resp.json()["flags"], list)


def test_analyze_returns_entity_count(client):
    resp = client.post("/api/analyze", json={"text": "Call 081-234-5678 please."})
    assert resp.status_code == 200
    data = resp.json()
    assert "entity_count" in data
    assert "risk_level" in data
    assert data["entity_count"] >= 1


def test_analyze_risk_level_no_pii(client):
    resp = client.post("/api/analyze", json={"text": "The weather is nice today."})
    assert resp.status_code == 200
    assert resp.json()["risk_level"] == "Low"


def test_analyze_returns_fp_and_tb_counts(client):
    resp = client.post("/api/analyze", json={"text": "Call 081-234-5678 please."})
    assert resp.status_code == 200
    data = resp.json()
    assert "fp_count" in data
    assert "tb_count" in data
    assert "entity_types" in data


def test_analyze_entity_types_is_dict(client):
    resp = client.post("/api/analyze", json={"text": "email me at a@b.com"})
    assert resp.status_code == 200
    assert isinstance(resp.json()["entity_types"], dict)


def test_analyze_unknown_provider_in_sanitize(client):
    resp = client.post("/api/sanitize", json={"text": "hello", "provider": "unknown"})
    assert resp.status_code == 400


def test_analyze_high_risk(client):
    text = (
        "ชื่อ: นายสมชาย ใจดี อีเมล: somchai@example.com "
        "โทร: 081-234-5678 เลขบัตร: 1-1019-03451-08-3 "
        "อีกเบอร์: 090-000-1234 อีเมลสอง: b@c.com"
    )
    resp = client.post("/api/analyze", json={"text": text})
    assert resp.status_code == 200
    data = resp.json()
    assert data["entity_count"] > 5
    assert data["risk_level"] == "High"
