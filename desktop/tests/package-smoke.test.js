import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  analyze: vi.fn(),
  analyzeReport: vi.fn(),
  auditLog: vi.fn(),
  copyMasked: vi.fn(),
  disposeSession: vi.fn(),
  health: vi.fn(),
  redactPdf: vi.fn(),
  reidentify: vi.fn(),
  resetScope: vi.fn(),
  sanitize: vi.fn(),
}));

vi.mock("../src/api.js", () => mocks);

const invoke = vi.fn();

beforeEach(() => {
  vi.clearAllMocks();
  window.__TAURI__ = { core: { invoke } };
  window.__AIGUARD_APP_READY__ = Promise.resolve(true);
  invoke.mockResolvedValue(undefined);
  mocks.health.mockResolvedValue({ status: "ok" });
  mocks.analyze.mockResolvedValue({ direct_pii_count: 1 });
  mocks.sanitize
    .mockResolvedValueOnce({
      session_id: "opaque-broker-handle",
      sanitized_text: "[PHONE_1]",
    })
    .mockResolvedValueOnce({
      session_id: "opaque-broker-handle",
      sanitized_text: "[PHONE_2]",
    });
  mocks.copyMasked.mockResolvedValue({ copied: true });
  mocks.reidentify.mockResolvedValue({
    restored_text: "Synthetic contact 081-234-5678",
    leftover_count: 0,
    warnings: [],
  });
  mocks.analyzeReport.mockResolvedValue({ report_pdf_b64: "JVBERi0=" });
  mocks.redactPdf.mockResolvedValue({ redacted_pdf_b64: "JVBERi0=" });
  mocks.auditLog.mockResolvedValue({ status: "ok" });
  mocks.disposeSession.mockResolvedValue({ disposed: true });
  mocks.resetScope.mockResolvedValue({ closed: true });
});

describe("installed Desktop webview package smoke", () => {
  it("waits for page load before reading deferred app readiness", async () => {
    const readyState = vi
      .spyOn(document, "readyState", "get")
      .mockReturnValue("loading");
    delete window.__AIGUARD_APP_READY__;
    const { runPackageSmoke } = await import("../src/package-smoke.js");

    const smoke = runPackageSmoke();
    await Promise.resolve();

    expect(invoke).not.toHaveBeenCalled();
    expect(mocks.health).not.toHaveBeenCalled();

    window.__AIGUARD_APP_READY__ = Promise.resolve(true);
    window.dispatchEvent(new Event("load"));
    await smoke;

    expect(mocks.health).toHaveBeenCalledOnce();
    expect(invoke).toHaveBeenNthCalledWith(1, "desktop_package_smoke_ready");
    expect(invoke).toHaveBeenNthCalledWith(
      2,
      "desktop_package_smoke_finish",
      { evidence: expect.any(Object) }
    );
    readyState.mockRestore();
  });

  it.each([
    ["absent", () => delete window.__AIGUARD_APP_READY__],
    ["false", () => (window.__AIGUARD_APP_READY__ = Promise.resolve(false))],
  ])(
    "fails closed at app_ready when readiness is %s after page load",
    async (_case, setReadiness) => {
      const readyState = vi
        .spyOn(document, "readyState", "get")
        .mockReturnValue("loading");
      setReadiness();
      const { runPackageSmoke } = await import("../src/package-smoke.js");

      const smoke = runPackageSmoke();
      await Promise.resolve();

      expect(invoke).not.toHaveBeenCalled();

      window.dispatchEvent(new Event("load"));
      await smoke;

      expect(mocks.health).not.toHaveBeenCalled();
      expect(invoke).toHaveBeenCalledOnce();
      expect(invoke).toHaveBeenCalledWith("desktop_package_smoke_fail", {
        stage: "app_ready",
      });
      readyState.mockRestore();
    }
  );

  it("crosses the production API and reports only bounded status/timings", async () => {
    const { runPackageSmoke } = await import("../src/package-smoke.js");

    await runPackageSmoke();

    expect(invoke).toHaveBeenNthCalledWith(1, "desktop_package_smoke_ready");
    expect(invoke).toHaveBeenNthCalledWith(
      2,
      "desktop_package_smoke_finish",
      { evidence: expect.objectContaining({ workflowMs: expect.any(Number) }) }
    );
    const encodedEvidence = JSON.stringify(invoke.mock.calls[1][1]);
    expect(encodedEvidence).not.toContain("Synthetic contact");
    expect(encodedEvidence).not.toContain("opaque-broker-handle");
    expect(encodedEvidence).not.toContain("[PHONE_1]");
    expect(Object.keys(invoke.mock.calls[1][1].evidence).sort()).toEqual(
      [
        "healthConnectMs",
        "analyzeMs",
        "sanitizeMs",
        "continuationMs",
        "copyMs",
        "reidentifyMs",
        "reportMs",
        "pdfMs",
        "auditMs",
        "cleanupMs",
        "workflowMs",
      ].sort()
    );
    expect(mocks.copyMasked).toHaveBeenCalledOnce();
    expect(mocks.disposeSession).toHaveBeenCalledWith("opaque-broker-handle");
    expect(mocks.resetScope).toHaveBeenCalledOnce();
  });

  it("never continues or reports private failure details after a rejected mutation", async () => {
    mocks.sanitize.mockReset();
    mocks.sanitize.mockRejectedValue(new Error("private provider body"));
    const { runPackageSmoke } = await import("../src/package-smoke.js");

    await runPackageSmoke();

    expect(mocks.reidentify).not.toHaveBeenCalled();
    expect(invoke).toHaveBeenLastCalledWith("desktop_package_smoke_fail", {
      stage: "sanitize",
    });
    expect(JSON.stringify(invoke.mock.calls.at(-1))).not.toContain(
      "private provider body"
    );
  });
});
