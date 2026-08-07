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
    _measure_render_ocr_text,
    _measure_source_ocr,
    _ocr_origin_text,
    align_words,
    approx_substring_distance,
    detect_columns,
    load_expectations,
    measure_detection,
    measure_extraction,
    measure_ocr_accuracy,
    measure_order,
    measure_privacy_alignment,
    probe,
    render_report,
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
                "fields": [
                    {
                        "field": "โทร",
                        "value": "081-234-5678",
                        "type": "phone",
                        "region": {
                            "page": 1,
                            "x": 10,
                            "y": 20,
                            "width": 30,
                            "height": 12,
                        },
                    }
                ],
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
    assert only.region == {
        "page": 1,
        "x": 10.0,
        "y": 20.0,
        "width": 30.0,
        "height": 12.0,
    }


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
        WordBbox(text="ชื่อ", page=1, x=10, y=10, width=20, height=14, source_span=(0, 4)),
        WordBbox(text="สมชาย", page=1, x=35, y=10, width=40, height=14, source_span=(5, 10)),
        WordBbox(
            text="ไม่มีในข้อความ",
            page=1,
            x=80,
            y=10,
            width=40,
            height=14,
            source_span=None,
        ),
        WordBbox(text="ใจดี", page=1, x=80, y=10, width=21, height=14, source_span=(11, 15)),
    ]
    aligned, unaligned = align_words(text, words)
    assert unaligned == 1, "a box without provenance is dropped and counted, never guessed at"
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


def test_measure_extraction_does_not_reuse_one_span_for_duplicate_values():
    value = "1312271505581"
    values = [
        _value(0, "เลขบัตร 1", value, "THAI_ID"),
        _value(1, "เลขบัตร 2", value, "THAI_ID"),
    ]

    result = measure_extraction(values, value)

    assert [row["found"] for row in result["values"]] == [True, False]


def test_measure_extraction_uses_two_spans_for_two_duplicate_values():
    value = "1312271505581"
    values = [
        _value(0, "เลขบัตร 1", value, "THAI_ID"),
        _value(1, "เลขบัตร 2", value, "THAI_ID"),
    ]

    result = measure_extraction(values, f"{value} {value}")

    assert [(row["start"], row["end"]) for row in result["values"]] == [
        (0, len(value)),
        (len(value) + 1, len(value) * 2 + 1),
    ]


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


def test_ocr_accuracy_uses_only_ocr_origin_text_on_a_mixed_page():
    text = "1312271505581\n13I227I50558I"
    meta = {"ocr_text_ranges": [(14, len(text))]}

    assert _ocr_origin_text(text, meta) == "13I227I50558I"


def test_mixed_page_ocr_alignment_maps_back_to_full_text():
    layer = "selectable layer"
    ocr_text = "13I227I50558I"
    full_text = f"{layer}\n{ocr_text}"
    result = _measure_source_ocr(
        [_value(0, "เลขบัตร", "1312271505581", "THAI_ID")],
        full_text,
        "pdf_hybrid",
        None,
        {"ocr_text_ranges": [(len(layer) + 1, len(full_text))]},
    )

    row = result["values"][0]
    assert row["status"] == "measured"
    assert row["start"] == len(layer) + 1
    assert full_text[row["start"] : row["end"]] == ocr_text[: row["end"] - row["start"]]


def test_mixed_page_ocr_accuracy_keeps_a_deduped_observation():
    phone = "081-234-5678"
    canonical = f"{phone}\nโทร"
    result = _measure_source_ocr(
        [_value(0, "phone", phone, "PHONE")],
        canonical,
        "pdf_hybrid",
        None,
        {
            "ocr_text_ranges": [(len(phone) + 1, len(canonical))],
            "ocr_observations": [f"โทร {phone}"],
        },
    )

    row = result["values"][0]
    assert row["char_accuracy"] == 1.0
    assert row["source_alignment"] == "observation_only"
    assert "start" not in row


