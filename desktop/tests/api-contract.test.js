import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const invoke = vi.fn();
const fetchMock = vi.fn();

function envelope(operation, result) {
  return { operation, result };
}

function sanitizeBody(overrides = {}) {
  return {
    session_id: "session-broker-handle",
    sanitized_text: "[PHONE_1]",
    detected_entity_count: 1,
    replacement_count: 1,
    entity_type_counts: { PHONE: 1 },
    highlights: [{ start: 0, end: 9, data_type: "PHONE", redact_type: "FP" }],
    section26_categories: [],
    guard_findings: [],
    warnings: [],
    safety: { status: "pass", residual_count: 0 },
    ...overrides,
  };
}

function reidentifyBody(overrides = {}) {
  return {
    restored_text: "synthetic restored",
    replaced_count: 1,
    leftover_count: 0,
    warnings: [],
    ...overrides,
  };
}

function analyzeBody(overrides = {}) {
  return {
    overall_score: "10",
    overall_grade: "A",
    risk_label: "Very Low Risk",
    direct_pii_count: 1,
    fp_count: 1,
    tb_count: 0,
    section26_categories: [],
    reidentification: {
      score: "2",
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
    ...overrides,
  };
}

async function freshApi() {
  vi.resetModules();
  return import("../src/api.js");
}

beforeEach(() => {
  invoke.mockReset();
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  window.__TAURI__ = { core: { invoke } };
});

afterEach(() => {
  delete window.__TAURI__;
  vi.unstubAllGlobals();
});

describe("Desktop native-broker result boundary", () => {
  it("validates a sanitize result and never performs an HTTP health gate", async () => {
    const backend = sanitizeBody();
    invoke.mockResolvedValue(envelope("sanitize", backend));
    const api = await freshApi();

    const projected = await api.sanitize("synthetic");
    expect(projected).toEqual(sanitizeBody());
    expect(projected).not.toBe(backend);
    expect(invoke).toHaveBeenCalledOnce();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("includes an existing opaque session only when supplied", async () => {
    invoke.mockResolvedValue(envelope("sanitize", sanitizeBody()));
    const api = await freshApi();
    await api.sanitize("synthetic", "token", "session-broker-handle");
    expect(invoke).toHaveBeenCalledWith("desktop_sanitize", {
      text: "synthetic",
      mode: "token",
      sessionId: "session-broker-handle",
    });
  });

  it("rejects extra mapping fields and unsafe nested safety", async () => {
    invoke.mockResolvedValueOnce(
      envelope("sanitize", sanitizeBody({ original_text: "forbidden" }))
    );
    let api = await freshApi();
    await expect(api.sanitize("synthetic")).rejects.toMatchObject({
      code: "operation_failed",
      sessionInvalidated: true,
    });

    invoke.mockReset();
    invoke.mockResolvedValueOnce(
      envelope("sanitize", sanitizeBody({ safety: { status: "pass", residual_count: 1 } }))
    );
    api = await freshApi();
    await expect(api.sanitize("synthetic")).rejects.toMatchObject({
      code: "operation_failed",
    });
  });

  it("rejects empty sanitize output and noncanonical Section 26 order", async () => {
    invoke.mockResolvedValueOnce(
      envelope(
        "sanitize",
        sanitizeBody({
          sanitized_text: "",
          detected_entity_count: 0,
          replacement_count: 0,
          entity_type_counts: {},
          highlights: [],
        })
      )
    );
    let api = await freshApi();
    await expect(api.sanitize("synthetic")).rejects.toMatchObject({
      code: "operation_failed",
    });

    invoke.mockReset();
    invoke.mockResolvedValueOnce(
      envelope(
        "sanitize",
        sanitizeBody({ section26_categories: ["HEALTH", "RACE_ETHNICITY"] })
      )
    );
    api = await freshApi();
    await expect(api.sanitize("synthetic")).rejects.toMatchObject({
      code: "operation_failed",
    });
  });

  it("rejects mapping fields in reidentify", async () => {
    invoke.mockResolvedValue(
      envelope(
        "reidentify",
        reidentifyBody({ replaced: [{ token: "[PHONE_1]", original: "forbidden" }] })
      )
    );
    const api = await freshApi();
    await expect(
      api.reidentify("session-broker-handle", "[PHONE_1]")
    ).rejects.toMatchObject({ code: "operation_failed", sessionInvalidated: true });
  });

  it("accepts canonical protocol decimals and rejects noncanonical decimal strings", async () => {
    invoke.mockResolvedValueOnce(envelope("analyze", analyzeBody()));
    let api = await freshApi();
    await expect(api.analyze("synthetic")).resolves.toMatchObject({
      overall_score: 10,
      reidentification: { score: 2 },
    });

    invoke.mockReset();
    invoke.mockResolvedValueOnce(
      envelope("analyze", analyzeBody({ overall_score: "01" }))
    );
    api = await freshApi();
    await expect(api.analyze("synthetic")).rejects.toMatchObject({
      code: "operation_failed",
    });
  });

  it("rejects noncanonical analyze breakdown semantics", async () => {
    invoke.mockResolvedValue(
      envelope("analyze", analyzeBody({ fp_count: 0, tb_count: 1 }))
    );
    const api = await freshApi();
    await expect(api.analyze("synthetic")).rejects.toMatchObject({
      code: "operation_failed",
    });
  });

  it("projects only exact fixed native errors", async () => {
    invoke.mockRejectedValueOnce({
      code: "operation_timeout",
      sessionInvalidated: true,
      restartRequired: false,
    });
    let api = await freshApi();
    await expect(api.sanitize("synthetic")).rejects.toMatchObject({
      code: "operation_timeout",
      sessionInvalidated: true,
      restartRequired: false,
    });

    invoke.mockReset();
    invoke.mockRejectedValueOnce({
      code: "operation_timeout",
      sessionInvalidated: true,
      restartRequired: false,
      detail: "forbidden",
    });
    api = await freshApi();
    await expect(api.sanitize("synthetic")).rejects.toMatchObject({
      code: "operation_failed",
      restartRequired: true,
    });
  });

  it("rejects a mismatched operation or extra native envelope field", async () => {
    invoke.mockResolvedValueOnce(envelope("detect", sanitizeBody()));
    let api = await freshApi();
    await expect(api.sanitize("synthetic")).rejects.toMatchObject({
      code: "operation_failed",
      sessionInvalidated: true,
      restartRequired: true,
    });

    invoke.mockReset();
    invoke.mockResolvedValueOnce({
      operation: "sanitize",
      result: sanitizeBody(),
      endpoint: "forbidden",
    });
    api = await freshApi();
    await expect(api.sanitize("synthetic")).rejects.toMatchObject({
      code: "operation_failed",
      sessionInvalidated: true,
      restartRequired: true,
    });
  });

  it("rejects pagination before invoking native code", async () => {
    const api = await freshApi();
    await expect(api.auditLog(0, 0)).rejects.toMatchObject({ code: "request_invalid" });
    await expect(api.auditLog(100, -1)).rejects.toMatchObject({ code: "request_invalid" });
    expect(invoke).not.toHaveBeenCalled();
  });

  it("does not retry broker disconnects, timeouts, or uncertain completion", async () => {
    for (const code of ["broker_unavailable", "operation_timeout", "operation_failed"]) {
      invoke.mockReset();
      invoke.mockRejectedValue({
        code,
        sessionInvalidated: true,
        restartRequired: true,
      });
      const api = await freshApi();
      await expect(
        api.sanitize("synthetic", "token", "session-broker-handle")
      ).rejects.toMatchObject({ code, sessionInvalidated: true });
      expect(invoke).toHaveBeenCalledTimes(2);
      expect(invoke).toHaveBeenNthCalledWith(1, "desktop_sanitize", {
        text: "synthetic",
        mode: "token",
        sessionId: "session-broker-handle",
      });
      expect(invoke).toHaveBeenNthCalledWith(2, "desktop_scope_reset");
    }
  });
});
