export const CONTRACT_HEADER = "X-AIGuard-Contract-Version";
export const CONTRACT_VERSION = "2";

const SECTION26 = new Set([
  "RACE_ETHNICITY",
  "POLITICAL_OPINION",
  "RELIGION",
  "HEALTH",
  "SEXUAL_BEHAVIOR",
  "CRIMINAL_RECORD",
  "DISABILITY",
  "LABOR_UNION",
]);
const GUARD_CATEGORIES = new Set([
  "instruction_override",
  "role_hijack",
  "exfiltration",
  "hidden_chars",
  "suspicious_payload",
]);
const GUARD_SEVERITIES = new Set(["low", "medium", "high"]);
const REDACT_TYPES = new Set(["FP", "TB"]);
const GRADES = new Set(["A", "B", "C", "D", "F"]);
const RISK_LABELS = new Set([
  "Very Low Risk",
  "Low Risk",
  "Medium Risk",
  "High Risk",
  "Very High Risk",
]);
const QUASI_CATEGORIES = new Set([
  "gender",
  "date_of_birth",
  "age",
  "district",
  "province",
  "occupation",
  "religion",
]);
const RECOMMENDATION_LEVELS = new Set(["high", "medium", "info"]);
const RECOMMENDATION_TEMPLATES = {
  direct: {
    level: "high",
    title: "Direct PII detected",
    desc: "ใช้ AI Guard เพื่อปกปิดข้อมูลทั้งหมดก่อนส่งให้ AI ภายนอก",
  },
  section26: {
    level: "high",
    title: "Section 26 sensitive data detected",
    desc: "ต้องได้รับความยินยอมโดยชัดแจ้งจากเจ้าของข้อมูลก่อนประมวลผล ตาม PDPA มาตรา 26",
  },
  reidentification: {
    level: "medium",
    title: "High re-identification risk",
    desc: "ลดการรวมข้อมูลกึ่งระบุตัวบุคคลก่อนนำข้อมูลไปใช้",
  },
  minimization: {
    level: "info",
    title: "Consider data minimization",
    desc: "เก็บเฉพาะข้อมูลที่จำเป็นตามวัตถุประสงค์ที่กำหนด ตาม PDPA มาตรา 22",
  },
  clear: {
    level: "info",
    title: "No significant PDPA risk detected",
    desc: "ไม่พบข้อมูลส่วนบุคคลที่มีความเสี่ยงสูงในข้อความนี้",
  },
};
const RESTORE_WARNINGS = new Set(["generated_pii", "foreign_replacement"]);
const PDF_WARNINGS = new Set(["ocr_low_confidence", "human_review_required"]);
const AUDIT_FLAG_CODES = new Set([
  "provider_call",
  "leftover_replacement",
  "residual_block",
  "ocr_review_required",
  "source_pdf_text",
  "source_pdf_hybrid",
]);
const PROCESS_STEPS = new Set([
  "api_sanitize",
  "api_reidentify",
  "api_analyze",
  "api_analyze_report",
  "api_roundtrip",
  "api_redact_pdf",
]);
const VALIDATION_RESULTS = new Set(["prepared", "blocked", "pass", "warn"]);
const SECURITY_LAYERS = new Set([
  "layer1",
  "layer2",
  "layer3",
  "outbound",
  "provider",
  "restore",
]);
const PII_SCAN_RESULTS = new Set(["clean", "unexpected_pii", "blocked", "error"]);

const ERROR_SPECS = new Map([
  ["contract_version_required", [426, "contract", false]],
  ["invalid_request", [400, "request", false]],
  ["request_schema_invalid", [422, "request", false]],
  ["authentication_required", [401, "authentication", false]],
  ["control_forbidden", [403, "authentication", false]],
  ["route_not_found", [404, "request", false]],
  ["session_unavailable", [404, "session", false]],
  ["method_not_allowed", [405, "request", false]],
  ["rate_limited", [429, "service", true]],
  ["payload_too_large", [413, "request", false]],
  ["residual_pii", [422, "privacy", false]],
  ["document_invalid", [422, "document", false]],
  ["provider_unavailable", [502, "upstream", true]],
  ["provider_rejected", [502, "upstream", false]],
  ["provider_response_invalid", [502, "upstream", false]],
  ["ner_incomplete", [502, "upstream", false]],
  ["provider_configuration", [503, "configuration", false]],
  ["dependency_unavailable", [503, "dependency", false]],
  ["ocr_unavailable", [503, "dependency", false]],
  ["service_unavailable", [503, "service", true]],
  ["restore_failed", [500, "internal", false]],
  ["internal_error", [500, "internal", false]],
]);
const COUNTED_ERROR_CODES = new Set([
  "request_schema_invalid",
  "residual_pii",
  "ner_incomplete",
  "ner_unavailable",
]);

