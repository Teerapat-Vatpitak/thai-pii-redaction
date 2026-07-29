"""Tests for the PDPA report PDF renderer (feature D).

The renderer's contract: whitelist-only fields (scores/grades/counts/category
names), never raw text or entity values — the PII-free property is structural
(the function is never handed PII) but pinned here anyway via text extraction.
"""

import pypdfium2 as pdfium
import pytest

from pii_redactor.report_pdf import render_pdpa_report
from pii_redactor.thai_pdf_text import register_thai_font

requires_thai_font = pytest.mark.skipif(
    register_thai_font() == "Helvetica",
    reason="no Thai-capable font on this machine — Thai text cannot render or extract",
)

ANALYSIS = {
    "overall_score": 72.0,
    "overall_grade": "D",
    "risk_label": "High Risk",
    "direct_pii_count": 3,
    "fp_count": 2,
    "tb_count": 1,
    "section26": [{"category": "health", "keyword": "แพ้ยา"}],
    "reid": {
        "score": 85.0,
        "grade": "F",
        "qi_found": ["gender", "district", "date_of_birth"],
        "high_risk_combo": True,
    },
    "breakdown": [
        {"data_type": "THAI_ID", "redact_type": "FP", "count": 1},
        {"data_type": "NAME", "redact_type": "TB", "count": 2},
    ],
    "recommendations": [
        {
            "level": "high",
            "title": "Remove or pseudonymize 3 direct PII entities",
            "desc": "ใช้ AI Guard เพื่อปกปิดข้อมูลทั้งหมดก่อนส่งให้ AI ภายนอก",
        },
    ],
}


def _text_of(pdf_bytes: bytes) -> str:
    # pypdfium2, not pdfplumber: draw_text() (pii_redactor/thai_pdf_text.py) draws
    # an invisible real-character layer plus the visible shaped glyphs on affected
    # lines. pdfminer/pdfplumber discards text render mode entirely at the LTChar
    # layer and re-sorts characters by x-position, so it interleaves the two
    # near-identical-position layers character-by-character ("AAIIGGuuaarrdd"),
    # corrupting every substring check. pypdfium2 preserves paint order instead,
    # so the two layers extract sequentially and the original text stays intact
    # as a contiguous substring -- the same library test_thai_shaping.py uses to
    # verify draw_text() output for the same reason.
    doc = pdfium.PdfDocument(pdf_bytes)
    return "\n".join(page.get_textpage().get_text_range() for page in doc)


def test_returns_pdf_magic_bytes():
    pdf = render_pdpa_report(ANALYSIS, version="2.3.0", source_sha256_12="abc123def456")
    assert pdf[:5] == b"%PDF-"


@requires_thai_font
def test_report_carries_scores_headings_and_thai_labels():
    pdf = render_pdpa_report(
        ANALYSIS,
        version="2.3.0",
        source_sha256_12="abc123def456",
        generated_at="2026-07-21 21:00",
    )
    text = _text_of(pdf)
    assert "รายงานความเสี่ยง" in text
    assert "72" in text and "เกรด D" in text
    assert "เลขบัตรประชาชน" in text  # THAI_ID mapped to a Thai label
    assert "ชื่อบุคคล" in text
    assert "มาตรา 26" in text and "health" in text
    assert "abc123def456" in text  # source hash traceability
    assert "2026-07-21 21:00" in text
    assert "ข้อจำกัด" in text  # limitations block present


@requires_thai_font
def test_report_never_renders_keyword_excerpts():
    # section26 entries carry a "keyword" field — the renderer must not draw it
    pdf = render_pdpa_report(ANALYSIS, version="2.3.0", source_sha256_12="abc123def456")
    assert "แพ้ยา" not in _text_of(pdf)


@requires_thai_font
def test_empty_findings_render_gracefully():
    empty = {
        **ANALYSIS,
        "breakdown": [],
        "section26": [],
        "reid": {"score": 0.0, "grade": "A", "qi_found": [], "high_risk_combo": False},
        "recommendations": [
            {
                "level": "info",
                "title": "No significant PDPA risk detected",
                "desc": "ไม่พบข้อมูลส่วนบุคคลที่มีความเสี่ยงสูงในข้อความนี้",
            },
        ],
    }
    pdf = render_pdpa_report(empty, version="2.3.0", source_sha256_12="abc123def456")
    assert "ไม่พบ" in _text_of(pdf)
