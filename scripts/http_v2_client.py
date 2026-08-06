"""Strict, mapping-minimized HTTP v2 validators for repository-owned scripts."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

CONTRACT_HEADER = "X-AIGuard-Contract-Version"
CONTRACT_VERSION = "2"

_DATA_TYPE = re.compile(r"^[A-Z][A-Z0-9_]*$")
_SECTION26 = (
    "RACE_ETHNICITY",
    "POLITICAL_OPINION",
    "RELIGION",
    "HEALTH",
    "SEXUAL_BEHAVIOR",
    "CRIMINAL_RECORD",
    "DISABILITY",
    "LABOR_UNION",
)
_SECTION26_ORDER = {category: index for index, category in enumerate(_SECTION26)}
_GUARD_CATEGORIES = {
    "instruction_override",
    "role_hijack",
    "exfiltration",
    "hidden_chars",
    "suspicious_payload",
}
_GUARD_SEVERITIES = {"low", "medium", "high"}
_RESTORE_WARNING_CODES = ("generated_pii", "foreign_replacement")
_PDF_WARNING_CODES = ("ocr_low_confidence", "human_review_required")
_GRADES = {"A", "B", "C", "D", "F"}
_RISK_LABELS = {
    "Very Low Risk",
    "Low Risk",
    "Medium Risk",
    "High Risk",
    "Very High Risk",
}
_QUASI_CATEGORIES = (
    "gender",
    "date_of_birth",
    "age",
    "district",
    "province",
    "occupation",
    "religion",
)
_RECOMMENDATION_TEMPLATES = {
    "direct": {
        "level": "high",
        "title": "Direct PII detected",
        "desc": "ใช้ AI Guard เพื่อปกปิดข้อมูลทั้งหมดก่อนส่งให้ AI ภายนอก",
    },
    "section26": {
        "level": "high",
        "title": "Section 26 sensitive data detected",
        "desc": "ต้องได้รับความยินยอมโดยชัดแจ้งจากเจ้าของข้อมูลก่อนประมวลผล ตาม PDPA มาตรา 26",
    },
    "reidentification": {
        "level": "medium",
        "title": "High re-identification risk",
        "desc": "ลดการรวมข้อมูลกึ่งระบุตัวบุคคลก่อนนำข้อมูลไปใช้",
    },
    "minimization": {
        "level": "info",
        "title": "Consider data minimization",
        "desc": "เก็บเฉพาะข้อมูลที่จำเป็นตามวัตถุประสงค์ที่กำหนด ตาม PDPA มาตรา 22",
    },
    "clear": {
        "level": "info",
        "title": "No significant PDPA risk detected",
        "desc": "ไม่พบข้อมูลส่วนบุคคลที่มีความเสี่ยงสูงในข้อความนี้",
    },
}

_ERRORS = {
    "contract_version_required": (426, "contract", False),
    "invalid_request": (400, "request", False),
    "request_schema_invalid": (422, "request", False),
    "authentication_required": (401, "authentication", False),
    "control_forbidden": (403, "authentication", False),
    "route_not_found": (404, "request", False),
    "session_unavailable": (404, "session", False),
    "method_not_allowed": (405, "request", False),
    "rate_limited": (429, "service", True),
    "payload_too_large": (413, "request", False),
    "residual_pii": (422, "privacy", False),
    "document_invalid": (422, "document", False),
    "provider_unavailable": (502, "upstream", True),
    "provider_rejected": (502, "upstream", False),
    "provider_response_invalid": (502, "upstream", False),
    "ner_incomplete": (502, "upstream", False),
    "provider_configuration": (503, "configuration", False),
    "dependency_unavailable": (503, "dependency", False),
    "ocr_unavailable": (503, "dependency", False),
    "service_unavailable": (503, "service", True),
    "restore_failed": (500, "internal", False),
    "internal_error": (500, "internal", False),
}
_COUNTED_ERROR_CODES = {
    "request_schema_invalid",
    "residual_pii",
    "ner_incomplete",
    "ner_unavailable",
}


class ContractError(ValueError):
    """The peer did not satisfy the exact HTTP v2 contract."""


def _fail() -> None:
    raise ContractError("HTTP v2 contract rejected")


def _object(value: Any, keys: set[str]) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        _fail()
    return value


def _list(value: Any) -> list[Any]:
    if type(value) is not list:
        _fail()
    return value


def _string(value: Any, *, nonempty: bool = False) -> str:
    if type(value) is not str or (nonempty and not value.strip()):
        _fail()
    return value


def _boolean(value: Any) -> bool:
    if type(value) is not bool:
        _fail()
    return value


def _count(value: Any, *, positive: bool = False) -> int:
    if type(value) is not int or value < (1 if positive else 0):
        _fail()
    return value


def _score(value: Any, *, maximum: float = 100.0) -> float:
    if type(value) not in {int, float} or not math.isfinite(value):
        _fail()
    number = float(value)
    if not 0.0 <= number <= maximum:
        _fail()
    return number


def _count_map(value: Any) -> dict[str, int]:
    if type(value) is not dict:
        _fail()
    projected: dict[str, int] = {}
    for key, count in value.items():
        if type(key) is not str or not _DATA_TYPE.fullmatch(key):
            _fail()
        projected[key] = _count(count, positive=True)
    return projected


def _section26(value: Any) -> list[str]:
    categories = [_string(item) for item in _list(value)]
    positions: list[int] = []
    for item in categories:
        if item not in _SECTION26_ORDER:
            _fail()
        positions.append(_SECTION26_ORDER[item])
    if any(current >= following for current, following in zip(positions, positions[1:])):
        _fail()
    return categories


def _guard_findings(value: Any) -> list[dict[str, str]]:
    projected: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for raw in _list(value):
        item = _object(raw, {"category", "severity"})
        category = _string(item["category"])
        severity = _string(item["severity"])
        key = (category, severity)
        if category not in _GUARD_CATEGORIES or severity not in _GUARD_SEVERITIES or key in seen:
            _fail()
        seen.add(key)
        projected.append({"category": category, "severity": severity})
    return projected


def _warnings(value: Any, allowed: Sequence[str]) -> list[dict[str, Any]]:
    projected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in _list(value):
        item = _object(raw, {"code", "count"})
        code = _string(item["code"])
        if code not in allowed or code in seen:
            _fail()
        seen.add(code)
        projected.append({"code": code, "count": _count(item["count"], positive=True)})
    expected = [code for code in allowed if code in seen]
    if [item["code"] for item in projected] != expected:
        _fail()
    return projected


def _safety(value: Any) -> dict[str, Any]:
    item = _object(value, {"status", "residual_count"})
    status = _string(item["status"])
    residual_count = _count(item["residual_count"])
    if status != "pass" or residual_count != 0:
        _fail()
    return {"status": status, "residual_count": residual_count}


def _highlights(value: Any, text: str) -> list[dict[str, Any]]:
    projected: list[dict[str, Any]] = []
    prior_end = 0
    for raw in _list(value):
        item = _object(raw, {"start", "end", "data_type", "redact_type"})
        start = _count(item["start"])
        end = _count(item["end"])
        data_type = _string(item["data_type"])
        redact_type = _string(item["redact_type"])
        if (
            start >= end
            or start < prior_end
            or end > len(text)
            or not _DATA_TYPE.fullmatch(data_type)
            or redact_type not in {"FP", "TB"}
        ):
            _fail()
        prior_end = end
        projected.append(
            {
                "start": start,
                "end": end,
                "data_type": data_type,
                "redact_type": redact_type,
            }
        )
    return projected


def contract_header_values(headers: Any) -> list[str]:
    """Return every assertion value without accepting comma-coalesced duplicates."""

    if hasattr(headers, "get_list"):
        values = headers.get_list(CONTRACT_HEADER)
    elif hasattr(headers, "get_all"):
        values = headers.get_all(CONTRACT_HEADER) or []
    elif isinstance(headers, Mapping):
        value = headers.get(CONTRACT_HEADER)
        values = [] if value is None else [value]
    else:
        _fail()
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        _fail()
    return [_string(value) for value in values]


def require_contract_header(headers: Any) -> None:
    if contract_header_values(headers) != [CONTRACT_VERSION]:
        _fail()


def validate_health(value: Any) -> dict[str, Any]:
    body = _object(value, {"status", "version", "contract_version", "capabilities"})
    capabilities = _object(
        body["capabilities"],
        {"control_token_required", "api_key_required"},
    )
    status = _string(body["status"])
    version = _string(body["version"], nonempty=True)
    contract_version = _count(body["contract_version"])
    if status != "ok" or contract_version != 2:
        _fail()
    return {
        "status": status,
        "version": version,
        "contract_version": contract_version,
        "capabilities": {
            "control_token_required": _boolean(capabilities["control_token_required"]),
            "api_key_required": _boolean(capabilities["api_key_required"]),
        },
    }


def validate_sanitize(value: Any) -> dict[str, Any]:
    body = _object(
        value,
        {
            "session_id",
            "sanitized_text",
            "detected_entity_count",
            "replacement_count",
            "entity_type_counts",
            "highlights",
            "section26_categories",
            "guard_findings",
            "warnings",
            "safety",
        },
    )
    sanitized_text = _string(body["sanitized_text"], nonempty=True)
    counts = _count_map(body["entity_type_counts"])
    highlights = _highlights(body["highlights"], sanitized_text)
    detected = _count(body["detected_entity_count"])
    replacements = _count(body["replacement_count"])
    if (
        detected != sum(counts.values())
        or replacements != len(highlights)
        or replacements < detected
    ):
        _fail()
    warnings = _warnings(body["warnings"], ())
    return {
        "session_id": _string(body["session_id"], nonempty=True),
        "sanitized_text": sanitized_text,
        "detected_entity_count": detected,
        "replacement_count": replacements,
        "entity_type_counts": counts,
        "highlights": highlights,
        "section26_categories": _section26(body["section26_categories"]),
        "guard_findings": _guard_findings(body["guard_findings"]),
        "warnings": warnings,
        "safety": _safety(body["safety"]),
    }


def validate_detect(value: Any, *, source_text: str) -> dict[str, Any]:
    body = _object(
        value,
        {
            "detected_entity_count",
            "entity_type_counts",
            "highlights",
        },
    )
    counts = _count_map(body["entity_type_counts"])
    highlights = _highlights(body["highlights"], _string(source_text))
    detected = _count(body["detected_entity_count"])
    if detected != sum(counts.values()) or detected != len(highlights):
        _fail()
    return {
        "detected_entity_count": detected,
        "entity_type_counts": counts,
        "highlights": highlights,
    }


def validate_reidentify(value: Any) -> dict[str, Any]:
    body = _object(
        value,
        {"restored_text", "replaced_count", "leftover_count", "warnings"},
    )
    return {
        "restored_text": _string(body["restored_text"]),
        "replaced_count": _count(body["replaced_count"]),
        "leftover_count": _count(body["leftover_count"]),
        "warnings": _warnings(body["warnings"], _RESTORE_WARNING_CODES),
    }


def validate_roundtrip(value: Any, *, requested_provider: str) -> dict[str, Any]:
    body = _object(
        value,
        {
            "sanitized_text",
            "ai_response_masked",
            "restored_text",
            "detected_entity_count",
            "entity_type_counts",
            "provider_used",
            "section26_categories",
            "guard_findings",
            "warnings",
            "safety",
            "restoration",
        },
    )
    provider_used = _string(body["provider_used"], nonempty=True)
    if provider_used != requested_provider:
        _fail()
    counts = _count_map(body["entity_type_counts"])
    detected = _count(body["detected_entity_count"])
    if detected != sum(counts.values()):
        _fail()
    warnings = _warnings(body["warnings"], _RESTORE_WARNING_CODES)
    restoration = _object(
        body["restoration"],
        {"status", "replaced_count", "leftover_count"},
    )
    restoration_status = _string(restoration["status"])
    replaced_count = _count(restoration["replaced_count"])
    leftover_count = _count(restoration["leftover_count"])
    expected_status = "unsafe" if warnings else "incomplete" if leftover_count else "complete"
    if restoration_status != expected_status:
        _fail()
    return {
        "sanitized_text": _string(body["sanitized_text"], nonempty=True),
        "ai_response_masked": _string(body["ai_response_masked"]),
        "restored_text": _string(body["restored_text"]),
        "detected_entity_count": detected,
        "entity_type_counts": counts,
        "provider_used": provider_used,
        "section26_categories": _section26(body["section26_categories"]),
        "guard_findings": _guard_findings(body["guard_findings"]),
        "warnings": warnings,
        "safety": _safety(body["safety"]),
        "restoration": {
            "status": restoration_status,
            "replaced_count": replaced_count,
            "leftover_count": leftover_count,
        },
    }


def validate_guard(value: Any) -> dict[str, Any]:
    body = _object(value, {"flagged", "guard_findings"})
    findings = _guard_findings(body["guard_findings"])
    flagged = _boolean(body["flagged"])
    if flagged != bool(findings):
        _fail()
    return {"flagged": flagged, "guard_findings": findings}


def validate_analyze(value: Any) -> dict[str, Any]:
    body = _object(
        value,
        {
            "overall_score",
            "overall_grade",
            "risk_label",
            "direct_pii_count",
            "fp_count",
            "tb_count",
            "section26_categories",
            "reidentification",
            "breakdown",
            "recommendations",
        },
    )
    grade = _string(body["overall_grade"])
    risk_label = _string(body["risk_label"])
    if grade not in _GRADES or risk_label not in _RISK_LABELS:
        _fail()

    reidentification = _object(
        body["reidentification"],
        {
            "score",
            "grade",
            "quasi_identifier_categories",
            "high_risk_combination",
        },
    )
    reidentification_grade = _string(reidentification["grade"])
    quasi = [_string(item) for item in _list(reidentification["quasi_identifier_categories"])]
    if (
        reidentification_grade not in _GRADES
        or len(set(quasi)) != len(quasi)
        or any(item not in _QUASI_CATEGORIES for item in quasi)
        or quasi != sorted(quasi, key=_QUASI_CATEGORIES.index)
    ):
        _fail()

    breakdown: list[dict[str, Any]] = []
    seen_breakdown: set[tuple[str, str]] = set()
    fp_total = 0
    tb_total = 0
    for raw in _list(body["breakdown"]):
        item = _object(raw, {"data_type", "redact_type", "count"})
        data_type = _string(item["data_type"])
        redact_type = _string(item["redact_type"])
        count = _count(item["count"], positive=True)
        key = (data_type, redact_type)
        if (
            not _DATA_TYPE.fullmatch(data_type)
            or redact_type not in {"FP", "TB"}
            or key in seen_breakdown
        ):
            _fail()
        seen_breakdown.add(key)
        if redact_type == "FP":
            fp_total += count
        else:
            tb_total += count
        breakdown.append({"data_type": data_type, "redact_type": redact_type, "count": count})

    direct_count = _count(body["direct_pii_count"])
    fp_count = _count(body["fp_count"])
    tb_count = _count(body["tb_count"])
    if fp_count != fp_total or tb_count != tb_total or direct_count != fp_count + tb_count:
        _fail()

    recommendations: list[dict[str, str]] = []
    for raw in _list(body["recommendations"]):
        item = _object(raw, {"level", "title", "desc"})
        level = _string(item["level"])
        if level not in {"high", "medium", "info"}:
            _fail()
        recommendations.append(
            {
                "level": level,
                "title": _string(item["title"], nonempty=True),
                "desc": _string(item["desc"], nonempty=True),
            }
        )
    expected_recommendations: list[dict[str, str]] = []
    if direct_count:
        expected_recommendations.append(_RECOMMENDATION_TEMPLATES["direct"])
    if body["section26_categories"]:
        expected_recommendations.append(_RECOMMENDATION_TEMPLATES["section26"])
    if reidentification["high_risk_combination"]:
        expected_recommendations.append(_RECOMMENDATION_TEMPLATES["reidentification"])
    if float(body["overall_score"]) >= 60:
        expected_recommendations.append(_RECOMMENDATION_TEMPLATES["minimization"])
    if not expected_recommendations:
        expected_recommendations.append(_RECOMMENDATION_TEMPLATES["clear"])
    if recommendations != expected_recommendations:
        _fail()

    return {
        "overall_score": _score(body["overall_score"]),
        "overall_grade": grade,
        "risk_label": risk_label,
        "direct_pii_count": direct_count,
        "fp_count": fp_count,
        "tb_count": tb_count,
        "section26_categories": _section26(body["section26_categories"]),
        "reidentification": {
            "score": _score(reidentification["score"]),
            "grade": reidentification_grade,
            "quasi_identifier_categories": quasi,
            "high_risk_combination": _boolean(reidentification["high_risk_combination"]),
        },
        "breakdown": breakdown,
        "recommendations": recommendations,
    }


def validate_analyze_report(value: Any) -> dict[str, Any]:
    body = _object(value, {"report_pdf_b64", "overall_score", "overall_grade"})
    grade = _string(body["overall_grade"])
    if grade not in _GRADES:
        _fail()
    return {
        "report_pdf_b64": _string(body["report_pdf_b64"]),
        "overall_score": _score(body["overall_score"]),
        "overall_grade": grade,
    }


def validate_redact_pdf(value: Any) -> dict[str, Any]:
    body = _object(
        value,
        {
            "source_type",
            "ocr_confidence",
            "human_review",
            "warnings",
            "detected_entity_count",
            "entity_type_counts",
            "fields",
            "section26_categories",
            "redacted_pdf_b64",
            "after_png_b64",
        },
    )
    source_type = _string(body["source_type"])
    if source_type not in {"pdf_text", "pdf_hybrid"}:
        _fail()
    confidence = body["ocr_confidence"]
    if confidence is not None:
        confidence = _score(confidence, maximum=1.0)
    counts = _count_map(body["entity_type_counts"])
    detected = _count(body["detected_entity_count"])
    if detected != sum(counts.values()):
        _fail()
    fields: list[dict[str, str]] = []
    seen_fields: set[tuple[str, str]] = set()
    for raw in _list(body["fields"]):
        item = _object(raw, {"data_type", "redact_type"})
        data_type = _string(item["data_type"])
        redact_type = _string(item["redact_type"])
        key = (data_type, redact_type)
        if (
            not _DATA_TYPE.fullmatch(data_type)
            or redact_type not in {"FP", "TB"}
            or key in seen_fields
        ):
            _fail()
        seen_fields.add(key)
        fields.append({"data_type": data_type, "redact_type": redact_type})
    return {
        "source_type": source_type,
        "ocr_confidence": confidence,
        "human_review": _boolean(body["human_review"]),
        "warnings": _warnings(body["warnings"], _PDF_WARNING_CODES),
        "detected_entity_count": detected,
        "entity_type_counts": counts,
        "fields": fields,
        "section26_categories": _section26(body["section26_categories"]),
        "redacted_pdf_b64": _string(body["redacted_pdf_b64"]),
        "after_png_b64": _string(body["after_png_b64"]),
    }


def validate_error(value: Any, *, response_status: int) -> dict[str, Any]:
    body = _object(value, {"error"})
    error = _object(
        body["error"],
        {"code", "category", "count", "retryable", "status"},
    )
    code = _string(error["code"])
    category = _string(error["category"])
    count = _count(error["count"])
    retryable = _boolean(error["retryable"])
    status = _count(error["status"])
    expected = _ERRORS.get(code)
    if status != response_status:
        _fail()
    if code == "ner_unavailable":
        if (
            status != 503
            or category not in {"configuration", "dependency", "network", "upstream"}
            or retryable != (category in {"network", "upstream"})
        ):
            _fail()
    elif expected != (status, category, retryable):
        _fail()
    if code not in _COUNTED_ERROR_CODES and count != 0:
        _fail()
    return {
        "error": {
            "code": code,
            "category": category,
            "count": count,
            "retryable": retryable,
            "status": status,
        }
    }