function fail(label) {
  throw new Error(`invalid ${label} response`);
}

function plainObject(value, label) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) fail(label);
  return value;
}

function exactObject(value, keys, label) {
  const object = plainObject(value, label);
  const actual = Object.keys(object).sort();
  const expected = [...keys].sort();
  if (
    actual.length !== expected.length ||
    actual.some((key, index) => key !== expected[index])
  ) {
    fail(label);
  }
  return object;
}

function stringValue(value, label, { nonempty = false } = {}) {
  if (typeof value !== "string" || (nonempty && value.length === 0)) fail(label);
  return value;
}

function enumValue(value, allowed, label) {
  if (!allowed.has(value)) fail(label);
  return value;
}

function booleanValue(value, label) {
  if (typeof value !== "boolean") fail(label);
  return value;
}

function nonNegativeInt(value, label) {
  if (!Number.isInteger(value) || value < 0) fail(label);
  return value;
}

function errorCount(code, value, label) {
  const count = nonNegativeInt(value, label);
  if (!COUNTED_ERROR_CODES.has(code) && count !== 0) fail(label);
  return count;
}

function positiveInt(value, label) {
  if (!Number.isInteger(value) || value <= 0) fail(label);
  return value;
}

function finiteRange(value, min, max, label) {
  let projected = value;
  if (typeof value === "string") {
    if (!/^(0|[1-9][0-9]*)(?:\.[0-9]*[1-9])?$/.test(value)) fail(label);
    projected = Number(value);
  }
  if (!Number.isFinite(projected) || projected < min || projected > max) fail(label);
  return projected;
}

function uniqueEnumList(value, allowed, label) {
  if (!Array.isArray(value)) fail(label);
  const canonical = [...allowed];
  let previousIndex = -1;
  return value.map((item) => {
    const projected = enumValue(item, allowed, label);
    const index = canonical.indexOf(projected);
    if (index <= previousIndex) fail(label);
    previousIndex = index;
    return projected;
  });
}

function countMap(value, label) {
  const source = plainObject(value, label);
  const projected = {};
  for (const [key, count] of Object.entries(source)) {
    if (!/^[A-Z][A-Z0-9_]*$/.test(key)) fail(label);
    projected[key] = positiveInt(count, label);
  }
  return projected;
}

function dataType(value, label) {
  const projected = stringValue(value, label, { nonempty: true });
  if (!/^[A-Z][A-Z0-9_]*$/.test(projected)) fail(label);
  return projected;
}

function sumCounts(value) {
  return Object.values(value).reduce((sum, count) => sum + count, 0);
}

function warningList(value, allowed, label) {
  if (!Array.isArray(value)) fail(label);
  const seen = new Set();
  const projected = value.map((warning) => {
    const item = exactObject(warning, ["code", "count"], label);
    const code = enumValue(item.code, allowed, label);
    if (seen.has(code)) fail(label);
    seen.add(code);
    return { code, count: positiveInt(item.count, label) };
  });
  const expected = [...allowed].filter((code) => seen.has(code));
  if (projected.some((warning, index) => warning.code !== expected[index])) fail(label);
  return projected;
}

function guardFindings(value, label) {
  if (!Array.isArray(value)) fail(label);
  const seen = new Set();
  return value.map((finding) => {
    const item = exactObject(finding, ["category", "severity"], label);
    const projected = {
      category: enumValue(item.category, GUARD_CATEGORIES, label),
      severity: enumValue(item.severity, GUARD_SEVERITIES, label),
    };
    const key = `${projected.category}:${projected.severity}`;
    if (seen.has(key)) fail(label);
    seen.add(key);
    return projected;
  });
}

function highlightList(value, text, label) {
  if (!Array.isArray(value)) fail(label);
  const codePointLength = Array.from(text).length;
  let previousEnd = 0;
  return value.map((highlight) => {
    const item = exactObject(
      highlight,
      ["start", "end", "data_type", "redact_type"],
      label
    );
    const start = nonNegativeInt(item.start, label);
    const end = nonNegativeInt(item.end, label);
    if (start >= end || start < previousEnd || end > codePointLength) fail(label);
    previousEnd = end;
    return {
      start,
      end,
      data_type: dataType(item.data_type, label),
      redact_type: enumValue(item.redact_type, REDACT_TYPES, label),
    };
  });
}