def test_render_ocr_uses_one_range_for_similar_values():
    first = "1312271505581"
    second = "1312271506581"
    result = _measure_render_ocr_text(
        [
            _value(0, "เลขบัตร 1", first, "THAI_ID"),
            _value(1, "เลขบัตร 2", second, "THAI_ID"),
        ],
        first,
    )

    assert result["status"] == "measured"
    assert result["surviving"] == 1
    assert [row["survives"] for row in result["values"]] == [True, False]


def test_ocr_alignment_range_cannot_be_reused_by_a_similar_value():
    first = "1312271505581"
    second = "1312271506581"
    values = [
        _value(0, "เลขบัตร 1", first, "THAI_ID"),
        _value(1, "เลขบัตร 2", second, "THAI_ID"),
    ]

    ocr = measure_ocr_accuracy(values, first, "pdf_hybrid", None)
    extraction = measure_extraction(values, first)
    detection = measure_detection(values, extraction, [_entity(0, 13, "THAI_ID")], ocr)

    assert ocr["values"][0]["status"] == "measured"
    assert ocr["values"][1]["status"] == "alignment_conflict"
    assert detection["values"][1]["status"] == "not_in_text"
    assert detection["values"][1]["alignment"] is None


def test_detection_rejects_duplicate_exact_alignments_from_external_input():
    value = "1312271505581"
    values = [
        _value(0, "เลขบัตร 1", value, "THAI_ID"),
        _value(1, "เลขบัตร 2", value, "THAI_ID"),
    ]
    extraction = {
        "values": [
            {"index": 0, "found": True, "start": 0, "end": len(value), "match": "exact"},
            {"index": 1, "found": True, "start": 0, "end": len(value), "match": "exact"},
        ]
    }

    detection = measure_detection(values, extraction, [_entity(0, len(value), "THAI_ID")])

    assert detection["values"][0]["detected"] is True
    assert detection["values"][1]["status"] == "not_in_text"
    assert detection["values"][1]["alignment"] is None


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


def test_measure_detection_rejects_a_weak_ocr_alignment():
    values = [_value(0, "เลขบัตร", "1312271505581", "THAI_ID")]
    extraction = {"values": [{"index": 0, "found": False, "start": None, "end": None}]}
    ocr = {
        "values": [
            {
                "index": 0,
                "status": "measured",
                "start": 0,
                "end": 13,
                "char_accuracy": 0.79,
            }
        ]
    }

    result = measure_detection(values, extraction, [_entity(0, 13, "THAI_ID")], ocr)

    assert result["values"][0]["status"] == "not_in_text"
    assert result["values"][0]["alignment"] is None


def test_privacy_alignment_accepts_a_unique_close_ocr_match():
    value = _value(0, "เลขบัตร", "1312271505581", "THAI_ID")
    extraction = {"values": [{"index": 0, "field": value.field, "found": False}]}
    ocr = {
        "values": [
            {
                "index": 0,
                "status": "measured",
                "start": 3,
                "end": 16,
                "char_accuracy": 0.92,
            }
        ]
    }

    result = measure_privacy_alignment([value], extraction, ocr)

    assert result["aligned"] == 1
    assert result["values"][0]["alignment"] == "ocr_approximate"


def test_privacy_alignment_uses_a_fixture_region_without_text_alignment():
    value = ExpectedValue(
        index=0,
        field="marker",
        value="WQXY-4417",
        type="STUDENT_ID",
        region={"page": 1, "x": 72.0, "y": 170.0, "width": 70.0, "height": 18.0},
    )
    extraction = {"values": [{"index": 0, "field": value.field, "found": False}]}

    result = measure_privacy_alignment([value], extraction, None)

    assert result["aligned"] == 1
    assert result["values"][0]["alignment"] == "ground_truth_region"


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


def test_report_shows_safe_render_ocr_summary(sample_result):
    report = render_report(sample_result)

    assert "supporting render OCR:" in report


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


