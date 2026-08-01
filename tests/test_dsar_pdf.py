"""Tests for the DSAR locate result PDF renderer (Track D #3, Task 3).

Same technique as tests/test_breach_pdf.py: pypdfium2 to extract text (not
pdfplumber -- see thai_pdf_text.py's docstring for why draw_text()'s dual
invisible/shaped layers corrupt pdfplumber's character-position sort), a
`requires_thai_font` skip guard, and a privacy check against fabricated
fixture values.

All PII values below are fabricated. The Thai national id is computed to pass
the real mod-11 checksum (see pii_redactor.detectors.thai_id.is_valid_thai_id)
so the FP detector actually fires on it, matching tests/test_dsar.py.
"""

from pathlib import Path

import pypdfium2 as pdfium
import pytest

from pii_redactor.dsar import locate_subject
from pii_redactor.dsar_pdf import render_dsar_pdf
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


def _matched_result(tmp_path: Path) -> dict:
    subject_file = _write(tmp_path, "subject.txt", f"{ID_A}\n{PHONE_1}\n{EMAIL_1}")
    doc = _write(
        tmp_path,
        "match.txt",
        f"นาย สมชาย ใจดี เลขบัตรประชาชน {ID_A} โทร {PHONE_1} อีเมล {EMAIL_1} "
        "เป็นโรคเบาหวานและเข้ารับการรักษาต่อเนื่อง",
    )
    result = locate_subject([str(doc)], str(subject_file))

    # Positive: the fixture actually matched on all three identifier types,
    # so the absence checks below cannot pass simply because nothing matched.
    assert len(result.matched_files) == 1
    row = result.matched_files[0]
    assert row.matched_identifier_counts["THAI_ID"] == 1
    assert row.matched_identifier_counts["PHONE"] == 1
    assert row.matched_identifier_counts["EMAIL"] == 1
    assert row.third_party_possible is True  # NAME is in the file but not the subject
    return result.to_json_dict()


def test_returns_pdf_magic_bytes(tmp_path):
    out = tmp_path / "result.pdf"
    render_dsar_pdf(_matched_result(tmp_path), out)
    assert out.read_bytes()[:5] == b"%PDF-"


@requires_thai_font
def test_pdf_shows_whitelisted_thai_labels_and_counts(tmp_path):
    payload = _matched_result(tmp_path)
    out = tmp_path / "result.pdf"
    render_dsar_pdf(payload, out)

    text = _text_of(out.read_bytes())
    assert "ผลการค้นหาไฟล์" in text
    assert "มาตรา 30" in text
    assert "match.txt" in text
    assert "เลขบัตรประชาชน" in text  # THAI_ID mapped via shared _TYPE_LABELS
    assert "เบอร์โทรศัพท์" in text
    assert "อีเมล" in text
    assert "อาจมีข้อมูลของบุคคลอื่นปะปน" in text  # third_party_possible flag
    assert "ครั้ง" in text  # M5: matched-identifier count spelled out as occurrences
    # The method statements are drawn verbatim (word-wrapped for layout), so
    # check a substring that word-wrap keeps on one line rather than the full
    # paragraph.
    assert "same normalization breach.py uses" in text
    assert "known Track A limitation" in text
    assert "heuristic" in text  # M6: third_party note states it's heuristic
    assert payload["environment"]["product_version"] in text


@requires_thai_font
def test_pdf_carries_no_subject_or_document_value_or_input_path(tmp_path):
    payload = _matched_result(tmp_path)
    out = tmp_path / "result.pdf"
    render_dsar_pdf(payload, out)

    text = _text_of(out.read_bytes())
    for secret in (ID_A, PHONE_1, EMAIL_1, "สมชาย", "ใจดี", "เบาหวาน"):
        assert secret not in text, f"DSAR PDF leaked {secret!r}"
    # No 13-digit run of any national id either, spaced/hyphenated or not.
    assert ID_A not in text.replace(" ", "").replace("-", "")
    # Neither backslash spelling of the input directory path leaks.
    assert str(tmp_path) not in text
    assert str(tmp_path).replace("\\", "\\\\") not in text


