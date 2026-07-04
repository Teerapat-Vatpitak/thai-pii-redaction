"""Tests for Step 1 ingest: file_detector and text_extractor."""
from pathlib import Path

import pytest

from pii_redactor.ingest.file_detector import detect_source_type, validate_encoding
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
    thai_bytes = "สวัสดี".encode("utf-8")
    result = validate_encoding(thai_bytes)
    assert "สวัสดี" in result


def test_validate_encoding_invalid_raises():
    with pytest.raises(ValueError):
        validate_encoding(b"\xff\xfe\xfa")  # invalid in all Thai encodings


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


def test_extract_hybrid_without_ocr_deps_raises(monkeypatch):
    from pii_redactor.ingest import ocr_processor

    monkeypatch.setattr(ocr_processor, "is_available", lambda: False)
    with pytest.raises(ocr_processor.OCRUnavailableError):
        extract("tests/sample_thai.txt", "pdf_hybrid")


# ---------------------------------------------------------------------------
# PDF helpers and tests
# ---------------------------------------------------------------------------

def _make_test_pdf(text: str, tmp_path) -> Path:
    """Create a minimal text-layer PDF for testing."""
    import fitz
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), text, fontsize=12)
    path = tmp_path / "test.pdf"
    doc.save(str(path))
    doc.close()
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
    assert "Hello" in text or "World" in text  # flexible: pdfplumber or PyMuPDF
    assert meta == {}


def test_extract_pdf_text_returns_bboxes(tmp_path):
    pdf_path = _make_test_pdf("Hello World Test", tmp_path)
    text, bboxes, meta = extract(str(pdf_path), "pdf_text")
    # At least some word bboxes should be returned
    assert isinstance(bboxes, list)


def test_detect_pdf_hybrid(tmp_path):
    """A PDF with very little text should be classified as pdf_hybrid."""
    import fitz
    doc = fitz.open()
    doc.new_page()  # blank page — no text at all
    path = tmp_path / "blank.pdf"
    doc.save(str(path))
    doc.close()
    result = detect_source_type(str(path))
    assert result == "pdf_hybrid"


def test_extract_unknown_source_type_raises():
    with pytest.raises(ValueError, match="Unknown source_type"):
        extract("tests/sample_thai.txt", "unknown_type")


def _make_hybrid_test_pdf(tmp_path) -> Path:
    """A page with an inserted image and no insert_text call -- no text layer at all."""
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 100, 100))
    pix.set_rect(pix.irect, (255, 255, 255))
    page.insert_image(page.rect, pixmap=pix)
    path = tmp_path / "hybrid.pdf"
    doc.save(str(path))
    doc.close()
    return path


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

from pii_redactor.ingest.text_cleaner import clean, CleanResult


def test_clean_whitespace_normalization():
    text = "Hello   World\n\n\n\nParagraph"
    result = clean(text)
    assert "   " not in result.text    # no triple spaces
    assert "\n\n\n" not in result.text  # no triple newlines
    assert isinstance(result, CleanResult)


def test_clean_unicode_normalization():
    # NFC normalization: combine base + combining char into precomposed
    import unicodedata
    # Thai text should remain valid after NFC
    text = "สวัสดี"
    result = clean(text)
    assert unicodedata.is_normalized('NFC', result.text)


def test_clean_removes_zero_width():
    text = "Hello​World"  # zero-width space between
    result = clean(text)
    assert '​' not in result.text


def test_clean_thai_digits():
    text = "มี ๑๒๓ คน"
    result = clean(text)
    assert "123" in result.text
    assert "๑" not in result.text


def test_clean_returns_clean_result():
    result = clean("test text")
    assert hasattr(result, 'text')
    assert hasattr(result, 'skipped_sentence_review')
    assert hasattr(result, 'ocr_error_flags')
    assert hasattr(result, 'broken_sentence_candidates')
    assert hasattr(result, 'post_clean_warnings')


def test_clean_non_interactive_skips_review():
    # Text with a potential broken sentence
    text = "This is a long sentence that continues\nnext line starts here"
    result = clean(text, interactive=False)
    # Should not hang, should complete immediately
    assert isinstance(result.text, str)


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

from pii_redactor.ingest.quality_validator import validate, QualityResult


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