def test_render_ocr_overrides_a_fully_black_bbox(tmp_path, monkeypatch):
    pytest.importorskip("numpy")
    pytest.importorskip("pypdfium2")

    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    from pii_redactor.ingest import ocr_processor

    phone = "081-234-5678"
    pdf = tmp_path / "phone.pdf"
    c = canvas.Canvas(str(pdf), pagesize=letter)
    c.drawString(72, letter[1] - 72, phone)
    c.save()

    monkeypatch.setattr(ocr_processor, "is_available", lambda: True)
    monkeypatch.setattr(
        ocr_processor,
        "ocr_page",
        lambda page, page_num, **kw: ocr_processor.OCRPageResult(
            words=[WordBbox(text=phone, page=page_num, x=72, y=72, width=78, height=12)],
            text=phone,
            confidence=0.95,
            attempts=1,
            human_review=False,
        ),
    )

    result = probe(
        pdf,
        {
            "layout": "single_column",
            "values": [_value(0, "phone", phone, "PHONE")],
            "decoys": [],
        },
    )

    assert result["coverage"]["values"][0]["fully_covered"] is True
    assert result["residual"]["render_ocr"]["surviving"] == 1
    assert result["residual"]["values"][0]["verdict"] == "exposed"


def test_fixture_region_turns_a_missing_value_into_exposed(tmp_path):
    pytest.importorskip("numpy")

    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    pdf = tmp_path / "marker.pdf"
    c = canvas.Canvas(str(pdf), pagesize=letter)
    c.setFont("Helvetica", 12)
    c.drawString(72, letter[1] - 182, "WQXZ-4417")
    c.save()

    result = probe(
        pdf,
        {
            "layout": "single_column",
            "values": [
                ExpectedValue(
                    index=0,
                    field="marker",
                    value="WQXY-4417",
                    type="STUDENT_ID",
                    region={
                        "page": 1,
                        "x": 72.0,
                        "y": 170.0,
                        "width": 70.0,
                        "height": 18.0,
                    },
                )
            ],
            "decoys": [],
        },
    )

    assert result["extraction"]["missing"] == 1
    assert result["coverage"]["values"][0]["alignment"] == "ground_truth_region"
    assert result["residual"]["values"][0]["verdict"] == "exposed"


def test_fixture_region_overrides_a_shifted_ocr_box(tmp_path, monkeypatch):
    pytest.importorskip("numpy")
    pytest.importorskip("pypdfium2")

    from PIL import Image, ImageDraw
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    from pii_redactor.ingest import ocr_processor

    phone = "081-234-5678"
    image = Image.new("RGB", (612, 792), "white")
    ImageDraw.Draw(image).text((72, 72), phone, fill="black")
    pdf = tmp_path / "shifted-ocr.pdf"
    c = canvas.Canvas(str(pdf), pagesize=letter)
    c.drawImage(ImageReader(image), 0, 0, width=letter[0], height=letter[1])
    c.save()

    source_words = [WordBbox(text=phone, page=1, x=300, y=300, width=90, height=14)]
    ocr_results = iter(
        [
            ocr_processor.OCRPageResult(
                words=source_words,
                text=phone,
                confidence=0.95,
                attempts=1,
                human_review=False,
            ),
            ocr_processor.OCRPageResult(
                words=[],
                text="",
                confidence=0.95,
                attempts=1,
                human_review=False,
            ),
        ]
    )
    monkeypatch.setattr(ocr_processor, "is_available", lambda: True)
    monkeypatch.setattr(
        ocr_processor,
        "ocr_page",
        lambda page, page_num, **kw: next(ocr_results),
    )

    result = probe(
        pdf,
        {
            "layout": "single_column",
            "values": [
                ExpectedValue(
                    index=0,
                    field="phone",
                    value=phone,
                    type="PHONE",
                    region={
                        "page": 1,
                        "x": 70.0,
                        "y": 68.0,
                        "width": 100.0,
                        "height": 22.0,
                    },
                )
            ],
            "decoys": [],
        },
    )

    coverage = result["coverage"]["values"][0]
    assert coverage["alignment"] == "ground_truth_region"
    assert coverage["fully_covered"] is False
    assert result["residual"]["values"][0]["verdict"] == "exposed"