function safety(value, label) {
  const item = exactObject(value, ["status", "residual_count"], label);
  if (item.status !== "pass" || item.residual_count !== 0) fail(label);
  return { status: "pass", residual_count: 0 };
}

export function hasV2ResponseHeader(response) {
  return (
    response &&
    response.headers &&
    typeof response.headers.get === "function" &&
    response.headers.get(CONTRACT_HEADER) === CONTRACT_VERSION
  );
}

export function validateHealth(value) {
  const item = exactObject(
    value,
    ["status", "version", "contract_version", "capabilities"],
    "health"
  );
  if (item.status !== "ok" || item.contract_version !== 2) fail("health");
  const capabilities = exactObject(
    item.capabilities,
    ["control_token_required", "api_key_required"],
    "health"
  );
  return {
    status: "ok",
    version: stringValue(item.version, "health", { nonempty: true }),
    contract_version: 2,
    capabilities: {
      control_token_required: booleanValue(
        capabilities.control_token_required,
        "health"
      ),
      api_key_required: booleanValue(capabilities.api_key_required, "health"),
    },
  };
}

export function validateBrokerHealth(value) {
  const item = exactObject(value, ["status"], "broker health");
  if (item.status !== "ok") fail("broker health");
  return { status: "ok" };
}

export function validateSanitize(value) {
  const item = exactObject(
    value,
    [
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
    ],
    "sanitize"
  );
  const sanitizedText = stringValue(item.sanitized_text, "sanitize", {
    nonempty: true,
  });
  const counts = countMap(item.entity_type_counts, "sanitize");
  const detectedCount = nonNegativeInt(item.detected_entity_count, "sanitize");
  const highlights = highlightList(item.highlights, sanitizedText, "sanitize");
  const replacementCount = nonNegativeInt(item.replacement_count, "sanitize");
  if (
    sumCounts(counts) !== detectedCount ||
    highlights.length !== replacementCount ||
    replacementCount < detectedCount
  ) {
    fail("sanitize");
  }
  const warnings = warningList(item.warnings, new Set(), "sanitize");
  return {
    session_id: stringValue(item.session_id, "sanitize", { nonempty: true }),
    sanitized_text: sanitizedText,
    detected_entity_count: detectedCount,
    replacement_count: replacementCount,
    entity_type_counts: counts,
    highlights,
    section26_categories: uniqueEnumList(
      item.section26_categories,
      SECTION26,
      "sanitize"
    ),
    guard_findings: guardFindings(item.guard_findings, "sanitize"),
    warnings,
    safety: safety(item.safety, "sanitize"),
  };
}

export function validateReidentify(value) {
  const item = exactObject(
    value,
    ["restored_text", "replaced_count", "leftover_count", "warnings"],
    "reidentify"
  );
  return {
    restored_text: stringValue(item.restored_text, "reidentify"),
    replaced_count: nonNegativeInt(item.replaced_count, "reidentify"),
    leftover_count: nonNegativeInt(item.leftover_count, "reidentify"),
    warnings: warningList(item.warnings, RESTORE_WARNINGS, "reidentify"),
  };
}

export function restorationIsComplete(value) {
  return (
    value.leftover_count === 0 &&
    Array.isArray(value.warnings) &&
    !value.warnings.some((warning) => RESTORE_WARNINGS.has(warning.code))
  );
}

export function validateDetect(value, sourceText) {
  const item = exactObject(
    value,
    ["detected_entity_count", "entity_type_counts", "highlights"],
    "detect"
  );
  const counts = countMap(item.entity_type_counts, "detect");
  const detectedCount = nonNegativeInt(item.detected_entity_count, "detect");
  const highlights = highlightList(item.highlights, sourceText, "detect");
  if (
    sumCounts(counts) !== detectedCount ||
    highlights.length !== detectedCount
  ) {
    fail("detect");
  }
  return {
    detected_entity_count: detectedCount,
    entity_type_counts: counts,
    highlights,
  };
}

export function validateGuard(value) {
  const item = exactObject(value, ["flagged", "guard_findings"], "guard");
  const findings = guardFindings(item.guard_findings, "guard");
  const flagged = booleanValue(item.flagged, "guard");
  if (flagged !== (findings.length > 0)) fail("guard");
  return { flagged, guard_findings: findings };
}

