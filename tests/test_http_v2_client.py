from __future__ import annotations

from copy import deepcopy

import pytest

from scripts.http_v2_client import (
    ContractError,
    validate_analyze,
    validate_detect,
    validate_error,
    validate_health,
    validate_redact_pdf,
    validate_reidentify,
    validate_roundtrip,
    validate_sanitize,
)

TOKEN = f"[ชื่อ_{'a' * 25}_{'n' * 20}_1]"


def _health() -> dict:
    return {
        "status": "ok",
        "version": "2.5.0",
        "contract_version": 2,
        "capabilities": {
            "control_token_required": True,
            "api_key_required": False,
        },
    }


def _sanitize() -> dict:
    return {
        "session_id": "synthetic-session",
        "sanitized_text": f"😀{TOKEN}",
        "detected_entity_count": 1,
        "replacement_count": 1,
        "entity_type_counts": {"NAME": 1},
        "highlights": [
            {
                "start": 1,
                "end": 1 + len(TOKEN),
                "data_type": "NAME",
                "redact_type": "TB",
            }
        ],
        "section26_categories": [],
        "guard_findings": [],
        "warnings": [],
        "safety": {"status": "pass", "residual_count": 0},
    }


def _detect() -> dict:
    return {
        "detected_entity_count": 1,
        "entity_type_counts": {"NAME": 1},
        "highlights": [
            {
                "start": 1,
                "end": 9,
                "data_type": "NAME",
                "redact_type": "TB",
            }
        ],
    }


def _reidentify() -> dict:
    return {
        "restored_text": "synthetic restored text",
        "replaced_count": 1,
        "leftover_count": 0,
        "warnings": [],
    }


def _roundtrip() -> dict:
    return {
        "sanitized_text": TOKEN,
        "ai_response_masked": TOKEN,
        "restored_text": "synthetic restored text",
        "detected_entity_count": 1,
        "entity_type_counts": {"NAME": 1},
        "provider_used": "fake",
        "section26_categories": [],
        "guard_findings": [],
        "warnings": [],
        "safety": {"status": "pass", "residual_count": 0},
        "restoration": {
            "status": "complete",
            "replaced_count": 1,
            "leftover_count": 0,
        },
    }


def _analyze() -> dict:
    return {
        "overall_score": 40.0,
        "overall_grade": "C",
        "risk_label": "Medium Risk",
        "direct_pii_count": 1,
        "fp_count": 1,
        "tb_count": 0,
        "section26_categories": [],
        "reidentification": {
            "score": 10.0,
            "grade": "A",
            "quasi_identifier_categories": [],
            "high_risk_combination": False,
        },
        "breakdown": [{"data_type": "PHONE", "redact_type": "FP", "count": 1}],
        "recommendations": [
            {
                "level": "high",
                "title": "Direct PII detected",
                "desc": "ใช้ AI Guard เพื่อปกปิดข้อมูลทั้งหมดก่อนส่งให้ AI ภายนอก",
            }
        ],
    }


def _redact_pdf() -> dict:
    return {
        "source_type": "pdf_text",
        "ocr_confidence": None,
        "human_review": True,
        "warnings": [
            {"code": "ocr_low_confidence", "count": 1},
            {"code": "human_review_required", "count": 1},
        ],
        "detected_entity_count": 1,
        "entity_type_counts": {"PHONE": 1},
        "fields": [{"data_type": "PHONE", "redact_type": "FP"}],
        "section26_categories": [],
        "redacted_pdf_b64": "JVBERi0=",
        "after_png_b64": "cG5n",
    }


@pytest.mark.parametrize(
    ("validator", "payload", "kwargs"),
    [
        (validate_health, _health(), {}),
        (validate_detect, _detect(), {"source_text": "😀สมชาย ใจดี"}),
        (validate_sanitize, _sanitize(), {}),
        (validate_reidentify, _reidentify(), {}),
        (validate_roundtrip, _roundtrip(), {"requested_provider": "fake"}),
    ],
)
def test_validators_construct_fresh_exact_dtos(validator, payload, kwargs):
    projected = validator(payload, **kwargs)

    assert projected == payload
    assert projected is not payload
    for key, value in projected.items():
        if isinstance(value, (dict, list)):
            assert value is not payload[key]


