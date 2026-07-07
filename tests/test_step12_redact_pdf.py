"""/api/redact-pdf: real bbox-level PDF redaction (Task 3).

Verifies the endpoint returns a redacted PDF whose text layer no longer
contains the detected PII, plus before/after previews.
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


# --- Coverage-gap regression: adjacent word bboxes of one entity must merge
# into a single padded rectangle so no glyph fragment is exposed between them
# (see pii_redactor/redactor.py REDACT_PAD_PT / REDACT_MERGE_GAP_PT). ---

def test_merge_boxes_joins_adjacent_same_line_words():
    from pii_redactor.redactor import _merge_boxes

    # Two word boxes on the same line ("สมชาย" then "ใจดี"), 3.4pt apart --
    # simulates a multi-word NAME entity. They must collapse into one box.
    boxes = [
        (149.0, 117.25, 189.0, 131.25),
        (192.4, 117.25, 213.76, 131.25),
    ]
    merged = _merge_boxes(boxes)
    assert len(merged) == 1
    x0, y0, x1, y1 = merged[0]
    # The merged rectangle must fully cover both original boxes, no gap.
    assert x0 <= 149.0 and x1 >= 213.76
    assert y0 <= 117.25 and y1 >= 131.25


def test_merge_boxes_keeps_separate_lines_apart():
    from pii_redactor.redactor import _merge_boxes

    # Two boxes on different lines (large vertical gap) must NOT merge.
    boxes = [
        (72.0, 117.25, 150.0, 131.25),
        (72.0, 200.0, 150.0, 214.0),
    ]
    merged = _merge_boxes(boxes)
    assert len(merged) == 2


def test_merge_boxes_keeps_far_apart_words_on_same_line_separate():
    from pii_redactor.redactor import _merge_boxes

    # Same line, but far apart horizontally (beyond REDACT_MERGE_GAP_PT) --
    # e.g. an unredacted label sitting between two redacted words.
    boxes = [
        (72.0, 117.25, 100.0, 131.25),
        (400.0, 117.25, 430.0, 131.25),
    ]
    merged = _merge_boxes(boxes)
    assert len(merged) == 2


def test_redact_pdf_covers_full_padded_span_on_sample_document():
    """
    Regression test for the reported leak: redacting examples/sample_document.pdf
    must produce solid black coverage (with margin) over the full NAME entity
    ("สมชาย ใจดี") and the full multi-word ADDRESS line, with no exposed pixel
    gap between the words that make up a single entity/line.
    """
    from pii_redactor.detectors.fp_detector import detect_fp
    from pii_redactor.detectors.tb_detector import detect_tb
    from pii_redactor.ingest.file_detector import detect_source_type
    from pii_redactor.ingest.text_extractor import extract
    from pii_redactor.models import EntityRegistry
    from pii_redactor.redactor import REDACT_PAD_PT, REDACT_PAD_TOP_PT, _build_redact_set, _merge_boxes

    sample = Path(__file__).resolve().parents[1] / "examples" / "sample_document.pdf"
    if not sample.exists():
        pytest.skip("examples/sample_document.pdf not present")

    source_type = detect_source_type(str(sample))
    raw_text, word_bboxes, _meta = extract(str(sample), source_type)

    fp = detect_fp(raw_text)
    tb = detect_tb(raw_text)
    registry = EntityRegistry(entities=fp + tb, fp_count=len(fp), tb_count=len(tb))
    fragments = _build_redact_set(registry)

    page1_words = [wb for wb in word_bboxes if wb.page == 1]
    pt_boxes = []
    for wb in page1_words:
        word_text = wb.text.strip()
        should_redact = len(word_text) >= 2 and any(
            word_text in frag or frag in word_text for frag in fragments
        )
        if should_redact:
            pt_boxes.append((
                wb.x - REDACT_PAD_PT,
                wb.y - REDACT_PAD_TOP_PT,
                wb.x + wb.width + REDACT_PAD_PT,
                wb.y + wb.height + REDACT_PAD_PT,
            ))
    merged = _merge_boxes(pt_boxes)

    # "สมชาย" and "ใจดี" are two words of the same NAME entity/line, 3.4pt
    # apart -- they must land inside ONE merged rectangle (no exposed gap).
    name_words = [wb for wb in page1_words if wb.text.strip() in ("สมชาย", "ใจดี")]
    assert len(name_words) == 2
    covering = [
        (x0, y0, x1, y1) for x0, y0, x1, y1 in merged
        if all(
            x0 <= wb.x and y0 <= wb.y
            and x1 >= wb.x + wb.width and y1 >= wb.y + wb.height
            for wb in name_words
        )
    ]
    assert covering, "expected one rectangle covering both name words with no gap"

    # The three ADDRESS words on the same line must also merge into one box
    # spanning the full line, closing the gaps visible in the earlier bug.
    addr_words = [
        wb for wb in page1_words
        if wb.text.strip() in ("ถนนพหลโยธิน", "แขวงจตุจักร", "กรุงเทพฯ")
    ]
    assert len(addr_words) == 3
    addr_covering = [
        (x0, y0, x1, y1) for x0, y0, x1, y1 in merged
        if all(
            x0 <= wb.x and y0 <= wb.y
            and x1 >= wb.x + wb.width and y1 >= wb.y + wb.height
            for wb in addr_words
        )
    ]
    assert addr_covering, "expected one rectangle covering the full address line with no gap"


def test_redact_pdf_no_visible_ink_above_boxes(tmp_path):
    """
    Pixel-level regression test: renders the actual redacted PDF and checks
    that no dark (text) pixels are visible in a thin strip directly above
    each redaction rectangle. This is exactly the bug that was reported --
    tall Thai ascenders (e.g. in "ถนนพหลโยธิน") rendered ~3pt above the word
    bbox's nominal top, poking out above a too-tight/unpadded black box.
    """
    import numpy as np
    import pypdfium2 as pdfium

    from pii_redactor.detectors.fp_detector import detect_fp
    from pii_redactor.detectors.tb_detector import detect_tb
    from pii_redactor.ingest.file_detector import detect_source_type
    from pii_redactor.ingest.text_extractor import extract
    from pii_redactor.models import EntityRegistry
    from pii_redactor.redactor import REDACT_PAD_TOP_PT, RENDER_SCALE, redact_pdf

    sample = Path(__file__).resolve().parents[1] / "examples" / "sample_document.pdf"
    if not sample.exists():
        pytest.skip("examples/sample_document.pdf not present")

    source_type = detect_source_type(str(sample))
    raw_text, word_bboxes, _meta = extract(str(sample), source_type)
    fp = detect_fp(raw_text)
    tb = detect_tb(raw_text)
    registry = EntityRegistry(entities=fp + tb, fp_count=len(fp), tb_count=len(tb))

    out_path = tmp_path / "redacted.pdf"
    redact_pdf(str(sample), registry, word_bboxes, str(out_path))

    doc = pdfium.PdfDocument(str(out_path))
    pil = doc[0].render(scale=RENDER_SCALE).to_pil().convert("L")
    doc.close()
    arr = np.array(pil)

    redacted_words = [
        wb for wb in word_bboxes
        if wb.page == 1 and wb.text.strip() in (
            "สมชาย", "ใจดี", "ถนนพหลโยธิน", "แขวงจตุจักร", "กรุงเทพฯ",
        )
    ]
    assert redacted_words

    for wb in redacted_words:
        # A strip above the *padded* box (i.e. above where the black
        # rectangle's own top edge lands, not the word's un-padded bbox
        # top): this is where an under-padded box would let an ascender
        # (sara/tone mark, tall consonant) show through as a stray glyph
        # fragment on an otherwise clean white background.
        x0 = int(wb.x * RENDER_SCALE)
        x1 = int((wb.x + wb.width) * RENDER_SCALE)
        padded_top = int((wb.y - REDACT_PAD_TOP_PT) * RENDER_SCALE)
        strip_bottom = padded_top - 2
        strip_top = strip_bottom - 10
        if strip_top < 0:
            continue
        strip = arr[strip_top:strip_bottom, x0:x1]
        # Expect a clean white background here -- no partial-gray
        # anti-aliased glyph edge and no solid black ink at all. A leaking
        # ascender tip shows up as light gray (~220) before solid black, so
        # the threshold must be close to white, not merely "not black".
        assert strip.min() > 250, (
            f"exposed pixel fragment above redacted word {wb.text!r} "
            f"(min intensity {strip.min()} in strip y=[{strip_top},{strip_bottom}])"
        )
