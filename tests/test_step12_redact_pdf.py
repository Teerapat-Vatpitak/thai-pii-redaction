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

    return TestClient(
        app,
        base_url="http://localhost",
        headers={"X-AIGuard-Contract-Version": "2"},
    )


def _pdf_with_pii(tmp_path) -> bytes:
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    path = tmp_path / "in.pdf"
    c = canvas.Canvas(str(path), pagesize=letter)
    c.setFont("Helvetica", 12)
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
    assert data["detected_entity_count"] >= 2

    # a real redacted PDF and both previews come back
    redacted = base64.b64decode(data["redacted_pdf_b64"])
    assert redacted[:4] == b"%PDF"
    assert data["after_png_b64"]
    assert "before_png_b64" not in data

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
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "document_invalid"


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


def _two_page_text_pdf_with_logos(tmp_path) -> bytes:
    from PIL import Image
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    image = Image.new("RGB", (2, 2), (0, 0, 0))
    path = tmp_path / "two-page-text-with-logos.pdf"
    pdf = canvas.Canvas(str(path), pagesize=letter)
    for page_num in (1, 2):
        pdf.drawImage(ImageReader(image), 50, letter[1] - 20, width=8, height=8)
        pdf.drawString(
            50,
            letter[1] - 50,
            f"Selectable synthetic page {page_num} with enough safe text for extraction",
        )
        pdf.showPage()
    pdf.save()
    return path.read_bytes()


def _mixed_pdf_with_image_pii(tmp_path) -> bytes:
    from PIL import Image, ImageDraw
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    image = Image.new("RGB", (612, 792), "white")
    ImageDraw.Draw(image).text((50, 72), "081-234-5678", fill="black")
    path = tmp_path / "mixed.pdf"
    c = canvas.Canvas(str(path), pagesize=letter)
    c.drawImage(ImageReader(image), 0, 0, width=letter[0], height=letter[1])
    c.drawString(50, 40, "Selectable footer with more than twenty safe characters")
    c.save()
    return path.read_bytes()