@pytest.mark.parametrize(
    ("validator", "payload", "kwargs", "extra_key"),
    [
        (validate_health, _health(), {}, "token_required"),
        (
            validate_detect,
            _detect(),
            {"source_text": "😀สมชาย ใจดี"},
            "original_text",
        ),
        (validate_sanitize, _sanitize(), {}, "original_text"),
        (validate_reidentify, _reidentify(), {}, "replaced"),
        (
            validate_roundtrip,
            _roundtrip(),
            {"requested_provider": "fake"},
            "entities",
        ),
    ],
)
def test_validators_reject_unknown_mapping_or_legacy_fields(validator, payload, kwargs, extra_key):
    payload[extra_key] = "blocked"

    with pytest.raises(ContractError):
        validator(payload, **kwargs)


def test_nested_objects_are_exact_and_safety_is_not_truthy_only():
    payload = _sanitize()
    payload["safety"]["extra"] = False
    with pytest.raises(ContractError):
        validate_sanitize(payload)

    payload = _sanitize()
    payload["safety"] = {"status": "pass", "residual_count": 1}
    with pytest.raises(ContractError):
        validate_sanitize(payload)

    payload = _sanitize()
    payload["warnings"] = [{"code": "residual_pii", "count": 1}]
    with pytest.raises(ContractError):
        validate_sanitize(payload)


def test_section26_categories_require_canonical_scan_order():
    payload = _sanitize()
    payload["section26_categories"] = ["RACE_ETHNICITY", "HEALTH"]
    assert validate_sanitize(payload)["section26_categories"] == [
        "RACE_ETHNICITY",
        "HEALTH",
    ]

    payload["section26_categories"] = ["HEALTH", "RACE_ETHNICITY"]
    with pytest.raises(ContractError):
        validate_sanitize(payload)


def test_sanitize_highlights_use_code_point_offsets_and_exact_counts():
    assert validate_sanitize(_sanitize())["highlights"][0] == {
        "start": 1,
        "end": 1 + len(TOKEN),
        "data_type": "NAME",
        "redact_type": "TB",
    }

    payload = _sanitize()
    payload["highlights"][0]["end"] = len(payload["sanitized_text"]) + 20
    with pytest.raises(ContractError):
        validate_sanitize(payload)

    payload = _sanitize()
    payload["replacement_count"] = 2
    with pytest.raises(ContractError):
        validate_sanitize(payload)

    payload = _sanitize()
    payload["detected_entity_count"] = 2
    payload["entity_type_counts"] = {"NAME": 2}
    with pytest.raises(ContractError):
        validate_sanitize(payload)


@pytest.mark.parametrize(
    ("validator", "payload", "kwargs"),
    [
        (
            validate_sanitize,
            {
                **_sanitize(),
                "sanitized_text": "",
                "detected_entity_count": 0,
                "replacement_count": 0,
                "entity_type_counts": {},
                "highlights": [],
            },
            {},
        ),
        (validate_roundtrip, _roundtrip(), {"requested_provider": "fake"}),
    ],
)
def test_outbound_sanitized_text_cannot_be_empty(validator, payload, kwargs):
    payload["sanitized_text"] = ""

    with pytest.raises(ContractError):
        validator(payload, **kwargs)


def test_detect_validator_enforces_source_offsets_and_exact_counts():
    source = "😀สมชาย ใจดี"
    assert validate_detect(_detect(), source_text=source) == _detect()

    outside = _detect()
    outside["highlights"][0]["end"] = len(source) + 1
    with pytest.raises(ContractError):
        validate_detect(outside, source_text=source)

    mismatch = _detect()
    mismatch["detected_entity_count"] = 2
    mismatch["entity_type_counts"] = {"NAME": 2}
    with pytest.raises(ContractError):
        validate_detect(mismatch, source_text=source)


def test_reidentify_partial_or_warned_result_is_valid_preview_but_not_complete():
    partial = _reidentify()
    partial["leftover_count"] = 1
    projected = validate_reidentify(partial)
    assert projected["leftover_count"] == 1

    warned = _reidentify()
    warned["warnings"] = [{"code": "generated_pii", "count": 1}]
    projected = validate_reidentify(warned)
    assert projected["warnings"] == [{"code": "generated_pii", "count": 1}]

    malformed = deepcopy(warned)
    malformed["warnings"][0]["original"] = "blocked"
    with pytest.raises(ContractError):
        validate_reidentify(malformed)


