"""Strict DTOs and fixed error metadata for the main HTTP contract v2."""

from __future__ import annotations

import math
import re
from typing import Annotated, Literal

from fastapi import HTTPException
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)
from starlette.responses import JSONResponse

CONTRACT_VERSION = 2
CONTRACT_HEADER = "X-AIGuard-Contract-Version"

ErrorCategory = Literal[
    "contract",
    "request",
    "authentication",
    "session",
    "privacy",
    "document",
    "provider",
    "configuration",
    "dependency",
    "network",
    "upstream",
    "service",
    "internal",
]


class _ErrorSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    status: int
    category: ErrorCategory
    retryable: bool


ERROR_SPECS: dict[str, _ErrorSpec] = {
    "contract_version_required": _ErrorSpec(status=426, category="contract", retryable=False),
    "invalid_request": _ErrorSpec(status=400, category="request", retryable=False),
    "request_schema_invalid": _ErrorSpec(status=422, category="request", retryable=False),
    "authentication_required": _ErrorSpec(status=401, category="authentication", retryable=False),
    "control_forbidden": _ErrorSpec(status=403, category="authentication", retryable=False),
    "route_not_found": _ErrorSpec(status=404, category="request", retryable=False),
    "session_unavailable": _ErrorSpec(status=404, category="session", retryable=False),
    "method_not_allowed": _ErrorSpec(status=405, category="request", retryable=False),
    "rate_limited": _ErrorSpec(status=429, category="service", retryable=True),
    "payload_too_large": _ErrorSpec(status=413, category="request", retryable=False),
    "residual_pii": _ErrorSpec(status=422, category="privacy", retryable=False),
    "document_invalid": _ErrorSpec(status=422, category="document", retryable=False),
    "provider_unavailable": _ErrorSpec(status=502, category="upstream", retryable=True),
    "provider_rejected": _ErrorSpec(status=502, category="upstream", retryable=False),
    "provider_response_invalid": _ErrorSpec(status=502, category="upstream", retryable=False),
    "ner_incomplete": _ErrorSpec(status=502, category="upstream", retryable=False),
    "provider_configuration": _ErrorSpec(status=503, category="configuration", retryable=False),
    "dependency_unavailable": _ErrorSpec(status=503, category="dependency", retryable=False),
    "ocr_unavailable": _ErrorSpec(status=503, category="dependency", retryable=False),
    "ner_unavailable": _ErrorSpec(status=503, category="dependency", retryable=False),
    "service_unavailable": _ErrorSpec(status=503, category="service", retryable=True),
    "restore_failed": _ErrorSpec(status=500, category="internal", retryable=False),
    "internal_error": _ErrorSpec(status=500, category="internal", retryable=False),
}
_COUNTED_ERROR_CODES = {
    "request_schema_invalid",
    "residual_pii",
    "ner_incomplete",
    "ner_unavailable",
}
_QUASI_IDENTIFIER_ORDER = (
    "gender",
    "date_of_birth",
    "age",
    "district",
    "province",
    "occupation",
    "religion",
)

ErrorCode = Literal[
    "contract_version_required",
    "invalid_request",
    "request_schema_invalid",
    "authentication_required",
    "control_forbidden",
    "route_not_found",
    "session_unavailable",
    "method_not_allowed",
    "rate_limited",
    "payload_too_large",
    "residual_pii",
    "document_invalid",
    "provider_unavailable",
    "provider_rejected",
    "provider_response_invalid",
    "ner_incomplete",
    "provider_configuration",
    "dependency_unavailable",
    "ocr_unavailable",
    "ner_unavailable",
    "service_unavailable",
    "restore_failed",
    "internal_error",
]


class ContractError(HTTPException):
    """A value-free marker that selects one fixed public error row."""

    def __init__(self, code: ErrorCode, *, count: int = 0):
        self.code = code
        self.count = count if type(count) is int and count >= 0 else 0
        super().__init__(status_code=ERROR_SPECS[code].status, detail=code)


class StrictDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ErrorBody(StrictDTO):
    code: ErrorCode
    category: ErrorCategory
    count: Annotated[int, Field(ge=0)]
    retryable: bool
    status: Annotated[int, Field(ge=400, le=599)]


class ErrorEnvelope(StrictDTO):
    error: ErrorBody