export function validateRoundtrip(value, requestedProvider) {
  const item = exactObject(
    value,
    [
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
    ],
    "roundtrip"
  );
  const providerUsed = stringValue(item.provider_used, "roundtrip", {
    nonempty: true,
  });
  if (providerUsed !== requestedProvider) fail("roundtrip");
  const counts = countMap(item.entity_type_counts, "roundtrip");
  const detectedCount = nonNegativeInt(item.detected_entity_count, "roundtrip");
  if (sumCounts(counts) !== detectedCount) fail("roundtrip");
  const warnings = warningList(item.warnings, RESTORE_WARNINGS, "roundtrip");
  const restoration = exactObject(
    item.restoration,
    ["status", "replaced_count", "leftover_count"],
    "roundtrip"
  );
  const leftoverCount = nonNegativeInt(restoration.leftover_count, "roundtrip");
  const expectedStatus = warnings.length
    ? "unsafe"
    : leftoverCount
      ? "incomplete"
      : "complete";
  if (restoration.status !== expectedStatus) fail("roundtrip");
  return {
    sanitized_text: stringValue(item.sanitized_text, "roundtrip", {
      nonempty: true,
    }),
    ai_response_masked: stringValue(item.ai_response_masked, "roundtrip"),
    restored_text: stringValue(item.restored_text, "roundtrip"),
    detected_entity_count: detectedCount,
    entity_type_counts: counts,
    provider_used: providerUsed,
    section26_categories: uniqueEnumList(
      item.section26_categories,
      SECTION26,
      "roundtrip"
    ),
    guard_findings: guardFindings(item.guard_findings, "roundtrip"),
    warnings,
    safety: safety(item.safety, "roundtrip"),
    restoration: {
      status: expectedStatus,
      replaced_count: nonNegativeInt(restoration.replaced_count, "roundtrip"),
      leftover_count: leftoverCount,
    },
  };
}

export function validateAnalyze(value) {
  const item = exactObject(
    value,
    [
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
    ],
    "analyze"
  );
  const reidentification = exactObject(
    item.reidentification,
    ["score", "grade", "quasi_identifier_categories", "high_risk_combination"],
    "analyze"
  );
  if (!Array.isArray(item.breakdown) || !Array.isArray(item.recommendations)) {
    fail("analyze");
  }
  const breakdown = item.breakdown.map((row) => {
    const entry = exactObject(row, ["data_type", "redact_type", "count"], "analyze");
    return {
      data_type: dataType(entry.data_type, "analyze"),
      redact_type: enumValue(entry.redact_type, REDACT_TYPES, "analyze"),
      count: positiveInt(entry.count, "analyze"),
    };
  });
  const breakdownKeys = breakdown.map(
    (row) => `${row.data_type}:${row.redact_type}`
  );
  if (new Set(breakdownKeys).size !== breakdownKeys.length) fail("analyze");
  const recommendations = item.recommendations.map((row) => {
    const entry = exactObject(row, ["level", "title", "desc"], "analyze");
    return {
      level: enumValue(entry.level, RECOMMENDATION_LEVELS, "analyze"),
      title: stringValue(entry.title, "analyze", { nonempty: true }),
      desc: stringValue(entry.desc, "analyze", { nonempty: true }),
    };
  });
  const directCount = nonNegativeInt(item.direct_pii_count, "analyze");
  const fpCount = nonNegativeInt(item.fp_count, "analyze");
  const tbCount = nonNegativeInt(item.tb_count, "analyze");
  const fpBreakdown = breakdown
    .filter((row) => row.redact_type === "FP")
    .reduce((sum, row) => sum + row.count, 0);
  const tbBreakdown = breakdown
    .filter((row) => row.redact_type === "TB")
    .reduce((sum, row) => sum + row.count, 0);
  if (
    directCount !== fpCount + tbCount ||
    fpCount !== fpBreakdown ||
    tbCount !== tbBreakdown
  ) {
    fail("analyze");
  }
  const overallScore = finiteRange(item.overall_score, 0, 100, "analyze");
  const section26Categories = uniqueEnumList(
    item.section26_categories,
    SECTION26,
    "analyze"
  );
  const highRiskCombination = booleanValue(
    reidentification.high_risk_combination,
    "analyze"
  );
  const expectedRecommendations = [];
  if (directCount) expectedRecommendations.push(RECOMMENDATION_TEMPLATES.direct);
  if (section26Categories.length) {
    expectedRecommendations.push(RECOMMENDATION_TEMPLATES.section26);
  }
  if (highRiskCombination) {
    expectedRecommendations.push(RECOMMENDATION_TEMPLATES.reidentification);
  }
  if (overallScore >= 60) {
    expectedRecommendations.push(RECOMMENDATION_TEMPLATES.minimization);
  }
  if (!expectedRecommendations.length) {
    expectedRecommendations.push(RECOMMENDATION_TEMPLATES.clear);
  }
  if (JSON.stringify(recommendations) !== JSON.stringify(expectedRecommendations)) {
    fail("analyze");
  }
  return {
    overall_score: overallScore,
    overall_grade: enumValue(item.overall_grade, GRADES, "analyze"),
    risk_label: enumValue(item.risk_label, RISK_LABELS, "analyze"),
    direct_pii_count: directCount,
    fp_count: fpCount,
    tb_count: tbCount,
    section26_categories: section26Categories,
    reidentification: {
      score: finiteRange(reidentification.score, 0, 100, "analyze"),
      grade: enumValue(reidentification.grade, GRADES, "analyze"),
      quasi_identifier_categories: uniqueEnumList(
        reidentification.quasi_identifier_categories,
        QUASI_CATEGORIES,
        "analyze"
      ),
      high_risk_combination: highRiskCombination,
    },
    breakdown,
    recommendations,
  };
}

