"""/api/redact-pdf: real bbox-level PDF redaction (Task 3).

Verifies the endpoint returns a redacted PDF whose text layer no longer
contains the detected PII, plus before/after previews.
"""
import base64

import pytest

try:
    import fitz  # PyMuPDF
    from fastapi.testclient import TestClient
    from app.server import app
    DEPS = True
except ImportError:
    DEPS = False

pytestmark = pytest.mark.skipif(not DEPS, reason="fastapi/PyMuPDF not installed")


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from app.server import app
    return TestClient(app)


def _pdf_with_pii(tmp_path) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    # >= 50 chars so file_detector classifies this as pdf_text, not pdf_hybrid
    # (a short-but-real text layer would otherwise be mistaken for a scan).
    page.insert_text(
        (50, 72),
        "Please contact us at 081-234-5678 or email john@example.com today",
        fontsize=12,
    )
    path = tmp_path / "in.pdf"
    doc.save(str(path))
    doc.close()
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

    # the PII is gone from the redacted PDF's text layer
    doc = fitz.open(stream=redacted, filetype="pdf")
    text = "".join(p.get_text() for p in doc)
    doc.close()
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
    doc = fitz.open()
    page = doc.new_page()
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 100, 100))
    pix.set_rect(pix.irect, (255, 255, 255))
    page.insert_image(page.rect, pixmap=pix)
    path = tmp_path / "scan.pdf"
    doc.save(str(path))
    doc.close()
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