def error_payload(code: ErrorCode, *, count: int = 0) -> dict[str, object]:
    spec = ERROR_SPECS[code]
    safe_count = count if type(count) is int and count >= 0 else 0
    if code not in _COUNTED_ERROR_CODES:
        safe_count = 0
    return ErrorEnvelope(
        error=ErrorBody(
            code=code,
            category=spec.category,
            count=safe_count,
            retryable=spec.retryable,
            status=spec.status,
        )
    ).model_dump(mode="json")


def error_response(code: ErrorCode, *, count: int = 0) -> JSONResponse:
    spec = ERROR_SPECS[code]
    return JSONResponse(
        status_code=spec.status,
        content=error_payload(code, count=count),
        headers={CONTRACT_HEADER: str(CONTRACT_VERSION)},
    )


class StrictRequest(StrictDTO):
    pass


class TextRequest(StrictRequest):
    text: str


class SanitizeRequest(StrictRequest):
    text: str
    mode: str | None = None
    session_id: str | None = None


class ReidentifyRequest(StrictRequest):
    session_id: str
    text: str


class RoundtripRequest(StrictRequest):
    text: str
    mode: str
    provider: str


_DATA_TYPE = re.compile(r"^[A-Z][A-Z0-9_]*$")
_SECTION26_ORDER = (
    "RACE_ETHNICITY",
    "POLITICAL_OPINION",
    "RELIGION",
    "HEALTH",
    "SEXUAL_BEHAVIOR",
    "CRIMINAL_RECORD",
    "DISABILITY",
    "LABOR_UNION",
)
RECOMMENDATION_TEMPLATES = {
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


def _validate_count_map(value: object) -> dict[str, int]:
    if type(value) is not dict:
        raise ValueError("invalid count map")
    out: dict[str, int] = {}
    for key, count in value.items():
        if (
            type(key) is not str
            or _DATA_TYPE.fullmatch(key) is None
            or type(count) is not int
            or count <= 0
        ):
            raise ValueError("invalid count map")
        out[key] = count
    return out


def _validate_section26_order(value: list[str]) -> list[str]:
    expected = [category for category in _SECTION26_ORDER if category in value]
    if value != expected:
        raise ValueError("invalid Section 26 order")
    return value


def _validate_guard_findings(value: list[GuardFinding]) -> list[GuardFinding]:
    pairs = [(item.category, item.severity) for item in value]
    if len(pairs) != len(set(pairs)):
        raise ValueError("duplicate guard finding")
    return value


def _validate_restore_warnings(value: list[RestoreWarning]) -> list[RestoreWarning]:
    codes = [item.code for item in value]
    expected = [code for code in ("generated_pii", "foreign_replacement") if code in codes]
    if codes != expected:
        raise ValueError("invalid warning order")
    return value


def _validate_pdf_warnings(value: list[PdfWarning]) -> list[PdfWarning]:
    codes = [item.code for item in value]
    expected = [code for code in ("ocr_low_confidence", "human_review_required") if code in codes]
    if codes != expected:
        raise ValueError("invalid warning order")
    return value


class HealthCapabilities(StrictDTO):
    control_token_required: bool
    api_key_required: bool


class HealthResponse(StrictDTO):
    status: Literal["ok"]
    version: Annotated[str, Field(min_length=1)]
    contract_version: Literal[2]
    capabilities: HealthCapabilities


class Highlight(StrictDTO):
    start: Annotated[int, Field(ge=0)]
    end: Annotated[int, Field(gt=0)]
    data_type: str
    redact_type: Literal["FP", "TB"]

    @field_validator("data_type")
    @classmethod
    def validate_data_type(cls, value: str) -> str:
        if _DATA_TYPE.fullmatch(value) is None:
            raise ValueError("invalid data type")
        return value

    @model_validator(mode="after")
    def validate_interval(self):
        if self.end <= self.start:
            raise ValueError("invalid interval")
        return self


class GuardFinding(StrictDTO):
    category: Literal[
        "instruction_override",
        "role_hijack",
        "exfiltration",
        "hidden_chars",
        "suspicious_payload",
    ]
    severity: Literal["low", "medium", "high"]


class Safety(StrictDTO):
    status: Literal["pass"]
    residual_count: Literal[0]


class SanitizeWarning(StrictDTO):
    code: Literal["__no_sanitize_warning_codes__"]
    count: Annotated[int, Field(gt=0)]


class RestoreWarning(StrictDTO):
    code: Literal["generated_pii", "foreign_replacement"]
    count: Annotated[int, Field(gt=0)]


class PdfWarning(StrictDTO):
    code: Literal["ocr_low_confidence", "human_review_required"]
    count: Annotated[int, Field(gt=0)]


class SanitizeResponse(StrictDTO):
    session_id: Annotated[str, Field(min_length=1)]
    sanitized_text: Annotated[str, Field(min_length=1)]
    detected_entity_count: Annotated[int, Field(ge=0)]
    replacement_count: Annotated[int, Field(ge=0)]
    entity_type_counts: dict[str, int]
    highlights: list[Highlight]
    section26_categories: list[
        Literal[
            "RACE_ETHNICITY",
            "POLITICAL_OPINION",
            "RELIGION",
            "HEALTH",
            "SEXUAL_BEHAVIOR",
            "CRIMINAL_RECORD",
            "DISABILITY",
            "LABOR_UNION",
        ]
    ]
    guard_findings: list[GuardFinding]
    warnings: Annotated[list[SanitizeWarning], Field(max_length=0)]
    safety: Safety

    _count_map = field_validator("entity_type_counts")(_validate_count_map)
    _section26_order = field_validator("section26_categories")(_validate_section26_order)
    _guard_finding_order = field_validator("guard_findings")(_validate_guard_findings)

    @model_validator(mode="after")
    def validate_counts_and_offsets(self):
        if self.detected_entity_count != sum(self.entity_type_counts.values()):
            raise ValueError("detected count mismatch")
        if self.replacement_count != len(self.highlights):
            raise ValueError("replacement count mismatch")
        if self.replacement_count < self.detected_entity_count:
            raise ValueError("missing replacement highlight")
        previous_end = 0
        for item in self.highlights:
            if item.start < previous_end or item.end > len(self.sanitized_text):
                raise ValueError("invalid highlight plan")
            previous_end = item.end
        return self


class ReidentifyResponse(StrictDTO):
    restored_text: str
    replaced_count: Annotated[int, Field(ge=0)]
    leftover_count: Annotated[int, Field(ge=0)]
    warnings: list[RestoreWarning]

    _warning_order = field_validator("warnings")(_validate_restore_warnings)


class Restoration(StrictDTO):
    status: Literal["complete", "incomplete", "unsafe"]
    replaced_count: Annotated[int, Field(ge=0)]
    leftover_count: Annotated[int, Field(ge=0)]


class RoundtripResponse(StrictDTO):
    sanitized_text: Annotated[str, Field(min_length=1)]
    ai_response_masked: str
    restored_text: str
    detected_entity_count: Annotated[int, Field(ge=0)]
    entity_type_counts: dict[str, int]
    provider_used: Annotated[str, Field(min_length=1)]
    section26_categories: list[
        Literal[
            "RACE_ETHNICITY",
            "POLITICAL_OPINION",
            "RELIGION",
            "HEALTH",
            "SEXUAL_BEHAVIOR",
            "CRIMINAL_RECORD",
            "DISABILITY",
            "LABOR_UNION",
        ]
    ]
    guard_findings: list[GuardFinding]
    warnings: list[RestoreWarning]
    safety: Safety
    restoration: Restoration

    _count_map = field_validator("entity_type_counts")(_validate_count_map)
    _section26_order = field_validator("section26_categories")(_validate_section26_order)
    _guard_finding_order = field_validator("guard_findings")(_validate_guard_findings)
    _warning_order = field_validator("warnings")(_validate_restore_warnings)

    @model_validator(mode="after")
    def validate_counts(self):
        if self.detected_entity_count != sum(self.entity_type_counts.values()):
            raise ValueError("detected count mismatch")
        expected_status = (
            "unsafe"
            if self.warnings
            else "incomplete"
            if self.restoration.leftover_count
            else "complete"
        )
        if self.restoration.status != expected_status:
            raise ValueError("restoration status mismatch")
        return self


class DetectResponse(StrictDTO):
    detected_entity_count: Annotated[int, Field(ge=0)]
    entity_type_counts: dict[str, int]
    highlights: list[Highlight]

    _count_map = field_validator("entity_type_counts")(_validate_count_map)

    @model_validator(mode="after")
    def validate_counts(self):
        if self.detected_entity_count != sum(self.entity_type_counts.values()):
            raise ValueError("detected count mismatch")
        if self.detected_entity_count != len(self.highlights):
            raise ValueError("highlight count mismatch")
        previous_end = 0
        for item in self.highlights:
            if item.start < previous_end:
                raise ValueError("invalid highlight order")
            previous_end = item.end
        return self


class ReidProjection(StrictDTO):
    score: Annotated[float, Field(ge=0, le=100, allow_inf_nan=False)]
    grade: Literal["A", "B", "C", "D", "F"]
    quasi_identifier_categories: list[
        Literal[
            "gender",
            "date_of_birth",
            "age",
            "district",
            "province",
            "occupation",
            "religion",
        ]
    ]
    high_risk_combination: bool

    @field_validator("quasi_identifier_categories")
    @classmethod
    def validate_quasi_identifier_categories(cls, value: list[str]) -> list[str]:
        order = {category: index for index, category in enumerate(_QUASI_IDENTIFIER_ORDER)}
        indexes = [order[category] for category in value]
        if indexes != sorted(set(indexes)):
            raise ValueError("invalid quasi-identifier order")
        return value


class BreakdownItem(StrictDTO):
    data_type: str
    redact_type: Literal["FP", "TB"]
    count: Annotated[int, Field(gt=0)]

    @field_validator("data_type")
    @classmethod
    def validate_data_type(cls, value: str) -> str:
        if _DATA_TYPE.fullmatch(value) is None:
            raise ValueError("invalid data type")
        return value


class Recommendation(StrictDTO):
    level: Literal["high", "medium", "info"]
    title: str
    desc: str


class AnalyzeResponse(StrictDTO):
    overall_score: Annotated[float, Field(ge=0, le=100, allow_inf_nan=False)]
    overall_grade: Literal["A", "B", "C", "D", "F"]
    risk_label: Literal[
        "Very Low Risk",
        "Low Risk",
        "Medium Risk",
        "High Risk",
        "Very High Risk",
    ]
    direct_pii_count: Annotated[int, Field(ge=0)]
    fp_count: Annotated[int, Field(ge=0)]
    tb_count: Annotated[int, Field(ge=0)]
    section26_categories: list[
        Literal[
            "RACE_ETHNICITY",
            "POLITICAL_OPINION",
            "RELIGION",
            "HEALTH",
            "SEXUAL_BEHAVIOR",
            "CRIMINAL_RECORD",
            "DISABILITY",
            "LABOR_UNION",
        ]
    ]
    reidentification: ReidProjection
    breakdown: list[BreakdownItem]
    recommendations: list[Recommendation]

    _section26_order = field_validator("section26_categories")(_validate_section26_order)

    @model_validator(mode="after")
    def validate_counts(self):
        seen_breakdown: set[tuple[str, str]] = set()
        fp_total = 0
        tb_total = 0
        for item in self.breakdown:
            key = (item.data_type, item.redact_type)
            if key in seen_breakdown:
                raise ValueError("duplicate breakdown item")
            seen_breakdown.add(key)
            if item.redact_type == "FP":
                fp_total += item.count
            else:
                tb_total += item.count
        if self.direct_pii_count != self.fp_count + self.tb_count:
            raise ValueError("direct count mismatch")
        if self.fp_count != fp_total or self.tb_count != tb_total:
            raise ValueError("breakdown count mismatch")
        expected: list[dict[str, str]] = []
        if self.direct_pii_count:
            expected.append(RECOMMENDATION_TEMPLATES["direct"])
        if self.section26_categories:
            expected.append(RECOMMENDATION_TEMPLATES["section26"])
        if self.reidentification.high_risk_combination:
            expected.append(RECOMMENDATION_TEMPLATES["reidentification"])
        if self.overall_score >= 60:
            expected.append(RECOMMENDATION_TEMPLATES["minimization"])
        if not expected:
            expected.append(RECOMMENDATION_TEMPLATES["clear"])
        actual = [item.model_dump(mode="python") for item in self.recommendations]
        if actual != expected:
            raise ValueError("invalid recommendations")
        return self


class GuardResponse(StrictDTO):
    flagged: bool
    guard_findings: list[GuardFinding]

    _guard_finding_order = field_validator("guard_findings")(_validate_guard_findings)

    @model_validator(mode="after")
    def validate_flag(self):
        if self.flagged != bool(self.guard_findings):
            raise ValueError("guard flag mismatch")
        return self


class AnalyzeReportResponse(StrictDTO):
    report_pdf_b64: str
    overall_score: Annotated[float, Field(ge=0, le=100, allow_inf_nan=False)]
    overall_grade: Literal["A", "B", "C", "D", "F"]


class PdfField(StrictDTO):
    data_type: str
    redact_type: Literal["FP", "TB"]

    @field_validator("data_type")
    @classmethod
    def validate_data_type(cls, value: str) -> str:
        if _DATA_TYPE.fullmatch(value) is None:
            raise ValueError("invalid data type")
        return value


class RedactPdfResponse(StrictDTO):
    source_type: Literal["pdf_text", "pdf_hybrid"]
    ocr_confidence: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)] | None
    human_review: bool
    warnings: list[PdfWarning]
    detected_entity_count: Annotated[int, Field(ge=0)]
    entity_type_counts: dict[str, int]
    fields: list[PdfField]
    section26_categories: list[
        Literal[
            "RACE_ETHNICITY",
            "POLITICAL_OPINION",
            "RELIGION",
            "HEALTH",
            "SEXUAL_BEHAVIOR",
            "CRIMINAL_RECORD",
            "DISABILITY",
            "LABOR_UNION",
        ]
    ]
    redacted_pdf_b64: str
    after_png_b64: str

    _count_map = field_validator("entity_type_counts")(_validate_count_map)
    _section26_order = field_validator("section26_categories")(_validate_section26_order)
    _warning_order = field_validator("warnings")(_validate_pdf_warnings)

    @model_validator(mode="after")
    def validate_counts(self):
        if self.detected_entity_count != sum(self.entity_type_counts.values()):
            raise ValueError("detected count mismatch")
        pairs = [(item.data_type, item.redact_type) for item in self.fields]
        if len(pairs) != len(set(pairs)):
            raise ValueError("duplicate PDF field")
        return self