export function validateAnalyzeReport(value) {
  const item = exactObject(
    value,
    ["report_pdf_b64", "overall_score", "overall_grade"],
    "analyze-report"
  );
  return {
    report_pdf_b64: stringValue(item.report_pdf_b64, "analyze-report", {
      nonempty: true,
    }),
    overall_score: finiteRange(item.overall_score, 0, 100, "analyze-report"),
    overall_grade: enumValue(item.overall_grade, GRADES, "analyze-report"),
  };
}

export function validateRedactPdf(value) {
  const item = exactObject(
    value,
    [
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
    ],
    "redact-pdf"
  );
  const counts = countMap(item.entity_type_counts, "redact-pdf");
  const detectedCount = nonNegativeInt(item.detected_entity_count, "redact-pdf");
  if (sumCounts(counts) !== detectedCount || !Array.isArray(item.fields)) {
    fail("redact-pdf");
  }
  const fields = item.fields.map((field) => {
    const entry = exactObject(field, ["data_type", "redact_type"], "redact-pdf");
    return {
      data_type: dataType(entry.data_type, "redact-pdf"),
      redact_type: enumValue(entry.redact_type, REDACT_TYPES, "redact-pdf"),
    };
  });
  const fieldKeys = fields.map((field) => `${field.data_type}\u0000${field.redact_type}`);
  if (new Set(fieldKeys).size !== fieldKeys.length) fail("redact-pdf");
  return {
    source_type: enumValue(
      item.source_type,
      new Set(["pdf_text", "pdf_hybrid"]),
      "redact-pdf"
    ),
    ocr_confidence:
      item.ocr_confidence === null
        ? null
        : finiteRange(item.ocr_confidence, 0, 1, "redact-pdf"),
    human_review: booleanValue(item.human_review, "redact-pdf"),
    warnings: warningList(item.warnings, PDF_WARNINGS, "redact-pdf"),
    detected_entity_count: detectedCount,
    entity_type_counts: counts,
    fields,
    section26_categories: uniqueEnumList(
      item.section26_categories,
      SECTION26,
      "redact-pdf"
    ),
    redacted_pdf_b64: stringValue(item.redacted_pdf_b64, "redact-pdf", {
      nonempty: true,
    }),
    after_png_b64: stringValue(item.after_png_b64, "redact-pdf", {
      nonempty: true,
    }),
  };
}

function auditFlags(value, label) {
  if (!Array.isArray(value)) fail(label);
  const seen = new Set();
  return value.map((flag) => {
    const item = exactObject(flag, ["code", "count"], label);
    const code = enumValue(item.code, AUDIT_FLAG_CODES, label);
    if (seen.has(code)) fail(label);
    seen.add(code);
    return { code, count: nonNegativeInt(item.count, label) };
  });
}

