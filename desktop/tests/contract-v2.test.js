import { describe, expect, it } from "vitest";

import {
  codePointRangeToUtf16,
  renderHighlightedText,
  validateAuditLog,
  validateErrorEnvelope,
  validateRedactPdf,
} from "../src/contract-v2.js";

describe("HTTP v2 Unicode offsets", () => {
  it("converts emoji, combining text, Thai text, and boundary positions", () => {
    const text = "😀e\u0301ไทย";
    expect(codePointRangeToUtf16(text, 0, 0)).toEqual([0, 0]);
    expect(codePointRangeToUtf16(text, 0, 1)).toEqual([0, 2]);
    expect(codePointRangeToUtf16(text, 1, 3)).toEqual([2, 4]);
    expect(codePointRangeToUtf16(text, 3, 6)).toEqual([4, 7]);
    expect(codePointRangeToUtf16(text, 6, 6)).toEqual([7, 7]);
  });

  it("renders only the requested sanitized-space range", () => {
    const html = renderHighlightedText(
      "😀 e\u0301 ไทย [ชื่อ_1]",
      [{ start: 9, end: 17, data_type: "NAME", redact_type: "TB" }],
      "chip--token"
    );
    expect(html).toContain('<span class="chip chip--token">[ชื่อ_1]</span>');
    expect(html).toContain("😀 é ไทย");
  });
});

describe("HTTP v2 closed structural values", () => {
  it("rejects duplicate PDF field pairs", () => {
    const body = {
      source_type: "pdf_text",
      ocr_confidence: null,
      human_review: false,
      warnings: [],
      detected_entity_count: 1,
      entity_type_counts: { PHONE: 1 },
      fields: [
        { data_type: "PHONE", redact_type: "FP" },
        { data_type: "PHONE", redact_type: "FP" },
      ],
      section26_categories: [],
      redacted_pdf_b64: "JVBERi0=",
      after_png_b64: "cG5n",
    };

    expect(() => validateRedactPdf(body)).toThrow(/redact-pdf/i);
  });

  it("rejects audit error types outside the v2 error-code table", () => {
    const body = {
      status: "ok",
      total_count: 1,
      limit: 100,
      offset: 0,
      logs: [
        {
          type: "security",
          timestamp: 1,
          layer: "restore",
          pii_scan_result: "error",
          retry_count: 0,
          error_type: "private-exception-name",
          rollback_occurred: false,
        },
      ],
    };

    expect(() => validateAuditLog(body)).toThrow(/audit-log/i);
  });

  it("requires zero count for fixed-count errors", () => {
    const fixed = {
      error: {
        code: "internal_error",
        category: "internal",
        count: 1,
        retryable: false,
        status: 500,
      },
    };
    expect(() => validateErrorEnvelope(fixed, 500)).toThrow(/error/i);

    const counted = {
      error: {
        code: "residual_pii",
        category: "privacy",
        count: 1,
        retryable: false,
        status: 422,
      },
    };
    expect(validateErrorEnvelope(counted, 422).error.count).toBe(1);
  });
});
