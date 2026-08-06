import { afterEach, describe, expect, it, vi } from "vitest";

const HEADER = "X-AIGuard-Contract-Version";

function headers(value = "2") {
  return { get: (name) => (name.toLowerCase() === HEADER.toLowerCase() ? value : null) };
}

function response(body, { ok = true, status = 200, version = "2" } = {}) {
  return { ok, status, headers: headers(version), json: vi.fn().mockResolvedValue(body) };
}

function healthBody(overrides = {}) {
  return {
    status: "ok",
    version: "2.5.0",
    contract_version: 2,
    capabilities: { control_token_required: true, api_key_required: false },
    ...overrides,
  };
}

function sanitizeBody(overrides = {}) {
  return {
    session_id: "desktop-session",
    sanitized_text: "[ชื่อ_1]",
    detected_entity_count: 1,
    replacement_count: 1,
    entity_type_counts: { NAME: 1 },
    highlights: [{ start: 0, end: 8, data_type: "NAME", redact_type: "TB" }],
    section26_categories: [],
    guard_findings: [],
    warnings: [],
    safety: { status: "pass", residual_count: 0 },
    ...overrides,
  };
}

function reidentifyBody(overrides = {}) {
  return {
    restored_text: "restored",
    replaced_count: 1,
    leftover_count: 0,
    warnings: [],
    ...overrides,
  };
}

function analyzeBody() {
  return {
    overall_score: 10,
    overall_grade: "A",
    risk_label: "Very Low Risk",
    direct_pii_count: 1,
    fp_count: 1,
    tb_count: 0,
    section26_categories: [],
    reidentification: {
      score: 2,
      grade: "A",
      quasi_identifier_categories: [],
      high_risk_combination: false,
    },
    breakdown: [{ data_type: "PHONE", redact_type: "FP", count: 1 }],
    recommendations: [
      {
        level: "high",
        title: "Direct PII detected",
        desc: "ใช้ AI Guard เพื่อปกปิดข้อมูลทั้งหมดก่อนส่งให้ AI ภายนอก",
      },
    ],
  };
}

function reportBody() {
  return { report_pdf_b64: "JVBERi0=", overall_score: 10, overall_grade: "A" };
}

function pdfBody() {
  return {
    source_type: "pdf_text",
    ocr_confidence: null,
    human_review: false,
    warnings: [],
    detected_entity_count: 1,
    entity_type_counts: { PHONE: 1 },
    fields: [{ data_type: "PHONE", redact_type: "FP" }],
    section26_categories: [],
    redacted_pdf_b64: "JVBERi0=",
    after_png_b64: "cG5n",
  };
}

function auditBody() {
  return {
    status: "ok",
    total_count: 1,
    limit: 100,
    offset: 0,
    logs: [
      {
        type: "process",
        timestamp: 1,
        step: "api_sanitize",
        entity_count: 1,
        validation_result: "pass",
        latency_ms: 2,
        flags: [{ code: "provider_call", count: 0 }],
      },
    ],
  };
}

