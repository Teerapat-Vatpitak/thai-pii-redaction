"""Tests for the FastAPI web server (Step 11: Web API).

Covers the v2 token-mode contract:
- /api/sanitize  -> session_id, original_text, sanitized_text, entities[], section26
- /api/reidentify -> restore tokens via stored session map
- /api/analyze   -> full PDPA report (score, grade, reid, breakdown, recs)
"""
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


def test_root_redirects_to_docs(client):
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code in (307, 308)
    assert resp.headers["location"] == "/docs"


def test_cors_preflight_allows_extension(client):
    """The extension calls the API cross-origin; preflight must be allowed."""
    resp = client.options(
        "/api/sanitize",
        headers={
            "Origin": "https://chatgpt.com",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert resp.status_code == 200
    assert "access-control-allow-origin" in {k.lower() for k in resp.headers}


def test_health_version(client):
    resp = client.get("/api/health")
    assert resp.json()["version"] == "2.0.0"


def test_sanitize_returns_session_and_entities(client):
    resp = client.post("/api/sanitize", json={"text": "โทร 081-234-5678 นะ"})
    assert resp.status_code == 200
    data = resp.json()
    assert "session_id" in data
    assert "sanitized_text" in data
    assert isinstance(data["entities"], list)
    assert isinstance(data["entity_type_counts"], dict)


def test_sanitize_empty_text_rejected(client):
    resp = client.post("/api/sanitize", json={"text": "   "})
    assert resp.status_code == 400


def test_sanitize_with_email_is_tokenized(client):
    resp = client.post("/api/sanitize", json={"text": "Contact me at user@example.com"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["entities"]) >= 1
    assert "user@example.com" not in data["sanitized_text"]


def test_sanitize_section26_flagged(client):
    resp = client.post("/api/sanitize", json={"text": "ผู้ป่วยนับถือศาสนาพุทธ มีโรคประจำตัว"})
    assert resp.status_code == 200
    cats = {s["category"] for s in resp.json()["section26"]}
    assert "RELIGION" in cats


def test_reidentify_round_trip(client):
    """Sanitize then restore the same tokens via the session map."""
    s = client.post("/api/sanitize", json={"text": "โทร 081-234-5678 ได้เลย"}).json()
    r = client.post("/api/reidentify", json={
        "session_id": s["session_id"],
        "text": s["sanitized_text"],
    })
    assert r.status_code == 200
    data = r.json()
    assert "081-234-5678" in data["restored_text"]
    assert data["replaced_count"] >= 1
    assert data["leftover_tokens"] == []


def test_reidentify_unknown_session(client):
    resp = client.post("/api/reidentify", json={"session_id": "nope", "text": "hi"})
    assert resp.status_code == 404


def test_analyze_returns_report_shape(client):
    resp = client.post("/api/analyze", json={"text": "โทร 081-234-5678 นะ"})
    assert resp.status_code == 200
    data = resp.json()
    for key in ("overall_score", "overall_grade", "risk_label",
                "direct_pii_count", "fp_count", "tb_count",
                "section26", "reid", "breakdown", "recommendations"):
        assert key in data
    assert data["direct_pii_count"] >= 1


def test_analyze_no_pii_is_grade_a(client):
    resp = client.post("/api/analyze", json={"text": "The weather is nice today."})
    assert resp.status_code == 200
    data = resp.json()
    assert data["overall_grade"] == "A"
    assert data["risk_label"] == "Very Low Risk"


def test_analyze_breakdown_is_list(client):
    resp = client.post("/api/analyze", json={"text": "email me at a@b.com"})
    assert resp.status_code == 200
    assert isinstance(resp.json()["breakdown"], list)


def test_analyze_reid_shape(client):
    resp = client.post("/api/analyze", json={"text": "นายสมชาย อายุ 32 ปี แขวงคลองเตย"})
    assert resp.status_code == 200
    reid = resp.json()["reid"]
    for key in ("score", "grade", "qi_found", "high_risk_combo"):
        assert key in reid


def test_analyze_high_risk(client):
    text = (
        "ชื่อ: นายสมชาย ใจดี อีเมล: somchai@example.com "
        "โทร: 081-234-5678 เลขบัตร: 1-1019-03451-08-3 "
        "อีกเบอร์: 090-000-1234 อีเมลสอง: b@c.com"
    )
    resp = client.post("/api/analyze", json={"text": text})
    assert resp.status_code == 200
    data = resp.json()
    assert data["direct_pii_count"] > 5
    assert data["overall_score"] >= 60


def test_sanitize_surrogate_mode_round_trip(client):
    """Surrogate mode replaces PII with realistic fakes; restore is exact."""
    text = "ผมชื่อสมชาย ใจดี โทร 081-234-5678 อีเมล somchai@example.com"
    s = client.post("/api/sanitize", json={"text": text, "mode": "surrogate"}).json()
    san = s["sanitized_text"]
    assert len(s["entities"]) >= 2
    assert san != text
    # original PII must be gone from the surrogate text
    assert "081-234-5678" not in san
    assert "somchai@example.com" not in san
    # round-trip restore returns the originals exactly
    r = client.post(
        "/api/reidentify", json={"session_id": s["session_id"], "text": san}
    ).json()
    assert "081-234-5678" in r["restored_text"]
    assert "somchai@example.com" in r["restored_text"]
    assert r["leftover_tokens"] == []


def test_sanitize_token_mode_unchanged(client):
    """Token mode still emits bracket tokens (default behavior)."""
    s = client.post(
        "/api/sanitize", json={"text": "โทร 081-234-5678", "mode": "token"}
    ).json()
    assert "[" in s["sanitized_text"]
    assert "081-234-5678" not in s["sanitized_text"]
