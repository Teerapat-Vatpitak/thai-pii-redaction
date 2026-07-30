"""Cover the probe harness itself (benchmark/probe_document.py).

The harness exists to measure six things about a document. On
`examples/sample_document.pdf` all six come back perfect, which is exactly the
condition under which an instrument tells you nothing about itself. So most of
what is pinned here is the harness REPORTING A FAILURE: a value that never
survived extraction, a two-column page whose values come out scrambled, a type
the detector disagrees with, a value no black box landed on.

The most important test in this file is
`test_residual_verdict_ignores_the_vacuous_text_arm`. A redacted PDF from this
project is flattened to an image and has no text layer at all, so the naive
privacy check ("the value is not in the extracted text") passes for every
string in the universe. That test proves the harness still calls an uncovered
value exposed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmark.probe_document import (
    COVERAGE_FULL,
    INK_STRIP_PT,
    ExpectedValue,
    align_words,
    approx_substring_distance,
    detect_columns,
    load_expectations,
    measure_detection,
    measure_extraction,
    measure_ocr_accuracy,
    measure_order,
    probe,
)
from pii_redactor.models import Entity, WordBbox

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "examples" / "sample_document.pdf"
SAMPLE_EXPECTATIONS = ROOT / "benchmark" / "data" / "probe" / "sample_document.expected.json"


def _value(index: int, field: str, value: str, type_: str = "") -> ExpectedValue:
    return ExpectedValue(index=index, field=field, value=value, type=type_)


# ── expectations file ──────────────────────────────────────────────────────


def test_load_expectations_reads_fields_decoys_and_layout(tmp_path):
    path = tmp_path / "e.json"
    path.write_text(
        json.dumps(
            {
                "layout": "multi_column",
                "fields": [{"field": "โทร", "value": "081-234-5678", "type": "phone"}],
                "decoys": ["089-000-0000"],
            }
        ),
        encoding="utf-8",
    )
    loaded = load_expectations(path)
    assert loaded["layout"] == "multi_column"
    assert loaded["decoys"] == ["089-000-0000"]
    (only,) = loaded["values"]
    assert only.field == "โทร"
    assert only.type == "PHONE", "field types are upper-cased so they compare to detector labels"


@pytest.mark.parametrize(
    "payload",
    [
        {"decoys": []},  # no fields key at all
        {"fields": []},  # present but empty
        {"fields": [{"field": "โทร"}]},  # a field with no value
    ],
)
def test_load_expectations_rejects_an_unusable_file(tmp_path, payload):
    path = tmp_path / "e.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError):
        load_expectations(path)


# ── approximate matching (measurement 3's engine) ──────────────────────────


def test_approx_substring_distance_is_zero_for_an_exact_substring():
    distance, start, end = approx_substring_distance("081-234-5678", "โทร 081-234-5678 ครับ")
    assert distance == 0
    assert "โทร 081-234-5678 ครับ"[start:end] == "081-234-5678"


def test_approx_substring_distance_scores_a_misread_value():
    """Two OCR confusions (O for 0, Z for 2) must cost exactly two edits.

    A plain substring search reports nothing here, which is why measurement 3
    cannot reuse measurement 1's matcher.
    """
    haystack = "Tel O81-Z34-5678 ext 9"
    distance, start, end = approx_substring_distance("081-234-5678", haystack)
    assert distance == 2
    assert haystack[start:end] == "O81-Z34-5678"


# ── word/offset alignment (the geometry behind measurements 5 and 6) ───────


def test_align_words_pins_offsets_and_counts_what_it_could_not_place():
    text = "ชื่อ สมชาย ใจดี"
    words = [
        WordBbox(text="ชื่อ", page=1, x=10, y=10, width=20, height=14),
        WordBbox(text="สมชาย", page=1, x=35, y=10, width=40, height=14),
        WordBbox(text="ไม่มีในข้อความ", page=1, x=80, y=10, width=40, height=14),
        WordBbox(text="ใจดี", page=1, x=80, y=10, width=21, height=14),
    ]
    aligned, unaligned = align_words(text, words)
    assert unaligned == 1, "a word absent from the text is dropped and counted, never guessed at"
    assert [(a.start, a.end) for a in aligned] == [(0, 4), (5, 10), (11, 15)]


# ── column heuristic (measurement 2's meaningfulness gate) ─────────────────


def test_detect_columns_calls_ordinary_word_spacing_single_column():
    words = [
        WordBbox(text="ที่อยู่:", page=1, x=72, y=257, width=29, height=14),
        WordBbox(text="99", page=1, x=104, y=257, width=15, height=14),
        WordBbox(text="ถนนพหลโยธิน", page=1, x=123, y=257, width=83, height=14),
    ]
    result = detect_columns(words)
    assert result["verdict"] == "single_column"
    assert result["rows"] == 1
    assert result["max_gap_pt"] < 10


def test_detect_columns_flags_a_structural_gap_inside_a_row():
    words = [
        WordBbox(text="ชื่อ", page=1, x=72, y=100, width=30, height=14),
        WordBbox(text="วันเกิด", page=1, x=350, y=100, width=40, height=14),
    ]
    result = detect_columns(words)
    assert result["verdict"] == "multi_column_suspected"
    assert result["wide_gap_rows"] == 1


def test_detect_columns_says_so_when_there_is_no_geometry_at_all():
    result = detect_columns([])
    assert result["verdict"] == "unknown"
    assert "no word geometry" in result["reason"]


# ── measurement 1 ──────────────────────────────────────────────────────────


def test_measure_extraction_reports_a_value_that_did_not_survive():
    values = [_value(0, "โทร", "081-234-5678"), _value(1, "อีเมล", "a@example.com")]
    result = measure_extraction(values, "ติดต่อ 081-234-5678")
    assert result["found"] == 1 and result["missing"] == 1
    assert result["values"][0]["found"] is True
    assert result["values"][1]["found"] is False
    assert result["values"][1]["match"] == "none"


def test_measure_extraction_names_the_arm_that_matched_a_wrapped_value():
    """A line wrap changes the whitespace inside a value. Finding it is still a
    hit, but the report must say the exact match failed."""
    values = [_value(0, "ที่อยู่", "99 ถนนพหลโยธิน แขวงจตุจักร")]
    result = measure_extraction(values, "ที่อยู่: 99 ถนนพหลโยธิน\nแขวงจตุจักร")
    row = result["values"][0]
    assert row["found"] is True
    assert row["match"] == "whitespace_normalized"


# ── measurement 2 ──────────────────────────────────────────────────────────


def _extraction_at(offsets: list[int]) -> dict:
    return {
        "values": [
            {"index": i, "field": f"f{i}", "found": True, "start": o, "end": o + 1}
            for i, o in enumerate(offsets)
        ]
    }


def test_measure_order_refuses_to_call_a_single_column_result_a_result():
    columns = {"verdict": "single_column", "reason": "no wide gaps"}
    result = measure_order(_extraction_at([0, 10, 20]), columns, "single_column")
    assert result["inversions"] == 0
    assert result["meaningful"] is False
    assert "single column" in result["reason"]


def test_measure_order_counts_inversions_on_a_multi_column_source():
    """Placed 0,1,2,3 but extracted 0,2,1,3 -- one inversion."""
    columns = {"verdict": "multi_column_suspected", "reason": "wide gaps in 2 rows"}
    result = measure_order(_extraction_at([0, 40, 20, 60]), columns, "multi_column")
    assert result["extracted_order"] == [0, 2, 1, 3]
    assert result["inversions"] == 1
    assert result["max_inversions"] == 6
    assert result["meaningful"] is True


def test_measure_order_is_not_meaningful_with_fewer_than_two_values():
    columns = {"verdict": "multi_column_suspected", "reason": "wide gaps"}
    result = measure_order(_extraction_at([5]), columns, "multi_column")
    assert result["meaningful"] is False


# ── measurement 3 ──────────────────────────────────────────────────────────


def test_measure_ocr_accuracy_skips_a_text_layer_pdf_with_a_reason():
    result = measure_ocr_accuracy([_value(0, "โทร", "081")], "081", "pdf_text", None)
    assert result["status"] == "not_applicable"
    assert "pdf_text" in result["reason"]


def test_measure_ocr_accuracy_skips_cleanly_when_the_extra_is_missing():
    result = measure_ocr_accuracy(
        [_value(0, "โทร", "081")], "", "pdf_hybrid", "pip install -r requirements-ocr.txt"
    )
    assert result["status"] == "skipped"
    assert "requirements-ocr.txt" in result["reason"]


def test_measure_ocr_accuracy_scores_per_value_on_a_scan():
    result = measure_ocr_accuracy(
        [_value(0, "โทร", "081-234-5678"), _value(1, "อีเมล", "a@example.com")],
        "Tel O81-Z34-5678 mail a@example.com",
        "pdf_hybrid",
        None,
    )
    assert result["status"] == "measured"
    by_field = {r["field"]: r for r in result["values"]}
    assert by_field["โทร"]["edit_distance"] == 2
    assert by_field["อีเมล"]["edit_distance"] == 0
    assert by_field["อีเมล"]["char_accuracy"] == 1.0


# ── measurement 4 ──────────────────────────────────────────────────────────


def _entity(start: int, end: int, data_type: str) -> Entity:
    return Entity(
        entity_id="e",
        redact_type="FP",
        data_type=data_type,
        span=(start, end),
        score=1.0,
        original_text="",
    )


def test_measure_detection_reports_a_hit_with_the_wrong_type_as_a_mismatch():
    values = [_value(0, "เลขบัญชี", "1234567890", "BANK_ACCOUNT")]
    extraction = {"values": [{"index": 0, "found": True, "start": 0, "end": 10}]}
    result = measure_detection(values, extraction, [_entity(0, 10, "ID_NUMBER")])
    row = result["values"][0]
    assert row["detected"] is True
    assert row["type_match"] is False
    assert row["detected_types"] == ["ID_NUMBER"]
    assert result["type_matches"] == 0 and result["scored"] == 1


def test_measure_detection_reports_but_never_scores_a_type_outside_the_11():
    values = [_value(0, "หน่วยงาน", "กรมการปกครอง", "ORGANIZATION")]
    extraction = {"values": [{"index": 0, "found": True, "start": 0, "end": 12}]}
    result = measure_detection(values, extraction, [_entity(0, 12, "ORGANIZATION")])
    row = result["values"][0]
    assert row["status"] == "out_of_scheme"
    assert row["type_match"] is None, "a type the guidelines do not define cannot be right or wrong"
    assert result["scored"] == 0 and result["out_of_scheme"] == 1


def test_measure_detection_reports_a_partial_span_as_partial_coverage():
    values = [_value(0, "ที่อยู่", "99 ถนนพหลโยธิน", "ADDRESS")]
    extraction = {"values": [{"index": 0, "found": True, "start": 0, "end": 14}]}
    result = measure_detection(values, extraction, [_entity(3, 14, "ADDRESS")])
    row = result["values"][0]
    assert row["type_match"] is True
    assert row["char_coverage"] == pytest.approx(11 / 14, abs=1e-4)


def test_measure_detection_carries_a_missing_value_through_as_not_in_text():
    values = [_value(0, "โทร", "081-234-5678", "PHONE")]
    extraction = {"values": [{"index": 0, "found": False, "start": None, "end": None}]}
    result = measure_detection(values, extraction, [])
    assert result["values"][0]["status"] == "not_in_text"
    assert result["detected"] == 0


# ── end to end ─────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def sample_result():
    pytest.importorskip("numpy")
    if not SAMPLE.exists():
        pytest.skip("examples/sample_document.pdf not present")
    return probe(SAMPLE, load_expectations(SAMPLE_EXPECTATIONS))


def test_probe_reports_all_six_measurements_on_the_sample_document(sample_result):
    """The committed sample is single-column prose whose PII the product already
    handles, so five of six come back perfect. Pinned so a regression in any of
    them is loud -- and so the two honest non-results stay non-results."""
    r = sample_result
    assert r["source_type"] == "pdf_text"

    assert r["extraction"]["found"] == 6 and r["extraction"]["missing"] == 0
    assert r["order"]["inversions"] == 0
    assert r["order"]["meaningful"] is False  # single column: the 0 is not a result
    assert r["ocr"]["status"] == "not_applicable"
    assert r["detection"]["detected"] == 6
    assert r["detection"]["type_matches"] == 6 and r["detection"]["scored"] == 6
    assert r["coverage"]["fully_covered"] == 6
    assert r["coverage"]["mean_black_fraction"] == 1.0
    assert r["residual"]["removed"] == 6 and r["residual"]["exposed"] == 0
    assert r["decoy_control"]["false_hits"] == []


def test_sample_document_text_arm_is_reported_as_vacuous(sample_result):
    """The redacted output is flattened to an image, so its text layer is empty
    and the text-only privacy check earns nothing. The harness must say so."""
    arm = sample_result["residual"]["text_arm"]
    assert arm["text_layer_chars"] == 0
    assert arm["vacuous"] is True
    assert arm["redacted_source_type"] == "pdf_hybrid"


# --- a document the harness must fail ---------------------------------------
#
# Two columns, so the extraction order scrambles, plus one value ("WQXZ-4417")
# the detector does not flag, so no black box lands on it.

_TWO_COLUMN_FIELDS = [
    {"field": "phone_left", "value": "081-234-5678", "type": "PHONE"},
    {"field": "email_left", "value": "alice@example.com", "type": "EMAIL"},
    {"field": "phone_right", "value": "089-111-2222", "type": "PHONE"},
    {"field": "email_right", "value": "bob@example.org", "type": "EMAIL"},
    {"field": "case_marker", "value": "WQXZ-4417", "type": "STUDENT_ID"},
]


@pytest.fixture(scope="module")
def two_column_result(tmp_path_factory):
    pytest.importorskip("numpy")
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    tmp = tmp_path_factory.mktemp("probe_two_column")
    pdf = tmp / "two_column.pdf"
    c = canvas.Canvas(str(pdf), pagesize=letter)
    c.setFont("Helvetica", 12)
    top = letter[1] - 72
    c.drawString(72, top, "Contact sheet for the district office")
    # Placed column-major (left column top to bottom, then right column), but a
    # text extractor serializes row-major -- that difference is the measurement.
    c.drawString(72, top - 40, "081-234-5678")
    c.drawString(350, top - 40, "089-111-2222")
    c.drawString(72, top - 70, "alice@example.com")
    c.drawString(350, top - 70, "bob@example.org")
    c.drawString(72, top - 110, "Reference marker WQXZ-4417 printed in the footer")
    c.save()

    expectations = {"layout": "multi_column", "fields": _TWO_COLUMN_FIELDS, "decoys": []}
    path = tmp / "expected.json"
    path.write_text(json.dumps(expectations, ensure_ascii=False), encoding="utf-8")
    return probe(pdf, load_expectations(path))


def test_probe_counts_inversions_when_a_two_column_page_serializes_row_major(two_column_result):
    order = two_column_result["order"]
    assert order["columns"]["verdict"] == "multi_column_suspected"
    assert order["meaningful"] is True
    assert order["extracted_order"] == [0, 2, 1, 3, 4]
    assert order["inversions"] == 1


def test_probe_reports_the_undetected_value_as_undetected(two_column_result):
    by_field = {r["field"]: r for r in two_column_result["detection"]["values"]}
    assert by_field["phone_left"]["type_match"] is True
    marker = by_field["case_marker"]
    assert marker["detected"] is False
    assert marker["type_match"] is False
    assert marker["char_coverage"] == 0.0


def test_residual_verdict_ignores_the_vacuous_text_arm(two_column_result):
    """THE trap test.

    "WQXZ-4417" is in the document, no black box was painted over it, and it is
    still perfectly readable in the redacted render. A text-only privacy check
    reports it as gone, because the flattened output has no text layer for any
    string to be found in. The harness must call it exposed anyway.
    """
    assert two_column_result["residual"]["text_arm"]["vacuous"] is True

    by_field = {r["field"]: r for r in two_column_result["residual"]["values"]}
    marker = by_field["case_marker"]
    assert marker["text_arm_survives"] is False, "the naive check finds nothing -- vacuously"
    assert marker["verdict"] == "exposed", "the pixel arm must overrule it"

    coverage = {r["field"]: r for r in two_column_result["coverage"]["values"]}
    assert coverage["case_marker"]["black_fraction"] < COVERAGE_FULL
    assert coverage["case_marker"]["fully_covered"] is False
    # The detected values on the same page did get covered, so this is a
    # property of that value and not of a broken redaction run.
    assert coverage["phone_left"]["fully_covered"] is True


def test_decoy_control_catches_a_decoy_that_is_actually_present(tmp_path):
    """The negative control must be able to fire, or it is decoration."""
    if not SAMPLE.exists():
        pytest.skip("examples/sample_document.pdf not present")
    expectations = load_expectations(SAMPLE_EXPECTATIONS)
    expectations["decoys"] = ["081-234-5678"]  # actually IS in the sample
    result = probe(SAMPLE, expectations)
    assert result["decoy_control"]["false_hits"] == ["081-234-5678"]


def test_ink_strip_never_exceeds_the_redactors_top_pad():
    """The strip inspects the zone the redaction box's own pad owns. Taller
    than the pad and it reads the legitimate line above on tight leading;
    shorter and it misses a box painted short or in the wrong space."""
    from pii_redactor.redactor import REDACT_PAD_TOP_PT

    assert INK_STRIP_PT == REDACT_PAD_TOP_PT


def test_fully_covered_value_on_tight_leading_is_not_reported_exposed(tmp_path):
    """12pt text at 14pt leading — dense-form spacing. The unredacted line
    directly above the value must not read as ink leaking from the box."""
    pytest.importorskip("numpy")
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    pdf = tmp_path / "tight_leading.pdf"
    c = canvas.Canvas(str(pdf), pagesize=letter)
    c.setFont("Helvetica", 12)
    top = letter[1] - 72
    c.drawString(72, top, "Contact the duty officer directly for anything urgent")
    c.drawString(72, top - 14, "081-234-5678")
    c.save()

    spec = tmp_path / "expected.json"
    spec.write_text(
        json.dumps(
            {
                "layout": "linear",
                "fields": [{"field": "phone", "value": "081-234-5678", "type": "PHONE"}],
                "decoys": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = probe(pdf, load_expectations(spec))
    row = result["residual"]["values"][0]
    assert result["coverage"]["values"][0]["fully_covered"] is True
    assert row["verdict"] == "removed", row["reason"]
    assert result["residual"]["exposed"] == 0
