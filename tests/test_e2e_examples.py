"""End-to-end on realistic example prompts + the sample PDF.

Exercises the same API the extension and CLI use: token + surrogate sanitize,
re-identify round-trip, analyze, and real PDF redaction. The example files in
examples/ double as the test corpus and as try-it-yourself material for users.
"""
import base64
import io
from pathlib import Path

import pdfplumber
import pytest

try:
    from fastapi.testclient import TestClient
    from app.server import app
    DEPS = True
except ImportError:
    DEPS = False

pytestmark = pytest.mark.skipif(not DEPS, reason="fastapi not installed")

EXAMPLES = Path(__file__).parent.parent / "examples"
PROMPTS = sorted((EXAMPLES / "prompts").glob("*.txt"))


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from app.server import app
    return TestClient(app, base_url="http://localhost")


@pytest.mark.parametrize("prompt_file", PROMPTS, ids=lambda p: p.stem)
def test_prompt_round_trip_token(client, prompt_file):
    text = prompt_file.read_text(encoding="utf-8")
    s = client.post("/api/sanitize", json={"text": text, "mode": "token"}).json()
    assert len(s["entities"]) >= 1
    assert s["sanitized_text"] != s["original_text"]  # PII was masked
    r = client.post(
        "/api/reidentify", json={"session_id": s["session_id"], "text": s["sanitized_text"]}
    ).json()
    # exact round-trip against the cleaned text the API returns
    assert r["restored_text"] == s["original_text"]
    assert r["leftover_tokens"] == []


@pytest.mark.parametrize("prompt_file", PROMPTS, ids=lambda p: p.stem)
def test_prompt_round_trip_surrogate(client, prompt_file):
    text = prompt_file.read_text(encoding="utf-8")
    s = client.post("/api/sanitize", json={"text": text, "mode": "surrogate"}).json()
    assert s["sanitized_text"] != s["original_text"]
    r = client.post(
        "/api/reidentify", json={"session_id": s["session_id"], "text": s["sanitized_text"]}
    ).json()
    assert r["restored_text"] == s["original_text"]


def test_analyze_flags_health_in_medical_prompt(client):
    medical = next(p for p in PROMPTS if "medical" in p.stem)
    text = medical.read_text(encoding="utf-8")
    data = client.post("/api/analyze", json={"text": text}).json()
    assert "HEALTH" in {s["category"] for s in data["section26"]}


def test_sample_pdf_is_redacted(client):
    pdf = (EXAMPLES / "sample_document.pdf").read_bytes()
    resp = client.post(
        "/api/redact-pdf",
        files={"pdf_file": ("sample_document.pdf", pdf, "application/pdf")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["entity_count"] >= 2

    redacted = base64.b64decode(data["redacted_pdf_b64"])
    with pdfplumber.open(io.BytesIO(redacted)) as doc:
        text = "".join(p.extract_text() or "" for p in doc.pages)
    # the redacted PDF is flattened to an image, so text extraction finds
    # nothing at all -- in particular, none of the structured PII.
    assert text.strip() == ""
    assert "081-234-5678" not in text
    assert "somchai.j@example.co.th" not in text
