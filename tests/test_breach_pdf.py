"""Tests for the breach assessment PDF renderer (Track D #2, Task 3).

Same technique as tests/test_report_pdf.py and the receipt PDF tests in
tests/test_receipt.py: pypdfium2 to extract text (not pdfplumber -- see those
modules' docstrings for why draw_text()'s dual invisible/shaped layers corrupt
pdfplumber's character-position sort), a `requires_thai_font` skip guard, and a
privacy check against fabricated fixture values.

All PII values below are fabricated. The Thai national id is computed to pass
the real mod-11 checksum (see pii_redactor.detectors.thai_id.is_valid_thai_id)
so the FP detector actually fires on it, matching tests/test_breach_assessment.py.
"""

from pathlib import Path

import pypdfium2 as pdfium
import pytest

from pii_redactor.breach import assess_breach
from pii_redactor.breach_pdf import render_breach_pdf
from pii_redactor.thai_pdf_text import register_thai_font

requires_thai_font = pytest.mark.skipif(
    register_thai_font() == "Helvetica",
    reason="no Thai-capable font on this machine — Thai text cannot render or extract",
)

ID_A = "1101700230708"
PHONE_1 = "0812345678"
EMAIL_1 = "somchai@example.com"


def _text_of(pdf_bytes: bytes) -> str:
    doc = pdfium.PdfDocument(pdf_bytes)
    return "\n".join(page.get_textpage().get_text_range() for page in doc)


def _write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def _assessment(tmp_path: Path) -> dict:
    _write(
        tmp_path,
        "sensitive.txt",
        f"นาย สมชาย ใจดี เลขบัตรประชาชน {ID_A} โทร {PHONE_1} อีเมล {EMAIL_1} "
        "เป็นโรคเบาหวานและเข้ารับการรักษาต่อเนื่อง",
    )
    result = assess_breach([str(tmp_path)])
    # Positive: every fixture value was actually detected, so the absence
    # checks below cannot pass simply because detection found nothing.
    assert result.type_counts["THAI_ID"]["total"] == 1
    assert result.type_counts["PHONE"]["total"] == 1
    assert result.type_counts["EMAIL"]["total"] == 1
    assert result.type_counts["NAME"]["total"] == 1
    return result.to_json_dict()


def test_returns_pdf_magic_bytes(tmp_path):
    out = tmp_path / "report.pdf"
    render_breach_pdf(_assessment(tmp_path), out)
    assert out.read_bytes()[:5] == b"%PDF-"


@requires_thai_font
def test_pdf_shows_whitelisted_thai_labels_and_counts(tmp_path):
    assessment = _assessment(tmp_path)
    out = tmp_path / "report.pdf"
    render_breach_pdf(assessment, out)

    text = _text_of(out.read_bytes())
    assert "รายงานประเมินผลกระทบ" in text
    assert "มาตรา 37(4)" in text
    assert "เลขบัตรประชาชน" in text  # THAI_ID mapped via shared _TYPE_LABELS
    assert "เบอร์โทรศัพท์" in text
    assert "อีเมล" in text
    assert "HEALTH" in text  # section26 category name, not the keyword itself
    # The method statement and NAME note are drawn verbatim (word-wrapped for
    # layout), so check a substring that word-wrap keeps on one line rather
    # than the full paragraph.
    assert "subjects_min is the largest distinct-value count among the strong identifier" in text
    assert "NAME is a weak identifier" in text
    assert assessment["environment"]["product_version"] in text


@requires_thai_font
def test_pdf_carries_no_fixture_value(tmp_path):
    assessment = _assessment(tmp_path)
    out = tmp_path / "report.pdf"
    render_breach_pdf(assessment, out)

    text = _text_of(out.read_bytes())
    for secret in (ID_A, PHONE_1, EMAIL_1, "สมชาย", "ใจดี", "เบาหวาน"):
        assert secret not in text, f"breach PDF leaked {secret!r}"
    # No 13-digit run of any national id either, spaced/hyphenated or not.
    assert "1101700230708" not in text.replace(" ", "").replace("-", "")