def test_roundtrip_requires_selected_provider_and_consistent_restoration():
    assert validate_roundtrip(_roundtrip(), requested_provider="fake")["provider_used"] == "fake"

    wrong_provider = _roundtrip()
    wrong_provider["provider_used"] = "pathumma"
    with pytest.raises(ContractError):
        validate_roundtrip(wrong_provider, requested_provider="fake")

    inconsistent = _roundtrip()
    inconsistent["restoration"]["status"] = "complete"
    inconsistent["restoration"]["leftover_count"] = 1
    with pytest.raises(ContractError):
        validate_roundtrip(inconsistent, requested_provider="fake")

    unsafe = _roundtrip()
    unsafe["restoration"]["status"] = "unsafe"
    unsafe["warnings"] = []
    with pytest.raises(ContractError):
        validate_roundtrip(unsafe, requested_provider="fake")


def test_analyze_validator_enforces_exact_nested_shape_and_count_parity():
    assert validate_analyze(_analyze()) == _analyze()

    extra = _analyze()
    extra["recommendations"][0]["matched_text"] = "blocked"
    with pytest.raises(ContractError):
        validate_analyze(extra)

    mismatch = _analyze()
    mismatch["direct_pii_count"] = 2
    with pytest.raises(ContractError):
        validate_analyze(mismatch)

    arbitrary = _analyze()
    arbitrary["recommendations"][0]["title"] = "Arbitrary recommendation"
    with pytest.raises(ContractError):
        validate_analyze(arbitrary)

    reversed_quasi = _analyze()
    reversed_quasi["reidentification"]["quasi_identifier_categories"] = [
        "age",
        "gender",
    ]
    with pytest.raises(ContractError):
        validate_analyze(reversed_quasi)

    duplicate_breakdown = _analyze()
    duplicate_breakdown["direct_pii_count"] = 2
    duplicate_breakdown["fp_count"] = 2
    duplicate_breakdown["breakdown"] = [
        {"data_type": "PHONE", "redact_type": "FP", "count": 1},
        {"data_type": "PHONE", "redact_type": "FP", "count": 1},
    ]
    with pytest.raises(ContractError):
        validate_analyze(duplicate_breakdown)


def test_warning_lists_require_canonical_order():
    restore = _reidentify()
    restore["warnings"] = [
        {"code": "foreign_replacement", "count": 1},
        {"code": "generated_pii", "count": 1},
    ]
    with pytest.raises(ContractError):
        validate_reidentify(restore)

    pdf = _redact_pdf()
    pdf["warnings"].reverse()
    with pytest.raises(ContractError):
        validate_redact_pdf(pdf)


def test_recommendations_require_server_template_order():
    payload = _analyze()
    payload["overall_score"] = 60
    payload["section26_categories"] = ["HEALTH"]
    payload["reidentification"]["high_risk_combination"] = True
    payload["recommendations"] = [
        {
            "level": "high",
            "title": "Direct PII detected",
            "desc": "ใช้ AI Guard เพื่อปกปิดข้อมูลทั้งหมดก่อนส่งให้ AI ภายนอก",
        },
        {
            "level": "high",
            "title": "Section 26 sensitive data detected",
            "desc": "ต้องได้รับความยินยอมโดยชัดแจ้งจากเจ้าของข้อมูลก่อนประมวลผล ตาม PDPA มาตรา 26",
        },
        {
            "level": "medium",
            "title": "High re-identification risk",
            "desc": "ลดการรวมข้อมูลกึ่งระบุตัวบุคคลก่อนนำข้อมูลไปใช้",
        },
        {
            "level": "info",
            "title": "Consider data minimization",
            "desc": "เก็บเฉพาะข้อมูลที่จำเป็นตามวัตถุประสงค์ที่กำหนด ตาม PDPA มาตรา 22",
        },
    ]
    assert validate_analyze(payload)["recommendations"] == payload["recommendations"]

    payload["recommendations"][0], payload["recommendations"][1] = (
        payload["recommendations"][1],
        payload["recommendations"][0],
    )
    with pytest.raises(ContractError):
        validate_analyze(payload)


def test_error_counts_follow_the_v2_code_table():
    fixed = {
        "error": {
            "code": "internal_error",
            "category": "internal",
            "count": 1,
            "retryable": False,
            "status": 500,
        }
    }
    with pytest.raises(ContractError):
        validate_error(fixed, response_status=500)

    counted = {
        "error": {
            "code": "residual_pii",
            "category": "privacy",
            "count": 2,
            "retryable": False,
            "status": 422,
        }
    }
    assert validate_error(counted, response_status=422)["error"]["count"] == 2

    reserved_tner = {
        "error": {
            "code": "ner_unavailable",
            "category": "network",
            "count": 3,
            "retryable": True,
            "status": 503,
        }
    }
    assert validate_error(reserved_tner, response_status=503)["error"]["count"] == 3
