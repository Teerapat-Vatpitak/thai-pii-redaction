import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const invoke = vi.fn();
const fetchMock = vi.fn();

function brokerResult(operation, result) {
  return { operation, result };
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

const clearRecommendation = {
  level: "info",
  title: "No significant PDPA risk detected",
  desc: "ไม่พบข้อมูลส่วนบุคคลที่มีความเสี่ยงสูงในข้อความนี้",
};

const validResults = {
  analyze: {
    overall_score: "0",
    overall_grade: "A",
    risk_label: "Very Low Risk",
    direct_pii_count: 0,
    fp_count: 0,
    tb_count: 0,
    section26_categories: [],
    reidentification: {
      score: "0",
      grade: "A",
      quasi_identifier_categories: [],
      high_risk_combination: false,
    },
    breakdown: [],
    recommendations: [clearRecommendation],
  },
  analyze_report: {
    report_pdf_b64: "JVBERi0=",
    overall_score: "0",
    overall_grade: "A",
  },
  audit_log: { status: "ok", total_count: 0, limit: 100, offset: 0, logs: [] },
};

describe("Desktop authenticated native-broker API", () => {
  it("routes health through one typed Tauri command without HTTP", async () => {
    invoke.mockResolvedValue(brokerResult("broker_health", { status: "ok" }));
    const api = await freshApi();

    await expect(api.health()).resolves.toEqual({ status: "ok" });
    expect(invoke).toHaveBeenCalledWith("desktop_health");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it.each([
    ["analyze", "desktop_analyze", { text: "synthetic" }],
    ["analyzeReport", "desktop_analyze_report", { text: "synthetic" }],
    ["auditLog", "desktop_audit_log", { limit: 100, offset: 0 }],
  ])("uses the operation-specific %s command", async (method, command, args) => {
    const operation = command.replace("desktop_", "");
    invoke.mockResolvedValue(brokerResult(operation, validResults[operation]));
    const api = await freshApi();
    await api[method](...Object.values(args));
    expect(invoke).toHaveBeenCalledWith(command, args);
  });

  it("does not export unused detect, guard, or provider-roundtrip bridges", async () => {
    const api = await freshApi();
    expect(api.detect).toBeUndefined();
    expect(api.guard).toBeUndefined();
    expect(api.roundtrip).toBeUndefined();
  });

  it("passes only an opaque broker session handle for continuation and disposal", async () => {
    const first = {
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
    };
    invoke
      .mockResolvedValueOnce(brokerResult("sanitize", first))
      .mockResolvedValueOnce(brokerResult("session_dispose", { disposed: true }));
    const api = await freshApi();

    await api.sanitize("synthetic", "token", "session-broker-handle");
    await api.disposeSession("session-broker-handle");

    expect(invoke).toHaveBeenNthCalledWith(1, "desktop_sanitize", {
      text: "synthetic",
      mode: "token",
      sessionId: "session-broker-handle",
    });
    expect(invoke).toHaveBeenNthCalledWith(2, "desktop_session_dispose", {
      sessionId: "session-broker-handle",
    });
  });

  it("publishes masked clipboard text only through the session-bound native command", async () => {
    invoke.mockResolvedValue(
      brokerResult("copy_masked", { copied: true })
    );
    const api = await freshApi();

    await expect(
      api.copyMasked("session-broker-handle", "[PHONE_1]")
    ).resolves.toEqual({ copied: true });

    expect(invoke).toHaveBeenCalledWith("desktop_copy_masked", {
      sessionId: "session-broker-handle",
      text: "[PHONE_1]",
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("does not retry a mutation after an uncertain native failure", async () => {
    invoke
      .mockRejectedValueOnce({
        code: "operation_failed",
        sessionInvalidated: true,
        restartRequired: true,
      })
      .mockRejectedValueOnce({
        code: "operation_failed",
        privatePayload: "must-not-escape",
      });
    const api = await freshApi();

    let failure;
    try {
      await api.sanitize(
        "synthetic-private-value",
        "token",
        "session-broker-handle"
      );
    } catch (error) {
      failure = error;
    }

    expect(failure).toMatchObject({
      name: "ApiError",
      code: "operation_failed",
      sessionInvalidated: true,
    });
    expect(JSON.stringify(failure)).not.toContain("synthetic-private-value");
    expect(JSON.stringify(failure)).not.toContain("session-broker-handle");
    expect(JSON.stringify(failure)).not.toContain("must-not-escape");
    expect(invoke).toHaveBeenCalledTimes(2);
    expect(invoke).toHaveBeenNthCalledWith(1, "desktop_sanitize", {
      text: "synthetic-private-value",
      mode: "token",
      sessionId: "session-broker-handle",
    });
    expect(invoke).toHaveBeenNthCalledWith(2, "desktop_scope_reset");
  });

  it("rejects malformed envelopes and never exposes extra native fields", async () => {
    invoke.mockResolvedValue({
      operation: "broker_health",
      result: { status: "ok" },
      endpoint: "forbidden",
    });
    const api = await freshApi();
    await expect(api.health()).rejects.toMatchObject({
      name: "ApiError",
      code: "operation_failed",
      sessionInvalidated: false,
      restartRequired: true,
    });
    expect(invoke).toHaveBeenCalledTimes(1);
  });

  it("invalidates the scope once when a mutation result cannot be trusted", async () => {
    invoke
      .mockResolvedValueOnce(
        brokerResult("sanitize", {
          session_id: "untrusted-session-reference",
          sanitized_text: "untrusted-result",
        })
      )
      .mockResolvedValueOnce(brokerResult("scope_close", { closed: true }));
    const api = await freshApi();

    let failure;
    try {
      await api.sanitize("synthetic-private-value", "token");
    } catch (error) {
      failure = error;
    }

    expect(failure).toMatchObject({
      name: "ApiError",
      code: "operation_failed",
      sessionInvalidated: true,
      restartRequired: true,
    });
    expect(JSON.stringify(failure)).not.toContain("synthetic-private-value");
    expect(JSON.stringify(failure)).not.toContain("untrusted-session-reference");
    expect(JSON.stringify(failure)).not.toContain("untrusted-result");
    expect(invoke).toHaveBeenCalledTimes(2);
    expect(invoke).toHaveBeenNthCalledWith(1, "desktop_sanitize", {
      text: "synthetic-private-value",
      mode: "token",
    });
    expect(invoke).toHaveBeenNthCalledWith(2, "desktop_scope_reset");
  });

  it("resets only the current window scope through a fixed command", async () => {
    invoke.mockResolvedValue(brokerResult("scope_close", { closed: true }));
    const api = await freshApi();
    await expect(api.resetScope()).resolves.toEqual({ closed: true });
    expect(invoke).toHaveBeenCalledWith("desktop_scope_reset");
  });

  it("rotates renderer authority through the out-of-band lifecycle command", async () => {
    invoke.mockResolvedValue(
      brokerResult("scope_rotate", { rotated: true })
    );
    const api = await freshApi();
    await expect(api.rotateScope()).resolves.toEqual({ rotated: true });
    expect(invoke).toHaveBeenCalledWith("desktop_scope_rotate");
  });
});
