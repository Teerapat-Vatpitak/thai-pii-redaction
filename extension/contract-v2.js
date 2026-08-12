(function installContractV2(scope) {
  "use strict";

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

  function validateNativeHealth(value) {
    const item = exactObject(value, ["product_version", "status"], "native health");
    if (item.status !== "ok") fail("native health");
    const version = stringValue(item.product_version, "native health", true);
    if (!/^[0-9A-Za-z][0-9A-Za-z.+-]{0,63}$/.test(version)) fail("native health");
    return {
      status: "ok",
      version,
      contract_version: 2,
      capabilities: {
        control_token_required: true,
        api_key_required: false,
      },
    };
  }

  function validateNativeSanitize(value) {
    const item = exactObject(
      value,
      [
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
      "native sanitize"
    );
    const text = stringValue(item.sanitized_text, "native sanitize", true);
    const counts = countMap(item.entity_type_counts, "native sanitize");
    const detected = nonNegativeInt(item.detected_entity_count, "native sanitize");
    const replacement = nonNegativeInt(item.replacement_count, "native sanitize");
    const highlights = highlightList(item.highlights, text, "native sanitize");
    if (
      sumCounts(counts) !== detected ||
      highlights.length !== replacement ||
      replacement < detected
    ) {
      fail("native sanitize");
    }
    const safety = exactObject(
      item.safety,
      ["status", "residual_count"],
      "native sanitize"
    );
    if (safety.status !== "pass" || safety.residual_count !== 0) {
      fail("native sanitize");
    }
    return {
      sanitized_text: text,
      detected_entity_count: detected,
      replacement_count: replacement,
      entity_type_counts: counts,
      highlights,
      section26_categories: uniqueEnumList(
        item.section26_categories,
        SECTION26,
        "native sanitize"
      ),
      guard_findings: guardFindings(item.guard_findings, "native sanitize"),
      warnings: warningList(item.warnings, new Set(), "native sanitize"),
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
    validateHealth,
    validateNativeHealth,
    validateNativeSanitize,
    validateReidentify,
    restorationIsComplete,
    codePointRangeToUtf16,
    renderHighlightedText,
  });
})(globalThis);
