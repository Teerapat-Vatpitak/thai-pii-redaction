"""Tests for Step 1 ingest: file_detector and text_extractor."""

import gc
import sys
import weakref
from pathlib import Path
from types import SimpleNamespace

import pytest

from pii_redactor.ingest.file_detector import (
    detect_source_type,
    page_needs_ocr,
    validate_encoding,
)
from pii_redactor.ingest.text_extractor import extract
from pii_redactor.models import WordBbox

# ---------------------------------------------------------------------------
# file_detector tests
# ---------------------------------------------------------------------------


def test_detect_text_file():
    # tests/sample_thai.txt exists from Task 1
    result = detect_source_type("tests/sample_thai.txt")
    assert result == "text"


def test_detect_non_pdf_md():
    result = detect_source_type("CLAUDE.md")
    assert result == "text"


def test_validate_encoding_utf8():
    thai_bytes = "สวัสดี".encode()
    result = validate_encoding(thai_bytes)
    assert "สวัสดี" in result


def test_validate_encoding_invalid_raises():
    with pytest.raises(ValueError):
        validate_encoding(b"\xff\xfe\xfa")  # invalid in all Thai encodings


def test_page_ocr_fallback_discards_retained_exception_graph():
    retained_error = RuntimeError("synthetic object-enumeration failure")
    retained: dict[str, weakref.ReferenceType] = {}

    class Payload:
        pass

    class Page:
        def get_objects(self):
            payload = Payload()
            retained["payload"] = weakref.ref(payload)
            raise retained_error

    page = Page()
    retained["page"] = weakref.ref(page)

    assert page_needs_ocr(page) is True
    page = None
    gc.collect()

    assert retained_error.__traceback__ is None
    assert retained_error.__cause__ is None
    assert retained_error.__context__ is None
    assert retained["page"]() is None
    assert retained["payload"]() is None


# ---------------------------------------------------------------------------
# text_extractor tests
# ---------------------------------------------------------------------------


def test_extract_text_file():
    text, bboxes, meta = extract("tests/sample_thai.txt", "text")
    assert "วิทยา" in text
    assert bboxes == []  # no bboxes for plain text
    assert meta == {}


def test_extract_text_returns_unicode():
    text, _, _ = extract("tests/sample_thai.txt", "text")
    assert isinstance(text, str)


def test_extract_hybrid_without_ocr_deps_raises(tmp_path, monkeypatch):
    """An image-only page has no text layer to fall back to, so the hybrid
    path still refuses outright when the OCR extra is missing. (The fixture is
    a real scanned-shape PDF: the check is per page now, so handing this a
    non-PDF would only prove the argument was mis-routed.)
    """
    from pii_redactor.ingest import ocr_processor

    path = _make_hybrid_test_pdf(tmp_path)
    monkeypatch.setattr(ocr_processor, "is_available", lambda: False)
    with pytest.raises(ocr_processor.OCRUnavailableError):
        extract(path, "pdf_hybrid")


# ---------------------------------------------------------------------------
# PDF helpers and tests
# ---------------------------------------------------------------------------


def _make_test_pdf(text: str, tmp_path) -> Path:
    """Create a minimal text-layer PDF for testing."""
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    path = tmp_path / "test.pdf"
    c = canvas.Canvas(str(path), pagesize=letter)
    c.setFont("Helvetica", 12)
    c.drawString(50, letter[1] - 50, text)
    c.save()
    return path


def test_detect_pdf_text(tmp_path):
    # String must be >= 50 chars to exceed the pdf_text threshold
    pdf_path = _make_test_pdf(
        "Hello World Test Document With Many Words And Extra Text Here", tmp_path
    )
    result = detect_source_type(str(pdf_path))
    assert result == "pdf_text"


def test_extract_pdf_text(tmp_path):
    pdf_path = _make_test_pdf("Hello World Test", tmp_path)
    text, bboxes, meta = extract(str(pdf_path), "pdf_text")
    assert "Hello" in text or "World" in text  # flexible: pdfplumber or pypdfium2 fallback
    assert meta == {}