class AuditFlag(StrictDTO):
    code: Literal[
        "provider_call",
        "leftover_replacement",
        "residual_block",
        "ocr_review_required",
        "source_pdf_text",
        "source_pdf_hybrid",
    ]
    count: Annotated[int, Field(ge=0)]


class ProcessAuditEvent(StrictDTO):
    type: Literal["process"]
    timestamp: Annotated[float, Field(ge=0, allow_inf_nan=False)]
    step: Literal[
        "api_sanitize",
        "api_reidentify",
        "api_analyze",
        "api_analyze_report",
        "api_roundtrip",
        "api_redact_pdf",
    ]
    entity_count: Annotated[int, Field(ge=0)]
    validation_result: Literal["prepared", "blocked", "pass", "warn"]
    latency_ms: Annotated[float, Field(ge=0, allow_inf_nan=False)]
    flags: list[AuditFlag]


class SecurityAuditEvent(StrictDTO):
    type: Literal["security"]
    timestamp: Annotated[float, Field(ge=0, allow_inf_nan=False)]
    layer: Literal["layer1", "layer2", "layer3", "outbound", "provider", "restore"]
    pii_scan_result: Literal["clean", "unexpected_pii", "blocked", "error"]
    retry_count: Annotated[int, Field(ge=0)]
    error_type: ErrorCode | None
    rollback_occurred: bool


AuditEvent = Annotated[
    ProcessAuditEvent | SecurityAuditEvent,
    Field(discriminator="type"),
]


class AuditLogResponse(StrictDTO):
    status: Literal["ok"]
    total_count: Annotated[int, Field(ge=0)]
    limit: Annotated[int, Field(ge=1, le=1000)]
    offset: Annotated[int, Field(ge=0)]
    logs: list[AuditEvent]


class DeleteSessionResponse(StrictDTO):
    deleted: bool


class ShutdownResponse(StrictDTO):
    status: Literal["shutting_down"]


def validated_payload(model: type[StrictDTO], payload: object) -> dict[str, object]:
    """Validate a server-owned projection before it crosses the adapter."""
    # Keep text as Python strings until the response renderer. Besides avoiding
    # an unnecessary serialization pass, this lets the HTTP boundary contain
    # and scrub an encoding failure in one place.
    return model.model_validate(payload).model_dump(mode="python")


def finite_nonnegative(value: object) -> float | None:
    if type(value) not in {int, float} or isinstance(value, bool):
        return None
    result = float(value)
    if not math.isfinite(result) or result < 0:
        return None
    return result
