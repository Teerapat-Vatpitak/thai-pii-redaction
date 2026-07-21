"""Tests for the demo-facing endpoints (feature A: playground).

/api/detect    — detection-only, no session, offsets align with input text
/api/roundtrip — stateless mask -> LLM -> restore in one request
/demo          — gated behind AIGUARD_DEMO=1
"""

import pytest

from pii_redactor.exporter import _register_thai_font

try:
    from fastapi.testclient import TestClient

    from app.server import app

    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False

pytestmark = pytest.mark.skipif(not FASTAPI_AVAILABLE, reason="fastapi not installed")

requires_thai_font = pytest.mark.skipif(
    _register_thai_font() == "Helvetica",
    reason="no Thai-capable font on this machine — Thai text cannot render or extract",
)

THAI_TEXT = "ผมชื่อ นายสมชาย ใจดี เลขบัตรประชาชน 1101700230708 โทร 081-234-5678"


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.server import app

    return TestClient(app, base_url="http://localhost")


class TestDetect:
    def test_detect_returns_entities_with_aligned_spans(self, client):
        resp = client.post("/api/detect", json={"text": THAI_TEXT})
        assert resp.status_code == 200
        body = resp.json()
        assert body["entities"], "expected at least one entity"
        for ent in body["entities"]:
            assert set(ent) == {"start", "end", "data_type", "redact_type"}
            assert 0 <= ent["start"] < ent["end"] <= len(THAI_TEXT)
        types = {e["data_type"] for e in body["entities"]}
        assert "THAI_ID" in types
        assert body["entity_type_counts"]["THAI_ID"] >= 1

    def test_detect_spans_survive_thai_digits(self, client):
        # clean_length_preserving swaps Thai digits in place — offsets must not move
        text = "โทร ๐๘๑-๒๓๔-๕๖๗๘ ครับ"
        resp = client.post("/api/detect", json={"text": text})
        assert resp.status_code == 200
        for ent in resp.json()["entities"]:
            assert ent["end"] <= len(text)

    def test_detect_empty_text_400(self, client):
        assert client.post("/api/detect", json={"text": "  "}).status_code == 400

    def test_detect_creates_no_session(self, client):
        import app.server as server

        before = len(server.SERVICE._sessions)
        client.post("/api/detect", json={"text": THAI_TEXT})
        assert len(server.SERVICE._sessions) == before


class TestRoundtrip:
    def test_roundtrip_fake_provider_restores_original(self, client):
        resp = client.post(
            "/api/roundtrip",
            json={"text": THAI_TEXT, "mode": "token", "provider": "fake"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["provider_used"] == "fake"
        # fake = identity LLM: masked text comes back, restore puts PII back
        assert "1101700230708" not in body["sanitized_text"]
        assert "1101700230708" not in body["ai_response_masked"]
        assert "สมชาย" in body["restored_text"]
        assert body["entities"], "expected entities"

    def test_roundtrip_default_provider_is_fake(self, client):
        resp = client.post("/api/roundtrip", json={"text": THAI_TEXT})
        assert resp.status_code == 200
        assert resp.json()["provider_used"] == "fake"

    def test_roundtrip_unknown_provider_400(self, client):
        resp = client.post("/api/roundtrip", json={"text": THAI_TEXT, "provider": "gpt9"})
        assert resp.status_code == 400

    def test_roundtrip_pathumma_without_key_503(self, client, monkeypatch):
        monkeypatch.delenv("AIFORTHAI_API_KEY", raising=False)
        resp = client.post("/api/roundtrip", json={"text": THAI_TEXT, "provider": "pathumma"})
        assert resp.status_code == 503

    def test_roundtrip_empty_text_400(self, client):
        assert client.post("/api/roundtrip", json={"text": ""}).status_code == 400

    def test_roundtrip_no_mapping_left_serverside(self, client):
        import app.server as server

        before = len(server.SERVICE._sessions)
        client.post("/api/roundtrip", json={"text": THAI_TEXT})
        assert len(server.SERVICE._sessions) == before

    def test_roundtrip_invalid_mode_400(self, client):
        resp = client.post("/api/roundtrip", json={"text": THAI_TEXT, "mode": "redact"})
        assert resp.status_code == 400

    def test_roundtrip_provider_failure_502(self, client, monkeypatch):
        import app.server as server

        class BoomProvider:
            def complete(self, system, user, *, timeout=60.0):
                raise KeyError("content")

        monkeypatch.setitem(server._PROVIDER_FACTORIES, "boom", BoomProvider)
        resp = client.post("/api/roundtrip", json={"text": THAI_TEXT, "provider": "boom"})
        assert resp.status_code == 502
        assert "KeyError" in resp.json()["detail"]

    def test_roundtrip_surrogate_mode(self, client):
        resp = client.post(
            "/api/roundtrip",
            json={"text": THAI_TEXT, "mode": "surrogate", "provider": "fake"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "1101700230708" not in body["sanitized_text"]
        assert "[ชื่อ" not in body["sanitized_text"]  # surrogate mode: realistic values, no tokens
        assert "สมชาย" in body["restored_text"]

    def test_roundtrip_leak_blocked_422(self, client, monkeypatch):
        import app.server as server
        from pii_redactor.stateless import StatelessLeakError

        def boom_sanitize(*args, **kwargs):
            raise StatelessLeakError(["THAI_ID"])

        monkeypatch.setattr(server, "sanitize_stateless", boom_sanitize)
        resp = client.post("/api/roundtrip", json={"text": THAI_TEXT})
        assert resp.status_code == 422
        body = resp.json()["detail"]
        assert body["error"] == "pii_leak_risk"
        assert body["types"] == ["THAI_ID"]
        assert "สมชาย" not in resp.text


class TestDemoGate:
    def test_demo_404_by_default(self, client, monkeypatch):
        monkeypatch.delenv("AIGUARD_DEMO", raising=False)
        assert client.get("/demo").status_code == 404

    def test_demo_served_when_enabled(self, client, monkeypatch):
        monkeypatch.setenv("AIGUARD_DEMO", "1")
        resp = client.get("/demo")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "AI Guard" in resp.text


class TestAnalyzeReport:
    def test_returns_valid_pdf_b64(self, client):
        resp = client.post("/api/analyze-report", json={"text": THAI_TEXT})
        assert resp.status_code == 200
        body = resp.json()
        import base64

        pdf = base64.b64decode(body["report_pdf_b64"])
        assert pdf[:5] == b"%PDF-"
        assert isinstance(body["overall_score"], (int, float))
        assert body["overall_grade"]

    @requires_thai_font
    def test_report_pdf_is_pii_free_end_to_end(self, client):
        import base64
        import io

        import pdfplumber

        resp = client.post("/api/analyze-report", json={"text": THAI_TEXT})
        pdf = base64.b64decode(resp.json()["report_pdf_b64"])
        with pdfplumber.open(io.BytesIO(pdf)) as doc:
            text = "\n".join(page.extract_text() or "" for page in doc.pages)
        assert "สมชาย" not in text
        assert "1101700230708" not in text
        assert "081-234-5678" not in text and "0812345678" not in text

    def test_empty_text_400(self, client):
        assert client.post("/api/analyze-report", json={"text": " "}).status_code == 400