def test_probe_measures_hybrid_redaction_with_ocr_boxes(tmp_path, monkeypatch):
    """A scanned page has real OCR geometry, so measurements 5 and 6 must run."""
    pytest.importorskip("numpy")
    pytest.importorskip("pypdfium2")

    from PIL import Image, ImageDraw
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    from pii_redactor.ingest import ocr_processor

    phone = "081-234-5678"
    marker = "WQXZ-4417"
    image = Image.new("RGB", (612, 792), "white")
    draw = ImageDraw.Draw(image)
    draw.text((72, 72), phone, fill="black")
    draw.text((72, 110), marker, fill="black")

    scanned = tmp_path / "scanned.pdf"
    c = canvas.Canvas(str(scanned), pagesize=letter)
    c.drawImage(ImageReader(image), 0, 0, width=letter[0], height=letter[1])
    c.save()

    words = [
        WordBbox(text=phone, page=1, x=72, y=72, width=78, height=12),
        WordBbox(text=marker, page=1, x=72, y=110, width=66, height=12),
    ]
    ocr_results = iter(
        [
            ocr_processor.OCRPageResult(
                words=words,
                text=f"{phone}\n{marker}",
                confidence=0.95,
                attempts=1,
                human_review=False,
            ),
            ocr_processor.OCRPageResult(
                words=[WordBbox(text=marker, page=1, x=72, y=110, width=66, height=12)],
                text=marker,
                confidence=0.95,
                attempts=1,
                human_review=False,
            ),
        ]
    )
    monkeypatch.setattr(ocr_processor, "is_available", lambda: True)
    monkeypatch.setattr(
        ocr_processor,
        "ocr_page",
        lambda page, page_num, **kw: next(ocr_results),
    )

    expected = {
        "layout": "single_column",
        "values": [
            _value(0, "phone", phone, "PHONE"),
            _value(1, "marker", marker, "STUDENT_ID"),
        ],
        "decoys": [],
    }
    result = probe(scanned, expected)

    assert result["source_type"] == "pdf_hybrid"
    assert result["coverage"]["status"] == "measured"
    assert result["residual"]["status"] == "measured"
    by_field = {row["field"]: row for row in result["residual"]["values"]}
    assert by_field["phone"]["verdict"] == "removed"
    assert by_field["marker"]["verdict"] == "exposed"


def test_probe_uses_close_ocr_match_to_measure_a_misread_id(tmp_path, monkeypatch):
    pytest.importorskip("numpy")
    pytest.importorskip("pypdfium2")

    from PIL import Image, ImageDraw
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    from pii_redactor.ingest import ocr_processor

    expected_id = "1312271505581"
    ocr_id = "1312271506581"
    image = Image.new("RGB", (612, 792), "white")
    ImageDraw.Draw(image).text((72, 72), expected_id, fill="black")
    scanned = tmp_path / "misread-id.pdf"
    c = canvas.Canvas(str(scanned), pagesize=letter)
    c.drawImage(
        ImageReader(image),
        0,
        0,
        width=letter[0],
        height=letter[1],
    )
    c.save()

    words = [WordBbox(text=ocr_id, page=1, x=72, y=72, width=80, height=12)]
    ocr_results = iter(
        [
            ocr_processor.OCRPageResult(
                words=words,
                text=ocr_id,
                confidence=0.9,
                attempts=1,
                human_review=False,
            ),
            ocr_processor.OCRPageResult(
                words=[],
                text="",
                confidence=0.9,
                attempts=1,
                human_review=False,
            ),
        ]
    )
    monkeypatch.setattr(ocr_processor, "is_available", lambda: True)
    monkeypatch.setattr(
        ocr_processor,
        "ocr_page",
        lambda page, page_num, **kw: next(ocr_results),
    )

    result = probe(
        scanned,
        {
            "layout": "single_column",
            "values": [_value(0, "national id", expected_id, "THAI_ID")],
            "decoys": [],
        },
    )

    assert result["extraction"]["missing"] == 1
    assert result["privacy_alignment"]["aligned"] == 1
    detection = result["detection"]["values"][0]
    assert detection["alignment"] == "ocr_approximate"
    assert detection["type_match"] is True
    assert result["coverage"]["values"][0]["alignment"] == "ocr_approximate"
    assert result["residual"]["values"][0]["verdict"] == "removed"


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