def test_extract_pdf_text_returns_bboxes(tmp_path):
    pdf_path = _make_test_pdf("Hello World Test", tmp_path)
    text, bboxes, meta = extract(str(pdf_path), "pdf_text")
    # At least some word bboxes should be returned
    assert isinstance(bboxes, list)


def test_pdf_text_fallback_discards_retained_exception_graph(tmp_path, monkeypatch):
    from pii_redactor.ingest import text_extractor

    retained_error = RuntimeError("synthetic word-extraction failure")
    retained: dict[str, weakref.ReferenceType] = {}

    class ExtractedText(str):
        pass

    class Page:
        page_number = 1

        def extract_text(self):
            text = ExtractedText("synthetic extracted page text")
            retained["text"] = weakref.ref(text)
            return text

        def extract_words(self):
            raise retained_error

    class Pdf:
        def __enter__(self):
            page = Page()
            retained["page"] = weakref.ref(page)
            self.pages = [page]
            return self

        def __exit__(self, _error_type, _error, _traceback):
            self.pages.clear()

    monkeypatch.setitem(sys.modules, "pdfplumber", SimpleNamespace(open=lambda _path: Pdf()))
    monkeypatch.setattr(
        text_extractor,
        "_extract_pdf_pypdfium2",
        lambda _path: ("synthetic fallback text", []),
    )

    result = text_extractor._extract_pdf_text(tmp_path / "synthetic.pdf")
    gc.collect()

    assert result == ("synthetic fallback text", [])
    assert retained_error.__traceback__ is None
    assert retained_error.__cause__ is None
    assert retained_error.__context__ is None
    assert retained["page"]() is None
    assert retained["text"]() is None


def test_detect_pdf_hybrid(tmp_path):
    """A page that is an image with no text layer is image-only -> pdf_hybrid.

    (A genuinely blank page is not: it has nothing to OCR. See
    test_recall_leaks.py for the per-page routing regression cases.)
    """
    path = _make_hybrid_test_pdf(tmp_path)
    result = detect_source_type(str(path))
    assert result == "pdf_hybrid"


def test_extract_unknown_source_type_raises():
    with pytest.raises(ValueError, match="Unknown source_type"):
        extract("tests/sample_thai.txt", "unknown_type")


def _make_hybrid_test_pdf(tmp_path) -> Path:
    """A page with an inserted image and no text calls -- no text layer at all."""
    from PIL import Image
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    image = Image.new("RGB", (100, 100), (255, 255, 255))
    path = tmp_path / "hybrid.pdf"
    c = canvas.Canvas(str(path), pagesize=letter)
    c.drawImage(ImageReader(image), 0, 0, width=letter[0], height=letter[1])
    c.save()
    return path


def _make_mixed_page_pdf(tmp_path) -> Path:
    """A raster page with a small selectable text overlay."""
    from PIL import Image
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    image = Image.new("RGB", (100, 100), (255, 255, 255))
    path = tmp_path / "mixed-page.pdf"
    c = canvas.Canvas(str(path), pagesize=letter)
    c.drawImage(ImageReader(image), 0, 0, width=letter[0], height=letter[1])
    c.drawString(50, letter[1] - 50, "Selectable footer with more than twenty characters")
    c.save()
    return path


def _make_text_pdf_with_tiny_logo(tmp_path) -> Path:
    from PIL import Image
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    image = Image.new("RGB", (2, 2), (0, 0, 0))
    path = tmp_path / "text-with-logo.pdf"
    c = canvas.Canvas(str(path), pagesize=letter)
    c.drawImage(ImageReader(image), 50, letter[1] - 20, width=8, height=8)
    c.drawString(50, letter[1] - 50, "Selectable text with a small logo and no scanned page")
    c.save()
    return path