function auditRow(value) {
  const source = plainObject(value, "audit-log");
  if (source.type === "process") {
    const item = exactObject(
      source,
      [
        "type",
        "timestamp",
        "step",
        "entity_count",
        "validation_result",
        "latency_ms",
        "flags",
      ],
      "audit-log"
    );
    return {
      type: "process",
      timestamp: finiteRange(item.timestamp, 0, Number.MAX_VALUE, "audit-log"),
      step: enumValue(item.step, PROCESS_STEPS, "audit-log"),
      entity_count: nonNegativeInt(item.entity_count, "audit-log"),
      validation_result: enumValue(
        item.validation_result,
        VALIDATION_RESULTS,
        "audit-log"
      ),
      latency_ms: finiteRange(item.latency_ms, 0, Number.MAX_VALUE, "audit-log"),
      flags: auditFlags(item.flags, "audit-log"),
    };
  }
  if (source.type === "security") {
    const item = exactObject(
      source,
      [
        "type",
        "timestamp",
        "layer",
        "pii_scan_result",
        "retry_count",
        "error_type",
        "rollback_occurred",
      ],
      "audit-log"
    );
    return {
      type: "security",
      timestamp: finiteRange(item.timestamp, 0, Number.MAX_VALUE, "audit-log"),
      layer: enumValue(item.layer, SECURITY_LAYERS, "audit-log"),
      pii_scan_result: enumValue(
        item.pii_scan_result,
        PII_SCAN_RESULTS,
        "audit-log"
      ),
      retry_count: nonNegativeInt(item.retry_count, "audit-log"),
      error_type:
        item.error_type === null
          ? null
          : enumValue(
              item.error_type,
              new Set([...ERROR_SPECS.keys(), "ner_unavailable"]),
              "audit-log"
            ),
      rollback_occurred: booleanValue(item.rollback_occurred, "audit-log"),
    };
  }
  fail("audit-log");
}

export function validateAuditLog(value) {
  const item = exactObject(
    value,
    ["status", "total_count", "limit", "offset", "logs"],
    "audit-log"
  );
  if (item.status !== "ok" || !Array.isArray(item.logs)) fail("audit-log");
  const logs = item.logs.map(auditRow);
  const totalCount = nonNegativeInt(item.total_count, "audit-log");
  if (totalCount < logs.length) fail("audit-log");
  return {
    status: "ok",
    total_count: totalCount,
    limit: positiveInt(item.limit, "audit-log"),
    offset: nonNegativeInt(item.offset, "audit-log"),
    logs,
  };
}

export function validateErrorEnvelope(value, responseStatus) {
  const outer = exactObject(value, ["error"], "error");
  const item = exactObject(
    outer.error,
    ["code", "category", "count", "retryable", "status"],
    "error"
  );
  const code = stringValue(item.code, "error", { nonempty: true });
  let spec = ERROR_SPECS.get(code);
  if (code === "ner_unavailable") {
    const allowed =
      (item.category === "configuration" || item.category === "dependency") &&
      item.retryable === false
        ? true
        : (item.category === "network" || item.category === "upstream") &&
          item.retryable === true;
    if (!allowed || item.status !== 503) fail("error");
    spec = [503, item.category, item.retryable];
  }
  if (!spec) fail("error");
  if (
    item.status !== responseStatus ||
    item.status !== spec[0] ||
    item.category !== spec[1] ||
    item.retryable !== spec[2]
  ) {
    fail("error");
  }
  return {
    error: {
      code,
      category: item.category,
      count: errorCount(code, item.count, "error"),
      retryable: item.retryable,
      status: item.status,
    },
  };
}

export function codePointRangeToUtf16(text, start, end) {
  const points = Array.from(text);
  if (
    !Number.isInteger(start) ||
    !Number.isInteger(end) ||
    start < 0 ||
    end < start ||
    end > points.length
  ) {
    throw new Error("invalid code-point range");
  }
  return [
    points.slice(0, start).join("").length,
    points.slice(0, end).join("").length,
  ];
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

export function renderHighlightedText(text, highlights, chipClass) {
  const safeClass = chipClass === "chip--surrogate" ? "chip--surrogate" : "chip--token";
  const parts = [];
  let cursor = 0;
  for (const highlight of highlights) {
    const [start, end] = codePointRangeToUtf16(text, highlight.start, highlight.end);
    parts.push(escapeHtml(text.slice(cursor, start)));
    parts.push(
      `<span class="chip ${safeClass}">${escapeHtml(text.slice(start, end))}</span>`
    );
    cursor = end;
  }
  parts.push(escapeHtml(text.slice(cursor)));
  return parts.join("");
}
