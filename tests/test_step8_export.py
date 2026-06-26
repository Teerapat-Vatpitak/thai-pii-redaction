"""Tests for Step 8 exporter module."""

import pytest
from pathlib import Path

from pii_redactor.exporter import export, ExportResult, ExportError
from pii_redactor.models import ReverseResult, EntityRegistry
from pii_redactor.output_validator import ValidationResult


def _make_validation_result(halt: bool = False, l2_ok: bool = True) -> ValidationResult:
    """Create a ValidationResult for testing."""
    return ValidationResult(
        passed=not halt and l2_ok,
        layer1_pii_clean=True,
        layer2_completeness_ok=l2_ok,
        layer3_integrity_ok=not halt,
        flags=[] if l2_ok else ["incomplete_reverse:0/1"],
        halt=halt,
    )


def _make_reverse_result(text: str = "Final output text.") -> ReverseResult:
    """Create a ReverseResult for testing."""
    return ReverseResult(
        text=text,
        flags=[],
        audit_summary={"total_entities": 0, "replaced_count": 0},
    )


def test_export_txt_creates_file(tmp_path):
    """Test that export() creates a text file."""
    rr = _make_reverse_result("Hello world.")
    vr = _make_validation_result()
    out = str(tmp_path / "output.txt")
    result = export(rr, vr, out, fmt="txt")
    assert result.output_path.exists()
    assert result.format == "txt"
    assert result.byte_size > 0


def test_export_txt_content_correct(tmp_path):
    """Test that exported text content is correct."""
    text = "สวัสดี ครับ นี่คือข้อความทดสอบ"
    rr = _make_reverse_result(text)
    vr = _make_validation_result()
    out = str(tmp_path / "output.txt")
    result = export(rr, vr, out, fmt="txt")
    written = result.output_path.read_text(encoding="utf-8")
    assert written == text


def test_export_returns_export_result(tmp_path):
    """Test that export() returns ExportResult dataclass."""
    rr = _make_reverse_result()
    vr = _make_validation_result()
    out = str(tmp_path / "output.txt")
    result = export(rr, vr, out)
    assert isinstance(result, ExportResult)
    assert isinstance(result.output_path, Path)
    assert isinstance(result.byte_size, int)
    assert isinstance(result.warnings, list)


def test_export_halt_raises_export_error(tmp_path):
    """Test that halt=True raises ExportError."""
    rr = _make_reverse_result()
    vr = _make_validation_result(halt=True)
    out = str(tmp_path / "output.txt")
    with pytest.raises(ExportError, match="halt"):
        export(rr, vr, out, fmt="txt")


def test_export_unsupported_format_raises(tmp_path):
    """Test that unsupported format raises ExportError."""
    rr = _make_reverse_result()
    vr = _make_validation_result()
    out = str(tmp_path / "output.json")
    with pytest.raises(ExportError, match="Unsupported format"):
        export(rr, vr, out, fmt="json")


def test_export_no_overwrite_raises_when_exists(tmp_path):
    """Test that existing file without overwrite raises ExportError."""
    rr = _make_reverse_result()
    vr = _make_validation_result()
    out = tmp_path / "output.txt"
    out.write_text("existing")
    with pytest.raises(ExportError, match="already exists"):
        export(rr, vr, str(out), fmt="txt", overwrite=False)


def test_export_overwrite_replaces_file(tmp_path):
    """Test that overwrite=True replaces existing file."""
    rr = _make_reverse_result("new content")
    vr = _make_validation_result()
    out = tmp_path / "output.txt"
    out.write_text("old content")
    result = export(rr, vr, str(out), fmt="txt", overwrite=True)
    assert result.output_path.read_text(encoding="utf-8") == "new content"


def test_export_pdf_text_creates_pdf(tmp_path):
    """Test that export() with pdf_text format creates a valid PDF."""
    rr = _make_reverse_result("PDF content here.")
    vr = _make_validation_result()
    out = str(tmp_path / "output.pdf")
    result = export(rr, vr, out, fmt="pdf_text")
    assert result.output_path.exists()
    assert result.byte_size > 0
    # Verify it's a PDF (starts with %PDF)
    content = result.output_path.read_bytes()
    assert content[:4] == b"%PDF"


def test_export_layer2_warning_in_result(tmp_path):
    """Test that layer2 completeness issues are collected as warnings."""
    rr = _make_reverse_result()
    vr = _make_validation_result(l2_ok=False)
    out = str(tmp_path / "output.txt")
    result = export(rr, vr, out, fmt="txt")
    # Should contain layer2 warning but not raise
    assert len(result.warnings) > 0


def test_export_txt_with_multiline(tmp_path):
    """Test that multiline text is preserved correctly in txt export."""
    text = "Line 1\nLine 2\nLine 3"
    rr = _make_reverse_result(text)
    vr = _make_validation_result()
    out = str(tmp_path / "output.txt")
    result = export(rr, vr, out, fmt="txt")
    written = result.output_path.read_text(encoding="utf-8")
    assert written == text


def test_export_pdf_text_with_multiline(tmp_path):
    """Test that multiline text is handled in pdf_text export."""
    text = "Line 1\nLine 2\nLine 3"
    rr = _make_reverse_result(text)
    vr = _make_validation_result()
    out = str(tmp_path / "output.pdf")
    result = export(rr, vr, out, fmt="pdf_text")
    assert result.output_path.exists()
    content = result.output_path.read_bytes()
    assert content[:4] == b"%PDF"


def test_export_creates_parent_directories(tmp_path):
    """Test that export() creates parent directories as needed."""
    rr = _make_reverse_result("test")
    vr = _make_validation_result()
    out = str(tmp_path / "subdir" / "another" / "output.txt")
    result = export(rr, vr, out, fmt="txt")
    assert result.output_path.exists()
    assert result.output_path.parent.exists()