def _make_searchable_scan_pdf(tmp_path) -> Path:
    from PIL import Image, ImageDraw
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    phone = "081-234-5678"
    image = Image.new("RGB", (612, 792), "white")
    ImageDraw.Draw(image).text((50, 72), phone, fill="black")
    path = tmp_path / "searchable-scan.pdf"
    c = canvas.Canvas(str(path), pagesize=letter)
    c.drawImage(ImageReader(image), 0, 0, width=letter[0], height=letter[1])
    c.drawString(50, letter[1] - 72, phone)
    c.save()
    return path


def _make_partial_overlay_scan_pdf(tmp_path) -> Path:
    from PIL import Image, ImageDraw
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    phone = "081-234-5678"
    image = Image.new("RGB", (612, 792), "white")
    ImageDraw.Draw(image).text((50, 72), phone, fill="black")
    path = tmp_path / "partial-overlay-scan.pdf"
    c = canvas.Canvas(str(path), pagesize=letter)
    c.drawImage(ImageReader(image), 0, 0, width=letter[0], height=letter[1])
    c.drawString(50, letter[1] - 72, "1234")
    c.save()
    return path


def test_detect_mixed_page_requires_ocr(tmp_path):
    path = _make_mixed_page_pdf(tmp_path)

    assert detect_source_type(path) == "pdf_hybrid"


def test_tiny_logo_degrades_loudly_without_optional_ocr(tmp_path, monkeypatch):
    """A letterhead logo must not cost a core-only install the whole document.

    Routing sends any raster page to the hybrid path, so an ordinary digital
    PDF with a logo lands here. Refusing it outright reads as failing closed,
    but the packaged exe ships without requirements-ocr.txt, so it would take
    PDF redaction away from every such document — the text layer that carries
    the PII is right there and readable. The page is extracted from its text
    layer instead, and the caller is told what was skipped: /api/redact-pdf
    returns both human_review and ocr_warnings, so this is a surfaced limit,
    not a silent one. Failing closed stays for the case that earns it below.
    """
    from pii_redactor.ingest import ocr_processor

    path = _make_text_pdf_with_tiny_logo(tmp_path)
    monkeypatch.setattr(ocr_processor, "is_available", lambda: False)

    source_type = detect_source_type(path)
    assert source_type == "pdf_hybrid"

    text, _bboxes, meta = extract(path, source_type)

    assert "Selectable text with a small logo" in text
    assert meta["human_review"] is True
    assert any("OCR is not installed" in warning for warning in meta["warnings"])


def test_extract_surfaces_ocr_engine_retry_warnings_in_meta(tmp_path, monkeypatch):
    """A bare-RuntimeError engine retry inside ocr_page must never be silent:
    the page-level warning reaches extract() meta warnings, which is what the
    acceptance harness counts into evidence (warning_count)."""
    from pii_redactor.ingest import ocr_processor

    retry_warning = "page 1: OCR attempt 1 raised RuntimeError; retried once"
    path = _make_hybrid_test_pdf(tmp_path)
    monkeypatch.setattr(ocr_processor, "is_available", lambda: True)
    monkeypatch.setattr(
        ocr_processor,
        "ocr_page",
        lambda page, page_num, **kw: ocr_processor.OCRPageResult(
            words=[WordBbox(text="สวัสดี", page=1, x=0, y=0, width=10, height=10)],
            text="สวัสดี",
            confidence=0.95,
            attempts=2,
            human_review=False,
            warnings=[retry_warning],
        ),
    )

    _text, _bboxes, meta = extract(path, "pdf_hybrid")

    assert retry_warning in meta["warnings"]


