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
    page.insert_text((50, 72), "Contact 081-234-5678 email john@example.com", fontsize=12)
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