@requires_thai_font
def test_weak_only_match_renders_the_weak_marker_and_note(tmp_path):
    """F2: a NAME-only match must render differently from an id-backed one --
    the row's weak marker and the fixed name_weak_match statement both appear."""
    subject_file = _write(tmp_path, "subject.txt", "สมชาย ใจดี")
    doc = _write(tmp_path, "weak.txt", "นาย สมชาย ใจดี เดินทางไปทำงาน")

    result = locate_subject([str(doc)], str(subject_file))
    assert len(result.matched_files) == 1
    row = result.matched_files[0]
    assert row.weak_only is True
    payload = result.to_json_dict()

    out = tmp_path / "result.pdf"
    render_dsar_pdf(payload, out)
    text = _text_of(out.read_bytes())
    assert "ตรงกันเฉพาะชื่อ" in text
    # method.name_weak_match drawn verbatim -- picked because word-wrap (see
    # dsar_pdf._wrap) keeps this substring on one line, unlike "weak\nidentifier".
    assert "needs human confirmation before the file is treated as" in text


@requires_thai_font
def test_id_backed_match_does_not_render_the_weak_marker(tmp_path):
    payload = _matched_result(tmp_path)  # matches on THAI_ID/PHONE/EMAIL
    row = payload["matched_files"][0]
    assert row["weak_only"] is False

    out = tmp_path / "result.pdf"
    render_dsar_pdf(payload, out)
    text = _text_of(out.read_bytes())
    assert "ตรงกันเฉพาะชื่อ" not in text
    assert "มีตัวระบุที่เข้มกว่าชื่อร่วมด้วย" in text


@requires_thai_font
def test_zero_match_result_renders_the_plain_no_match_statement(tmp_path):
    subject_file = _write(tmp_path, "subject.txt", ID_A)
    other_id = "1101200012345"
    other = _write(tmp_path, "other.txt", f"เลขบัตรประชาชน {other_id}")

    result = locate_subject([str(other)], str(subject_file))
    assert result.matched_files == []
    payload = result.to_json_dict()

    out = tmp_path / "result.pdf"
    render_dsar_pdf(payload, out)
    text = _text_of(out.read_bytes())
    assert "ไม่พบไฟล์ที่ตรงกับผู้ขอข้อมูล" in text
    assert ID_A not in text
    assert other_id not in text


def test_failed_file_row_shows_basename_and_reason_only(tmp_path):
    subject_file = _write(tmp_path, "subject.txt", ID_A)
    good = _write(tmp_path, "good.txt", f"เลขบัตรประชาชน {ID_A}")
    missing_name = "missing.txt"

    result = locate_subject([str(good), str(tmp_path / missing_name)], str(subject_file))
    payload = result.to_json_dict()

    failed = payload["files"]["failed"]
    assert len(failed) == 1
    assert failed[0]["basename"] == missing_name
    assert "FileNotFoundError" in failed[0]["reason"]
    assert str(tmp_path) not in failed[0]["reason"]


@requires_thai_font
def test_failed_file_row_renders_in_pdf(tmp_path):
    subject_file = _write(tmp_path, "subject.txt", ID_A)
    good = _write(tmp_path, "good.txt", f"เลขบัตรประชาชน {ID_A}")
    missing_name = "missing.txt"

    result = locate_subject([str(good), str(tmp_path / missing_name)], str(subject_file))
    payload = result.to_json_dict()

    out = tmp_path / "result.pdf"
    render_dsar_pdf(payload, out)
    text = _text_of(out.read_bytes())
    assert missing_name in text
    assert "FileNotFoundError" in text
    assert str(tmp_path) not in text


@requires_thai_font
def test_skipped_file_basenames_render_in_pdf(tmp_path):
    subject_file = _write(tmp_path, "subject.txt", ID_A)
    _write(tmp_path, "good.txt", f"เลขบัตรประชาชน {ID_A}")
    _write(tmp_path, "leak.docx", "unsupported extension")

    result = locate_subject([str(tmp_path)], str(subject_file))
    payload = result.to_json_dict()
    assert payload["files"]["skipped"]["count"] == 1

    out = tmp_path / "result.pdf"
    render_dsar_pdf(payload, out)
    text = _text_of(out.read_bytes())
    assert "leak.docx" in text


def test_oserror_propagates_on_unwritable_path(tmp_path):
    payload = _matched_result(tmp_path)
    bad_path = tmp_path / "no-such-directory" / "result.pdf"

    with pytest.raises(OSError):
        render_dsar_pdf(payload, bad_path)
    assert not bad_path.exists()
