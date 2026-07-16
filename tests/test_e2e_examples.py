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


def test_multi_turn_mask_restore_round_trip(client):
    """Extension flow across two turns in ONE session: tokens stay consistent
    and a combined AI reply restores every original."""
    t1 = client.post("/api/sanitize", json={"text": "ผมชื่อ สมชาย ใจดี เบอร์ 081-234-5678"}).json()
    t2 = client.post(
        "/api/sanitize",
        json={"text": "ย้ำเบอร์ 081-234-5678 และอีเมล somchai@example.com",
              "session_id": t1["session_id"]},
    ).json()
    assert t2["session_id"] == t1["session_id"]
    tok1 = next(e["token"] for e in t1["entities"] if e["data_type"] == "PHONE")
    tok2 = next(e["token"] for e in t2["entities"] if e["data_type"] == "PHONE")
    assert tok1 == tok2
    reply = t1["sanitized_text"] + "\n" + t2["sanitized_text"]
    r = client.post("/api/reidentify",
                    json={"session_id": t1["session_id"], "text": reply}).json()
    assert "081-234-5678" in r["restored_text"]
    assert "somchai@example.com" in r["restored_text"]
    assert "สมชาย ใจดี" in r["restored_text"]


def test_sanitize_mode_conflict_400(client):
    s = client.post("/api/sanitize", json={"text": "เบอร์ 081-234-5678"}).json()
    resp = client.post("/api/sanitize",
                       json={"text": "อีกข้อความ", "mode": "surrogate",
                             "session_id": s["session_id"]})
    assert resp.status_code == 400


def test_business_doc_surrogates_stay_plausible(client):
    """Invoice numbers and meeting dates must mask as same-shape values
    (ID_NUMBER keeps digit length, DATE stays a date) — not as fake
    passports/birthdays — and restore exactly."""
    # 8-digit invoice number on purpose — 10 digits would be claimed by the
    # BANK_ACCOUNT pattern instead of ID_NUMBER.
    text = "ใบแจ้งหนี้เลขที่ 12345678 นัดประชุมวันที่ 12/05/2569 กับ สมชาย ใจดี"
    s = client.post("/api/sanitize", json={"text": text, "mode": "surrogate"}).json()
    assert "12345678" not in s["sanitized_text"]
    assert "12/05/2569" not in s["sanitized_text"]
    types = {e["data_type"] for e in s["entities"]}
    assert "ID_NUMBER" in types and "DATE" in types
    assert "PASSPORT" not in types and "DATE_OF_BIRTH" not in types
    r = client.post("/api/reidentify",
                    json={"session_id": s["session_id"], "text": s["sanitized_text"]}).json()
    assert "12345678" in r["restored_text"] and "12/05/2569" in r["restored_text"]