def test_failed_file_row_shows_basename_and_reason_only(tmp_path):
    """`missing.txt` is never created, so `extract()` raises a REAL
    FileNotFoundError -- CPython's `OSError.__str__` formats its filename via
    `repr()`, which backslash-escapes a Windows path, so the raw message
    embeds `tmp_path` in BOTH the plain single-backslash form (which
    `str(tmp_path) not in ...` alone would catch) and a doubled-backslash form
    a naive scrub misses entirely (M4: this was the exact gap the final
    whole-branch review flagged -- the plain check alone cannot fail here,
    the same way it could not have caught the original leak this branch's
    480ba08 fix closed in the sibling breach/dsar test files)."""
    good = _write(tmp_path, "good.txt", f"เลขบัตรประชาชน {ID_A}")
    missing_name = "missing.txt"

    result = assess_breach([str(good), str(tmp_path / missing_name)])
    assessment = result.to_json_dict()

    failed = assessment["files"]["failed"]
    assert len(failed) == 1
    assert failed[0]["basename"] == missing_name
    assert "FileNotFoundError" in failed[0]["reason"]
    assert str(tmp_path) not in failed[0]["reason"]
    assert str(tmp_path).replace("\\", "\\\\") not in failed[0]["reason"]
    assert tmp_path.name not in failed[0]["reason"]


@requires_thai_font
def test_failed_file_row_renders_in_pdf(tmp_path):
    """M4: the PDF is the surface a human actually reads, so the same
    doubled-backslash and bare-component checks used for the JSON reason
    above are asserted here too, not just "FileNotFoundError in text"."""
    good = _write(tmp_path, "good.txt", f"เลขบัตรประชาชน {ID_A}")
    missing_name = "missing.txt"

    result = assess_breach([str(good), str(tmp_path / missing_name)])
    assessment = result.to_json_dict()

    out = tmp_path / "report.pdf"
    render_breach_pdf(assessment, out)
    text = _text_of(out.read_bytes())
    assert missing_name in text
    assert "FileNotFoundError" in text
    assert str(tmp_path) not in text
    assert str(tmp_path).replace("\\", "\\\\") not in text
    assert tmp_path.name not in text


def test_oserror_propagates_on_unwritable_path(tmp_path):
    assessment = _assessment(tmp_path)
    bad_path = tmp_path / "no-such-directory" / "report.pdf"

    with pytest.raises(OSError):
        render_breach_pdf(assessment, bad_path)
    assert not bad_path.exists()


@requires_thai_font
def test_skipped_file_basenames_render_in_pdf(tmp_path):
    _write(tmp_path, "good.txt", f"เลขบัตรประชาชน {ID_A}")
    _write(tmp_path, "leak.docx", "unsupported extension")

    result = assess_breach([str(tmp_path)])
    assessment = result.to_json_dict()
    assert assessment["files"]["skipped"]["count"] == 1

    out = tmp_path / "report.pdf"
    render_breach_pdf(assessment, out)
    text = _text_of(out.read_bytes())
    assert "leak.docx" in text


@requires_thai_font
def test_pdf_shows_no_strong_identifiers_wording_instead_of_zero_range(tmp_path):
    _write(tmp_path, "f1.txt", "นาย สมชาย ใจดี พบกับ นาย มานะ ดีใจ")

    result = assess_breach([str(tmp_path)])
    assessment = result.to_json_dict()
    assert assessment["subjects"]["no_strong_identifiers"] is True

    out = tmp_path / "report.pdf"
    render_breach_pdf(assessment, out)
    text = _text_of(out.read_bytes())
    assert "ไม่พบตัวระบุแบบเข้ม" in text
    assert "0 ถึง 0" not in text
