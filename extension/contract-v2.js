(function installContractV2(scope) {
  "use strict";

  const HEADER = "X-AIGuard-Contract-Version";
  const VERSION = "2";
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
  const RESTORE_WARNINGS = new Set(["generated_pii", "foreign_replacement"]);
  const REDACT_TYPES = new Set(["FP", "TB"]);
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

  function stringValue(value, label, nonempty = false) {
    if (typeof value !== "string" || (nonempty && value.length === 0)) fail(label);
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

  function enumValue(value, allowed, label) {
    if (!allowed.has(value)) fail(label);
    return value;
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
    const projected = stringValue(value, label, true);
    if (!/^[A-Z][A-Z0-9_]*$/.test(projected)) fail(label);
    return projected;
  }

  function sumCounts(value) {
    return Object.values(value).reduce((sum, count) => sum + count, 0);
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
    if (projected.some((warning, index) => warning.code !== expected[index])) {
      fail(label);
    }
    return projected;
  }

  function highlightList(value, text, label) {
    if (!Array.isArray(value)) fail(label);
    const length = Array.from(text).length;
    let previousEnd = 0;
    return value.map((highlight) => {
      const item = exactObject(
        highlight,
        ["start", "end", "data_type", "redact_type"],
        label
      );
      const start = nonNegativeInt(item.start, label);
      const end = nonNegativeInt(item.end, label);
      if (start >= end || start < previousEnd || end > length) fail(label);
      previousEnd = end;
      return {
        start,
        end,
        data_type: dataType(item.data_type, label),
        redact_type: enumValue(item.redact_type, REDACT_TYPES, label),
      };
    });
  }

  function validateHealth(value) {
    const item = exactObject(
      value,
      ["status", "version", "contract_version", "capabilities"],
      "health"
    );
    const capabilities = exactObject(
      item.capabilities,
      ["control_token_required", "api_key_required"],
      "health"
    );
    if (item.status !== "ok" || item.contract_version !== 2) fail("health");
    return {
      status: "ok",
      version: stringValue(item.version, "health", true),
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

  function validateSanitize(value) {
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
    const text = stringValue(item.sanitized_text, "sanitize", true);
    const counts = countMap(item.entity_type_counts, "sanitize");
    const detected = nonNegativeInt(item.detected_entity_count, "sanitize");
    const replacement = nonNegativeInt(item.replacement_count, "sanitize");
    const highlights = highlightList(item.highlights, text, "sanitize");
    if (
      sumCounts(counts) !== detected ||
      highlights.length !== replacement ||
      replacement < detected
    ) {
      fail("sanitize");
    }
    const safety = exactObject(item.safety, ["status", "residual_count"], "sanitize");
    if (safety.status !== "pass" || safety.residual_count !== 0) fail("sanitize");
    return {
      session_id: stringValue(item.session_id, "sanitize", true),
      sanitized_text: text,
      detected_entity_count: detected,
      replacement_count: replacement,
      entity_type_counts: counts,
      highlights,
      section26_categories: uniqueEnumList(
        item.section26_categories,
        SECTION26,
        "sanitize"
      ),
      guard_findings: guardFindings(item.guard_findings, "sanitize"),
      warnings: warningList(item.warnings, new Set(), "sanitize"),
      safety: { status: "pass", residual_count: 0 },
    };
  }

  function validateReidentify(value) {
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

  function restorationIsComplete(value) {
    return (
      value &&
      value.leftover_count === 0 &&
      Array.isArray(value.warnings) &&
      !value.warnings.some((warning) => RESTORE_WARNINGS.has(warning.code))
    );
  }

  function validateError(value, responseStatus) {
    const outer = exactObject(value, ["error"], "error");
    const item = exactObject(
      outer.error,
      ["code", "category", "count", "retryable", "status"],
      "error"
    );
    const code = stringValue(item.code, "error", true);
    let spec = ERROR_SPECS.get(code);
    if (code === "ner_unavailable") {
      const valid =
        ((item.category === "configuration" || item.category === "dependency") &&
          item.retryable === false) ||
        ((item.category === "network" || item.category === "upstream") &&
          item.retryable === true);
      if (!valid || item.status !== 503) fail("error");
      spec = [503, item.category, item.retryable];
    }
    if (
      !spec ||
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

  function hasHeader(response) {
    return (
      response &&
      response.headers &&
      typeof response.headers.get === "function" &&
      response.headers.get(HEADER) === VERSION
    );
  }

  function codePointRangeToUtf16(text, start, end) {
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

  function renderHighlightedText(text, highlights, mode) {
    const cls = mode === "surrogate" ? "chip chip--surrogate" : "chip chip--token";
    const parts = [];
    let cursor = 0;
    for (const highlight of highlights) {
      const [start, end] = codePointRangeToUtf16(
        text,
        highlight.start,
        highlight.end
      );
      parts.push(escapeHtml(text.slice(cursor, start)));
      parts.push(`<span class="${cls}">${escapeHtml(text.slice(start, end))}</span>`);
      cursor = end;
    }
    parts.push(escapeHtml(text.slice(cursor)));
    return parts.join("");
  }

  scope.AIGUARD_CONTRACT_V2 = Object.freeze({
    HEADER,
    VERSION,
    hasHeader,
    validateHealth,
    validateSanitize,
    validateReidentify,
    validateError,
    restorationIsComplete,
    codePointRangeToUtf16,
    renderHighlightedText,
  });
})(globalThis);