def test_hybrid_drops_the_same_text_from_the_same_place(tmp_path, monkeypatch):
    from pii_redactor.detectors.aggregate import detect_all
    from pii_redactor.ingest import ocr_processor

    phone = "081-234-5678"
    ocr_line = f"โทร {phone}"
    path = _make_searchable_scan_pdf(tmp_path)
    monkeypatch.setattr(ocr_processor, "is_available", lambda: True)
    monkeypatch.setattr(
        ocr_processor,
        "ocr_page",
        lambda page, page_num, **kw: ocr_processor.OCRPageResult(
            words=[WordBbox(text=ocr_line, page=1, x=30, y=62, width=102, height=14)],
            text=ocr_line,
            confidence=0.95,
            attempts=1,
            human_review=False,
        ),
    )

    text, bboxes, _meta = extract(path, detect_source_type(path))
    phones = [entity for entity in detect_all(text) if entity.data_type == "PHONE"]

    assert text.count(phone) == 1
    assert len(phones) == 1
    assert any(word.text == ocr_line for word in bboxes)


def test_partial_overlay_cannot_hide_structured_ocr_text(tmp_path, monkeypatch):
    from pii_redactor.detectors.aggregate import detect_all
    from pii_redactor.ingest import ocr_processor

    phone = "081-234-5678"
    path = _make_partial_overlay_scan_pdf(tmp_path)
    monkeypatch.setattr(ocr_processor, "is_available", lambda: True)
    monkeypatch.setattr(
        ocr_processor,
        "ocr_page",
        lambda page, page_num, **kw: ocr_processor.OCRPageResult(
            words=[WordBbox(text=phone, page=1, x=50, y=62, width=82, height=14)],
            text=phone,
            confidence=0.95,
            attempts=1,
            human_review=False,
        ),
    )

    text, bboxes, _meta = extract(path, detect_source_type(path))

    assert phone in text
    assert any(entity.data_type == "PHONE" for entity in detect_all(text))
    assert any(word.text == phone for word in bboxes)


def test_extract_pdf_hybrid_returns_3_tuple_with_meta(tmp_path, monkeypatch):
    from pii_redactor.ingest import ocr_processor

    pdf_path = _make_hybrid_test_pdf(tmp_path)
    fake_words = [WordBbox(text="สวัสดี", page=1, x=0, y=0, width=10, height=10)]
    monkeypatch.setattr(ocr_processor, "is_available", lambda: True)
    monkeypatch.setattr(
        ocr_processor,
        "ocr_page",
        lambda page, page_num, **kw: ocr_processor.OCRPageResult(
            words=fake_words, text="สวัสดี", confidence=0.9, attempts=1, human_review=False
        ),
    )

    text, bboxes, meta = extract(str(pdf_path), "pdf_hybrid")

    assert text == "สวัสดี"
    assert bboxes == fake_words
    assert meta["pages_ocred"] == [1]
    assert meta["pages_text_layer"] == []
    assert meta["ocr_confidence"] == pytest.approx(0.9)
    assert meta["human_review"] is False
    assert meta["warnings"] == []


def test_extract_pdf_hybrid_merges_text_layer_and_ocr_on_one_page(tmp_path, monkeypatch):
    from pii_redactor.ingest import ocr_processor

    pdf_path = _make_mixed_page_pdf(tmp_path)
    fake_words = [WordBbox(text="OCR image text", page=1, x=20, y=30, width=80, height=10)]
    monkeypatch.setattr(ocr_processor, "is_available", lambda: True)
    monkeypatch.setattr(
        ocr_processor,
        "ocr_page",
        lambda page, page_num, **kw: ocr_processor.OCRPageResult(
            words=fake_words,
            text="OCR image text",
            confidence=0.9,
            attempts=1,
            human_review=False,
        ),
    )

    text, bboxes, meta = extract(pdf_path, "pdf_hybrid")

    assert "Selectable footer" in text
    assert "OCR image text" in text
    assert fake_words[0] in bboxes
    assert meta["pages_ocred"] == [1]
    assert meta["pages_text_layer"] == [1]
    assert meta["ocr_text_ranges"]
    assert all(text[start:end].strip() for start, end in meta["ocr_text_ranges"])