async function freshApi() {
  vi.resetModules();
  return import("../src/api.js");
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("Desktop HTTP v2 transport", () => {
  it("blocks every PII request when its fresh health gate fails", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(response(healthBody({ contract_version: 1 })));
    vi.stubGlobal("fetch", fetchMock);
    const api = await freshApi();

    await expect(api.sanitize("synthetic")).rejects.toThrow(/health/i);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0]).toEqual([
      "http://127.0.0.1:8000/api/health",
      { cache: "no-store" },
    ]);
  });

  it("runs health immediately before sanitize and asserts v2 on the operation", async () => {
    const backend = sanitizeBody();
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(response(healthBody()))
      .mockResolvedValueOnce(response(backend));
    vi.stubGlobal("fetch", fetchMock);
    const api = await freshApi();

    const projected = await api.sanitize("synthetic");
    expect(projected).toEqual(sanitizeBody());
    expect(projected).not.toBe(backend);
    expect(projected.safety).not.toBe(backend.safety);

    expect(fetchMock.mock.calls[0]).toEqual([
      "http://127.0.0.1:8000/api/health",
      { cache: "no-store" },
    ]);
    expect(fetchMock.mock.calls[1][1].headers).toEqual({
      "Content-Type": "application/json",
      [HEADER]: "2",
    });
  });

  it("includes an existing session only when one is supplied", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(response(healthBody()))
      .mockResolvedValueOnce(response(sanitizeBody()));
    vi.stubGlobal("fetch", fetchMock);
    const api = await freshApi();

    await api.sanitize("synthetic", "token", "session-1");

    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({
      text: "synthetic",
      mode: "token",
      session_id: "session-1",
    });
  });

  it.each([null, "2, 2", "02", "1"])(
    "rejects response assertion %s before accepting output",
    async (version) => {
      const fetchMock = vi
        .fn()
        .mockResolvedValueOnce(response(healthBody()))
        .mockResolvedValueOnce(response(sanitizeBody(), { version }));
      vi.stubGlobal("fetch", fetchMock);
      const api = await freshApi();

      await expect(api.sanitize("synthetic")).rejects.toThrow(/contract/i);
    }
  );

  it("rejects extra fields and unsafe nested safety", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(response(healthBody()))
      .mockResolvedValueOnce(response(sanitizeBody({ original_text: "synthetic" })));
    vi.stubGlobal("fetch", fetchMock);
    let api = await freshApi();
    await expect(api.sanitize("synthetic")).rejects.toThrow(/response/i);

    fetchMock.mockReset();
    fetchMock
      .mockResolvedValueOnce(response(healthBody()))
      .mockResolvedValueOnce(
        response(sanitizeBody({ safety: { status: "pass", residual_count: 1 } }))
      );
    api = await freshApi();
    await expect(api.sanitize("synthetic")).rejects.toThrow(/response/i);
  });

  it("rejects an empty sanitize result", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(response(healthBody()))
      .mockResolvedValueOnce(
        response(
          sanitizeBody({
            sanitized_text: "",
            detected_entity_count: 0,
            replacement_count: 0,
            entity_type_counts: {},
            highlights: [],
          })
        )
      );
    vi.stubGlobal("fetch", fetchMock);
    const api = await freshApi();

    await expect(api.sanitize("synthetic")).rejects.toThrow(/response/i);
  });

  it("rejects non-canonical Section 26 category order", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(response(healthBody()))
      .mockResolvedValueOnce(
        response(
          sanitizeBody({
            section26_categories: ["HEALTH", "RACE_ETHNICITY"],
          })
        )
      );
    vi.stubGlobal("fetch", fetchMock);
    const api = await freshApi();

    await expect(api.sanitize("synthetic")).rejects.toThrow(/response/i);
  });

  it("repeats health and validates every adjacent Desktop API response", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(response(healthBody()))
      .mockResolvedValueOnce(response(reidentifyBody()))
      .mockResolvedValueOnce(response(healthBody()))
      .mockResolvedValueOnce(response(analyzeBody()))
      .mockResolvedValueOnce(response(healthBody()))
      .mockResolvedValueOnce(response(reportBody()))
      .mockResolvedValueOnce(response(healthBody()))
      .mockResolvedValueOnce(response(pdfBody()))
      .mockResolvedValueOnce(response(healthBody()))
      .mockResolvedValueOnce(response(auditBody()));
    vi.stubGlobal("fetch", fetchMock);
    const api = await freshApi();

    await expect(api.reidentify("session", "[ชื่อ_1]")).resolves.toEqual(
      reidentifyBody()
    );
    await expect(api.analyze("synthetic")).resolves.toEqual(analyzeBody());
    await expect(api.analyzeReport("synthetic")).resolves.toEqual(reportBody());
    await expect(
      api.redactPdf(new File(["synthetic"], "fixture.pdf", { type: "application/pdf" }))
    ).resolves.toEqual(pdfBody());
    await expect(api.auditLog()).resolves.toEqual(auditBody());

    const operationCalls = fetchMock.mock.calls.filter(
      ([url]) => !url.endsWith("/api/health")
    );
    expect(operationCalls).toHaveLength(5);
    for (const [, options] of operationCalls) {
      expect(options.headers[HEADER]).toBe("2");
    }
  });

  it("rejects mapping fields in reidentify and malformed safe errors", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(response(healthBody()))
      .mockResolvedValueOnce(
        response(reidentifyBody({ replaced: [{ token: "[ชื่อ_1]", original: "x" }] }))
      );
    vi.stubGlobal("fetch", fetchMock);
    let api = await freshApi();
    await expect(api.reidentify("session", "[ชื่อ_1]")).rejects.toThrow(/response/i);

    fetchMock.mockReset();
    fetchMock
      .mockResolvedValueOnce(response(healthBody()))
      .mockResolvedValueOnce(
        response(
          {
            error: {
              code: "residual_pii",
              category: "privacy",
              count: 1,
              retryable: false,
              status: 422,
              detail: "not allowed",
            },
          },
          { ok: false, status: 422 }
        )
      );
    api = await freshApi();
    await expect(api.sanitize("synthetic")).rejects.toThrow(/response/i);
  });

  it("rejects noncanonical analyze category and breakdown semantics", async () => {
    const reversedQuasi = analyzeBody();
    reversedQuasi.reidentification.quasi_identifier_categories = ["age", "gender"];
    const duplicateBreakdown = analyzeBody();
    duplicateBreakdown.direct_pii_count = 2;
    duplicateBreakdown.fp_count = 2;
    duplicateBreakdown.breakdown = [
      { data_type: "PHONE", redact_type: "FP", count: 1 },
      { data_type: "PHONE", redact_type: "FP", count: 1 },
    ];
    const wrongSubtotal = analyzeBody();
    wrongSubtotal.fp_count = 0;
    wrongSubtotal.tb_count = 1;

    for (const payload of [reversedQuasi, duplicateBreakdown, wrongSubtotal]) {
      const fetchMock = vi
        .fn()
        .mockResolvedValueOnce(response(healthBody()))
        .mockResolvedValueOnce(response(payload));
      vi.stubGlobal("fetch", fetchMock);
      const api = await freshApi();
      await expect(api.analyze("synthetic")).rejects.toThrow(/response/i);
    }
  });

  it("rejects extra health capability fields before enabling operations", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(
      response(
        healthBody({
          capabilities: {
            control_token_required: true,
            api_key_required: false,
            token: "not-allowed",
          },
        })
      )
    );
    vi.stubGlobal("fetch", fetchMock);
    const api = await freshApi();

    await expect(api.sanitize("synthetic")).rejects.toThrow(/health/i);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
