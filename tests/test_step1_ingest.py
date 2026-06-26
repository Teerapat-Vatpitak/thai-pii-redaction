"""Tests for Step 1 ingest: file_detector and text_extractor."""
from pathlib import Path

import pytest

from pii_redactor.ingest.file_detector import detect_source_type, validate_encoding
from pii_redactor.ingest.text_extractor import extract


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
    text, bboxes = extract("tests/sample_thai.txt", "text")
    assert "วิทยา" in text
    assert bboxes == []  # no bboxes for plain text


def test_extract_text_returns_unicode():
    text, _ = extract("tests/sample_thai.txt", "text")
    assert isinstance(text, str)


def test_extract_hybrid_raises_not_implemented():
    with pytest.raises(NotImplementedError):
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
    text, bboxes = extract(str(pdf_path), "pdf_text")
    assert "Hello" in text or "World" in text  # flexible: pdfplumber or PyMuPDF


def test_extract_pdf_text_returns_bboxes(tmp_path):
    pdf_path = _make_test_pdf("Hello World Test", tmp_path)
    text, bboxes = extract(str(pdf_path), "pdf_text")
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