def test_extract_pdf_hybrid_keeps_ocr_line_boundaries_in_range(tmp_path, monkeypatch):
    from pii_redactor.ingest import ocr_processor

    pdf_path = _make_mixed_page_pdf(tmp_path)
    ocr_text = "บรรทัดหนึ่ง\nเลข 1234567890123"
    fake_words = [
        WordBbox(text="บรรทัดหนึ่ง", page=1, x=20, y=30, width=80, height=10),
        WordBbox(text="เลข 1234567890123", page=1, x=20, y=50, width=80, height=10),
    ]
    monkeypatch.setattr(ocr_processor, "is_available", lambda: True)
    monkeypatch.setattr(
        ocr_processor,
        "ocr_page",
        lambda page, page_num, **kw: ocr_processor.OCRPageResult(
            words=fake_words,
            text=ocr_text,
            confidence=0.9,
            attempts=1,
            human_review=False,
        ),
    )

    text, bboxes, meta = extract(pdf_path, "pdf_hybrid")

    start, end = meta["ocr_text_ranges"][0]
    assert text[start:end] == ocr_text
    assert fake_words == [word for word in bboxes if word in fake_words]


def test_extract_pdf_hybrid_human_review_propagates(tmp_path, monkeypatch):
    from pii_redactor.ingest import ocr_processor

    pdf_path = _make_hybrid_test_pdf(tmp_path)
    monkeypatch.setattr(ocr_processor, "is_available", lambda: True)
    monkeypatch.setattr(
        ocr_processor,
        "ocr_page",
        lambda page, page_num, **kw: ocr_processor.OCRPageResult(
            words=[], text="", confidence=0.2, attempts=3, human_review=True
        ),
    )

    text, bboxes, meta = extract(str(pdf_path), "pdf_hybrid")

    assert meta["human_review"] is True
    assert meta["ocr_confidence"] == pytest.approx(0.2)
    assert len(meta["warnings"]) == 1


# ---------------------------------------------------------------------------
# text_cleaner tests (Task 4)
# ---------------------------------------------------------------------------

from pii_redactor.ingest.text_cleaner import CleanResult, clean


def test_clean_whitespace_normalization():
    text = "Hello   World\n\n\n\nParagraph"
    result = clean(text)
    assert "   " not in result.text  # no triple spaces
    assert "\n\n\n" not in result.text  # no triple newlines
    assert isinstance(result, CleanResult)


def test_clean_unicode_normalization():
    # NFC normalization: combine base + combining char into precomposed
    import unicodedata

    # Thai text should remain valid after NFC
    text = "สวัสดี"
    result = clean(text)
    assert unicodedata.is_normalized("NFC", result.text)


def test_clean_removes_zero_width():
    text = "Hello​World"  # zero-width space between
    result = clean(text)
    assert "​" not in result.text


def test_clean_thai_digits():
    text = "มี ๑๒๓ คน"
    result = clean(text)
    assert "123" in result.text
    assert "๑" not in result.text


def test_clean_returns_clean_result():
    result = clean("test text")
    assert hasattr(result, "text")
    assert hasattr(result, "post_clean_warnings")


def test_clean_dropped_the_dead_stage_outputs():
    """Stages 4/5/6 were removed (kill-list, verified): stage 4 never changed
    real text yet loaded the whole Thai dictionary, stage 5 flagged every word
    containing B or Z, stage 6's interactive branch was unreachable (no caller
    passes interactive=True) — and nothing consumed any of their outputs."""
    result = clean("test text")
    for dead in ("skipped_sentence_review", "ocr_error_flags", "broken_sentence_candidates"):
        assert not hasattr(result, dead), f"{dead} should have been removed with its stage"


def test_clean_does_not_depend_on_the_thai_tokenizer(monkeypatch):
    """Stage 4 tokenized every input through PyThaiNLP just to rejoin it
    unchanged. Cleaning must no longer touch the tokenizer at all."""
    import pythainlp

    def _boom(*a, **k):
        raise AssertionError("clean() must not tokenize (stage 4 is gone)")

    monkeypatch.setattr(pythainlp, "word_tokenize", _boom)
    result = clean("ผมชื่อสมชาย ใจดี เบอร์ 081-234-5678")
    assert "สมชาย" in result.text