def test_redact_pdf_mixed_page_redacts_image_only_pii(client, tmp_path, monkeypatch):
    import pypdfium2 as pdfium

    from pii_redactor.ingest import ocr_processor
    from pii_redactor.models import WordBbox

    phone = "081-234-5678"
    words = [WordBbox(text=phone, page=1, x=50, y=72, width=80, height=12)]
    monkeypatch.setattr(ocr_processor, "is_available", lambda: True)
    monkeypatch.setattr(
        ocr_processor,
        "ocr_page",
        lambda page, page_num, **kw: ocr_processor.OCRPageResult(
            words=words,
            text=phone,
            confidence=0.95,
            attempts=1,
            human_review=False,
        ),
    )

    response = client.post(
        "/api/redact-pdf",
        files={
            "pdf_file": (
                "mixed.pdf",
                _mixed_pdf_with_image_pii(tmp_path),
                "application/pdf",
            )
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_type"] == "pdf_hybrid"
    assert any(field["data_type"] == "PHONE" for field in payload["fields"])

    redacted = tmp_path / "mixed-redacted.pdf"
    redacted.write_bytes(base64.b64decode(payload["redacted_pdf_b64"]))
    doc = pdfium.PdfDocument(str(redacted))
    try:
        image = doc[0].render(scale=2).to_pil().convert("L")
        region = image.crop((96, 134, 264, 172))
        assert region.getextrema() == (0, 0)
    finally:
        doc.close()


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
    assert data["detected_entity_count"] >= 2


def test_redact_pdf_marks_review_in_the_audit_log(client, tmp_path, monkeypatch):
    from app import server
    from pii_redactor.ingest import ocr_processor
    from pii_redactor.models import WordBbox

    pdf = _scanned_pdf(tmp_path)
    fake_words = [WordBbox(text="ข้อความ", page=1, x=50, y=72, width=80, height=12)]
    audit_rows = []
    monkeypatch.setattr(ocr_processor, "is_available", lambda: True)
    monkeypatch.setattr(
        ocr_processor,
        "ocr_page",
        lambda page, page_num, **kw: ocr_processor.OCRPageResult(
            words=fake_words,
            text="ข้อความ",
            confidence=0.4,
            attempts=3,
            human_review=True,
        ),
    )
    monkeypatch.setattr(server, "write_process_log", lambda **row: audit_rows.append(row))

    resp = client.post(
        "/api/redact-pdf",
        files={"pdf_file": ("scan.pdf", pdf, "application/pdf")},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["human_review"] is True
    assert data["warnings"] == [
        {"code": "ocr_low_confidence", "count": 1},
        {"code": "human_review_required", "count": 1},
    ]
    assert audit_rows[-1]["validation_result"] == "warn"


def test_redact_pdf_hybrid_keeps_false_negative_scan_in_the_real_path(
    client, tmp_path, monkeypatch
):
    from pii_redactor.ingest import ocr_processor
    from pii_redactor.models import WordBbox

    pdf = _scanned_pdf(tmp_path)
    misread_id = "1312271506581"
    fake_words = [
        WordBbox(
            text=f"เลขประจำตัวประชาชน {misread_id}",
            page=1,
            x=50,
            y=72,
            width=220,
            height=12,
        )
    ]
    monkeypatch.setattr(ocr_processor, "is_available", lambda: True)
    monkeypatch.setattr(
        ocr_processor,
        "ocr_page",
        lambda page, page_num, **kw: ocr_processor.OCRPageResult(
            words=fake_words,
            text=f"เลขประจำตัวประชาชน {misread_id}",
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
    assert any(field["data_type"] == "THAI_ID" for field in data["fields"])


def test_redact_pdf_hybrid_without_ocr_deps_returns_503(client, tmp_path, monkeypatch):
    from pii_redactor.ingest import ocr_processor

    pdf = _scanned_pdf(tmp_path)
    monkeypatch.setattr(ocr_processor, "is_available", lambda: False)

    resp = client.post(
        "/api/redact-pdf",
        files={"pdf_file": ("scan.pdf", pdf, "application/pdf")},
    )
    assert resp.status_code == 503


def test_redact_pdf_counts_each_unreadable_image_page_for_review(
    client,
    tmp_path,
    monkeypatch,
):
    from pii_redactor.ingest import ocr_processor

    pdf = _two_page_text_pdf_with_logos(tmp_path)
    monkeypatch.setattr(ocr_processor, "is_available", lambda: False)

    response = client.post(
        "/api/redact-pdf",
        files={"pdf_file": ("text-with-logos.pdf", pdf, "application/pdf")},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["source_type"] == "pdf_hybrid"
    assert data["human_review"] is True
    assert data["warnings"] == [{"code": "human_review_required", "count": 2}]


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
    from pii_redactor.redactor import (
        REDACT_PAD_PT,
        REDACT_PAD_TOP_PT,
        _map_entities_to_boxes,
        _merge_boxes,
    )

    sample = Path(__file__).resolve().parents[1] / "examples" / "sample_document.pdf"
    if not sample.exists():
        pytest.skip("examples/sample_document.pdf not present")

    source_type = detect_source_type(str(sample))
    raw_text, word_bboxes, _meta = extract(str(sample), source_type)

    fp = detect_fp(raw_text)
    tb = detect_tb(raw_text)
    registry = EntityRegistry(entities=fp + tb, fp_count=len(fp), tb_count=len(tb))
    mapped_entities = _map_entities_to_boxes(registry, word_bboxes)

    page1_words = [wb for wb in word_bboxes if wb.page == 1]
    merged = []
    for entity_boxes in mapped_entities:
        pt_boxes = [
            (
                wb.x - REDACT_PAD_PT,
                wb.y - REDACT_PAD_TOP_PT,
                wb.x + wb.width + REDACT_PAD_PT,
                wb.y + wb.height + REDACT_PAD_PT,
            )
            for wb in entity_boxes
            if wb.page == 1
        ]
        merged.extend(_merge_boxes(pt_boxes))

    # "สมชาย" and "ใจดี" are two words of the same NAME entity/line, 3.4pt
    # apart -- they must land inside ONE merged rectangle (no exposed gap).
    name_words = [wb for wb in page1_words if wb.text.strip() in ("สมชาย", "ใจดี")]
    assert len(name_words) == 2
    covering = [
        (x0, y0, x1, y1)
        for x0, y0, x1, y1 in merged
        if all(
            x0 <= wb.x and y0 <= wb.y and x1 >= wb.x + wb.width and y1 >= wb.y + wb.height
            for wb in name_words
        )
    ]
    assert covering, "expected one rectangle covering both name words with no gap"

    # Every identifying ADDRESS value on the same line -- including the house
    # number after the form-style ``ที่อยู่:`` label -- must merge into one
    # box spanning the full line, closing both the original word gaps and the
    # exposed ``99`` regression.
    addr_words = [
        wb
        for wb in page1_words
        if wb.text.strip() in ("99", "ถนนพหลโยธิน", "แขวงจตุจักร", "กรุงเทพฯ", "10900")
    ]
    assert len(addr_words) == 5
    addr_rectangles = [
        (x0, y0, x1, y1)
        for x0, y0, x1, y1 in merged
        if any(
            x0 <= wb.x and y0 <= wb.y and x1 >= wb.x + wb.width and y1 >= wb.y + wb.height
            for wb in addr_words
        )
    ]
    assert all(
        any(
            x0 <= wb.x and y0 <= wb.y and x1 >= wb.x + wb.width and y1 >= wb.y + wb.height
            for x0, y0, x1, y1 in addr_rectangles
        )
        for wb in addr_words
    )
    horizontal_coverage = sorted((x0, x1) for x0, _y0, x1, _y1 in addr_rectangles)
    covered_until = horizontal_coverage[0][1]
    for x0, x1 in horizontal_coverage[1:]:
        assert x0 <= covered_until, "expected padded address rectangles to leave no gap"
        covered_until = max(covered_until, x1)


def test_redact_pdf_blacks_out_sample_house_number_pixels(tmp_path):
    """The actual rendered output must contain no visible pixels from house no. 99."""
    import pypdfium2 as pdfium

    from pii_redactor.detectors.fp_detector import detect_fp
    from pii_redactor.detectors.tb_detector import detect_tb
    from pii_redactor.ingest.file_detector import detect_source_type
    from pii_redactor.ingest.text_extractor import extract
    from pii_redactor.models import EntityRegistry
    from pii_redactor.redactor import RENDER_SCALE, redact_pdf

    sample = Path(__file__).resolve().parents[1] / "examples" / "sample_document.pdf"
    if not sample.exists():
        pytest.skip("examples/sample_document.pdf not present")

    source_type = detect_source_type(str(sample))
    raw_text, word_bboxes, _meta = extract(str(sample), source_type)
    fp = detect_fp(raw_text)
    tb = detect_tb(raw_text)
    registry = EntityRegistry(entities=fp + tb, fp_count=len(fp), tb_count=len(tb))

    house_entities = [
        entity for entity in fp if entity.data_type == "ADDRESS" and entity.original_text == "99"
    ]
    assert len(house_entities) == 1, "house number must be detected before PDF redaction"
    house_words = [wb for wb in word_bboxes if wb.page == 1 and wb.text.strip() == "99"]
    assert len(house_words) == 1, "fixture bug: could not find house-number bbox"

    out_path = tmp_path / "redacted-house-number.pdf"
    redact_pdf(str(sample), registry, word_bboxes, str(out_path))

    doc = pdfium.PdfDocument(str(out_path))
    try:
        pil = doc[0].render(scale=RENDER_SCALE).to_pil().convert("L")
    finally:
        doc.close()
    wb = house_words[0]
    x0 = int(wb.x * RENDER_SCALE)
    x1 = int((wb.x + wb.width) * RENDER_SCALE)
    y0 = int(wb.y * RENDER_SCALE)
    y1 = int((wb.y + wb.height) * RENDER_SCALE)
    region = pil.crop((x0, y0, x1, y1))
    assert region.width > 0 and region.height > 0
    _minimum, maximum = region.getextrema()
    assert maximum < 10, (
        f"house number {wb.text!r} bbox not covered by an opaque black rectangle "
        f"(max pixel intensity {maximum})"
    )


_SARABUN_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\sarabun-v17-latin_latin-ext_thai_vietnamese-regular.ttf",
    "/usr/share/fonts/truetype/thai/Sarabun-Regular.ttf",
]


def _pdf_with_thai_numeral_phone(tmp_path) -> Path:
    """A Sarabun-rendered PDF whose only PII is a phone number written in
    THAI NUMERALS (e.g. ๐๘๑-๒๓๔-๕๖๗๘), the case this regression targets."""
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas

    font_path = next((f for f in _SARABUN_FONT_CANDIDATES if Path(f).exists()), None)
    if font_path is None:
        pytest.skip("Sarabun font not found on this machine")
    pdfmetrics.registerFont(TTFont("Sarabun", font_path))

    path = tmp_path / "thai_numeral_phone.pdf"
    c = canvas.Canvas(str(path), pagesize=letter)
    c.setFont("Sarabun", 14)
    c.drawString(72, letter[1] - 72, "โปรดติดต่อกลับที่หมายเลขโทรศัพท์ ๐๘๑-๒๓๔-๕๖๗๘ ในเวลาราชการ")
    c.save()
    return path


def test_redact_pdf_covers_thai_numeral_phone_number(client, tmp_path):
    """
    Regression test for the half-fix in 2aeb219: that commit made detection
    run on a length-preserving normalisation of the extracted text (Thai
    digits -> Arabic digits), so a Thai-numeral phone number is now detected.
    But pii_redactor/redactor.py still matched WordBbox.text (raw PDF text,
    still Thai digits) against redact_fragments (the normalised entity text,
    Arabic digits) via plain substring comparison -- neither side is a
    substring of the other, so nothing matched and no black box was drawn.

    Asserting only `entity_count` (as the sibling tests in this file do) is
    exactly what let that gap ship: detection succeeded while redaction
    silently did nothing. This test instead renders the actual redacted PDF
    and checks the pixels over the phone number's own word bbox are opaque
    black, proving a rectangle was actually painted over it.
    """
    np = pytest.importorskip("numpy")
    import pypdfium2 as pdfium

    from pii_redactor.ingest.file_detector import detect_source_type
    from pii_redactor.ingest.text_extractor import extract
    from pii_redactor.redactor import RENDER_SCALE

    pdf_path = _pdf_with_thai_numeral_phone(tmp_path)
    pdf_bytes = pdf_path.read_bytes()

    resp = client.post(
        "/api/redact-pdf",
        files={"pdf_file": ("thai_numeral_phone.pdf", pdf_bytes, "application/pdf")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["detected_entity_count"] >= 1  # detection side; already fixed by 2aeb219

    # Independently locate the phone-number word's bbox via the same
    # extraction the endpoint used internally -- raw text, Thai digits intact
    # (this is NOT the redacted output; it re-reads the original input PDF).
    source_type = detect_source_type(str(pdf_path))
    _raw_text, word_bboxes, _meta = extract(str(pdf_path), source_type)
    phone_words = [wb for wb in word_bboxes if "๐๘๑" in wb.text]
    assert phone_words, "fixture bug: could not find the Thai-numeral phone word bbox"

    redacted = base64.b64decode(data["redacted_pdf_b64"])
    doc = pdfium.PdfDocument(io.BytesIO(redacted))
    pil = doc[0].render(scale=RENDER_SCALE).to_pil().convert("L")
    doc.close()
    arr = np.array(pil)

    for wb in phone_words:
        x0 = int(wb.x * RENDER_SCALE)
        y0 = int(wb.y * RENDER_SCALE)
        x1 = int((wb.x + wb.width) * RENDER_SCALE)
        y1 = int((wb.y + wb.height) * RENDER_SCALE)
        region = arr[y0:y1, x0:x1]
        assert region.size > 0
        assert region.max() < 10, (
            f"Thai-numeral phone word {wb.text!r} bbox not covered by a black "
            f"rectangle (max pixel intensity {region.max()} in region "
            f"y=[{y0}:{y1}] x=[{x0}:{x1}])"
        )


def test_redact_pdf_no_visible_ink_above_boxes(tmp_path):
    """
    Pixel-level regression test: renders the actual redacted PDF and checks
    that no dark (text) pixels are visible in a thin strip directly above
    each redaction rectangle. This is exactly the bug that was reported --
    tall Thai ascenders (e.g. in "ถนนพหลโยธิน") rendered ~3pt above the word
    bbox's nominal top, poking out above a too-tight/unpadded black box.
    """
    np = pytest.importorskip("numpy")
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
        wb
        for wb in word_bboxes
        if wb.page == 1
        and wb.text.strip()
        in (
            "สมชาย",
            "ใจดี",
            "ถนนพหลโยธิน",
            "แขวงจตุจักร",
            "กรุงเทพฯ",
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
