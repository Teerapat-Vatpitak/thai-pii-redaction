"""/api/redact-pdf: real bbox-level PDF redaction (Task 3).

Verifies the endpoint returns a redacted PDF whose text layer no longer
contains the detected PII, plus before/after previews.
"""
import base64
import io

import pdfplumber
import pytest

try:
    from fastapi.testclient import TestClient
    from app.server import app
    DEPS = True
except ImportError:
    DEPS = False

pytestmark = pytest.mark.skipif(not DEPS, reason="fastapi not installed")


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from app.server import app
    return TestClient(app)


def _pdf_with_pii(tmp_path) -> bytes:
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    path = tmp_path / "in.pdf"
    c = canvas.Canvas(str(path), pagesize=letter)
    c.setFont("Helvetica", 12)
    # >= 50 chars so file_detector classifies this as pdf_text, not pdf_hybrid
    # (a short-but-real text layer would otherwise be mistaken for a scan).
    c.drawString(
        50, letter[1] - 72, "Please contact us at 081-234-5678 or email john@example.com today"
    )
    c.save()
    return path.read_bytes()


def test_redact_pdf_blacks_out_pii(client, tmp_path):
    pdf = _pdf_with_pii(tmp_path)
    resp = client.post(
        "/api/redact-pdf",
        files={"pdf_file": ("test.pdf", pdf, "application/pdf")},
    )
    assert resp.status_code == 200
    data = resp.json()

    # detection found the phone + email
    assert data["entity_count"] >= 2

    # a real redacted PDF and both previews come back
    redacted = base64.b64decode(data["redacted_pdf_b64"])
    assert redacted[:4] == b"%PDF"
    assert data["before_png_b64"] and data["after_png_b64"]

    # the redacted PDF is flattened to an image, so its text layer is empty --
    # the PII (and everything else) is unrecoverable via text extraction.
    with pdfplumber.open(io.BytesIO(redacted)) as doc:
        text = "".join(p.extract_text() or "" for p in doc.pages)
    assert text.strip() == ""
    assert "081-234-5678" not in text
    assert "john@example.com" not in text


def test_redact_pdf_rejects_non_pdf(client):
    resp = client.post(
        "/api/redact-pdf",
        files={"pdf_file": ("note.txt", b"hello", "text/plain")},
    )
    assert resp.status_code == 400


def _scanned_pdf(tmp_path) -> bytes:
    """A page with an inserted image and no text layer -- looks scanned."""
    from PIL import Image
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    image = Image.new("RGB", (100, 100), (255, 255, 255))
    path = tmp_path / "scan.pdf"
    c = canvas.Canvas(str(path), pagesize=letter)
    c.drawImage(ImageReader(image), 0, 0, width=letter[0], height=letter[1])
    c.save()
    return path.read_bytes()


def test_redact_pdf_hybrid_ocr_path(client, tmp_path, monkeypatch):
    from pii_redactor.ingest import ocr_processor
    from pii_redactor.models import WordBbox

    pdf = _scanned_pdf(tmp_path)
    fake_words = [
        WordBbox(
            text="Contact 081-234-5678 email john@example.com",
            page=1,
            x=50,
            y=72,
            width=300,
            height=12,
        )
    ]
    monkeypatch.setattr(ocr_processor, "is_available", lambda: True)
    monkeypatch.setattr(
        ocr_processor,
        "ocr_page",
        lambda page, page_num, **kw: ocr_processor.OCRPageResult(
            words=fake_words,
            text="Contact 081-234-5678 email john@example.com",
            confidence=0.85,
            attempts=1,
            human_review=False,
        ),
    )

    resp = client.post(
        "/api/redact-pdf",
        files={"pdf_file": ("scan.pdf", pdf, "application/pdf")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["source_type"] == "pdf_hybrid"
    assert data["ocr_confidence"] == pytest.approx(0.85)
    assert data["human_review"] is False
    assert data["entity_count"] >= 2


def test_redact_pdf_hybrid_without_ocr_deps_returns_503(client, tmp_path, monkeypatch):
    from pii_redactor.ingest import ocr_processor

    pdf = _scanned_pdf(tmp_path)
    monkeypatch.setattr(ocr_processor, "is_available", lambda: False)

    resp = client.post(
        "/api/redact-pdf",
        files={"pdf_file": ("scan.pdf", pdf, "application/pdf")},
    )
    assert resp.status_code == 503