def test_clean_preserves_text_it_used_to_rewrite():
    """Regression: the removed merge step could concatenate adjacent Thai
    tokens. Cleaning now only normalizes — Thai content passes through."""
    text = "ผู้ป่วยมีอาการปวดศีรษะ และได้รับการวินิจฉัยว่าเป็นไมเกรน"
    assert clean(text).text == text


def test_clean_empty_text():
    result = clean("")
    assert result.text == ""


def test_clean_sample_thai():
    from pathlib import Path

    text = Path("tests/sample_thai.txt").read_text(encoding="utf-8")
    result = clean(text, interactive=False)
    assert "วิทยา" in result.text
    assert "1101200012345" in result.text  # Thai ID preserved


# ---------------------------------------------------------------------------
# quality_validator tests (Task 5)
# ---------------------------------------------------------------------------

from pii_redactor.ingest.quality_validator import QualityResult, validate


def test_validate_returns_quality_result():
    result = validate("สวัสดีครับ ทดสอบข้อความภาษาไทย", "text")
    assert isinstance(result, QualityResult)
    assert 0 <= result.quality_score <= 100
    assert result.grade in ("A", "B", "C", "D", "F")


def test_validate_good_thai_text_scores_high():
    # The sample Thai text should score well
    from pathlib import Path

    text = Path("tests/sample_thai.txt").read_text(encoding="utf-8")
    result = validate(text, "text")
    assert result.quality_score >= 60  # At least grade B
    assert result.pattern_ok


def test_validate_empty_text_fails():
    result = validate("", "text")
    assert result.quality_score < 40
    assert not result.pattern_ok
    assert len(result.warnings) > 0


def test_validate_whitespace_only_fails():
    result = validate("   \n\n   ", "text")
    assert not result.pattern_ok


def test_validate_grade_a():
    # Pure Thai text should score A
    text = "สวัสดีครับ นี่คือข้อความภาษาไทยที่สมบูรณ์ มีหลายประโยค\nแต่ละประโยคมีความยาวเพียงพอ"
    result = validate(text, "text")
    assert result.grade in ("A", "B")  # Should be at least B


def test_validate_ocr_confidence_text_type():
    # For non-pdf_hybrid, ocr_confidence_ok should be True even without confidence
    result = validate("some text", "text")
    assert result.ocr_confidence_ok is True


def test_validate_pdf_hybrid_low_confidence():
    result = validate("some text", "pdf_hybrid", ocr_confidence=0.5)
    assert not result.ocr_confidence_ok
    assert any("OCR confidence" in w for w in result.warnings)


def test_validate_pdf_hybrid_good_confidence():
    result = validate("some thai text", "pdf_hybrid", ocr_confidence=0.9)
    assert result.ocr_confidence_ok


# ---------------------------------------------------------------------------
# text_cleaner: clean_length_preserving
# ---------------------------------------------------------------------------


def test_clean_length_preserving_converts_thai_digits_without_moving_offsets():
    """The redact-pdf path needs Thai numerals converted but offsets intact,
    because word bboxes are indexed by character position."""
    from pii_redactor.ingest.text_cleaner import clean_length_preserving

    raw = "โทร ๐๘๑-๒๓๔-๕๖๗๘  ครับ​"
    out = clean_length_preserving(raw)

    assert len(out) == len(raw), "offsets moved; bboxes would misalign"
    assert "081-234-5678" in out
    assert "  " in out, "whitespace must NOT be collapsed on this tier"
    assert "​" in out, "zero-width must NOT be stripped on this tier"


def test_thai_numeral_phone_is_detected_after_length_preserving_clean():
    from pii_redactor.detectors.fp_detector import detect_fp
    from pii_redactor.ingest.text_cleaner import clean_length_preserving

    cleaned = clean_length_preserving("ติดต่อ ๐๘๑-๒๓๔-๕๖๗๘")
    assert [e for e in detect_fp(cleaned) if e.data_type == "PHONE"]
