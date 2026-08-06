// Headless regression coverage for the browser-only playground artifact flows.
//
// This intentionally exercises the inline script from playground.html: the
// API/PDF Python tests cover server responses, while this verifies that a
// successful response becomes a browser download with the expected safe name.
// It does not replace the real-browser file chooser/download acceptance gate.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const page = readFileSync(resolve(import.meta.dirname, "..", "playground.html"), "utf8");
const markup = page.match(/<body>([\s\S]*?)<script>/i)?.[1];
const script = page.match(/<script>\s*([\s\S]*?)<\/script>/i)?.[1];

if (!markup || !script) throw new Error("playground HTML must contain a body and inline script");

const PDF_B64 = btoa("%PDF-synthetic");
const CONTRACT_HEADER = "X-AIGuard-Contract-Version";

function headers(value = "2") {
  return {
    get: (name) => (name.toLowerCase() === CONTRACT_HEADER.toLowerCase() ? value : null),
  };
}

function response(body, { ok = true, status = 200, version = "2" } = {}) {
  return { ok, status, headers: headers(version), json: async () => body };
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

function roundtripBody(overrides = {}) {
  return {
    sanitized_text: "[ชื่อ_1]",
    ai_response_masked: "สวัสดี [ชื่อ_1]",
    restored_text: "สวัสดี บุคคลทดสอบ",
    detected_entity_count: 1,
    entity_type_counts: { NAME: 1 },
    provider_used: "fake",
    section26_categories: [],
    guard_findings: [],
    warnings: [],
    safety: { status: "pass", residual_count: 0 },
    restoration: {
      status: "complete",
      replaced_count: 1,
      leftover_count: 0,
    },
    ...overrides,
  };
}

async function flush() {
  await new Promise((resolve) => setTimeout(resolve, 0));
  await Promise.resolve();
}

function loadPlayground() {
  document.body.innerHTML = markup;
  // Named elements are browser globals in the shipped page. jsdom does not
  // expose every id consistently when code is executed through Function().
  globalThis.meta = document.getElementById("meta");
  new Function(script)();
}

let clickedDownloads;

beforeEach(async () => {
  clickedDownloads = [];
  vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(response(healthBody())));
  vi.stubGlobal("URL", {
    createObjectURL: vi.fn(() => "blob:aiguard-test"),
    revokeObjectURL: vi.fn(),
  });
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function () {
    clickedDownloads.push({ href: this.href, download: this.download });
  });
  loadPlayground();
  await flush();
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  delete globalThis.meta;
  document.body.innerHTML = "";
});

describe("playground browser artifacts", () => {
  it("turns a successful PDF-redaction response into previews and a redacted download", async () => {
    fetch
      .mockResolvedValueOnce(response(healthBody()))
      .mockResolvedValueOnce({
        ...response({
          source_type: "pdf_text",
          ocr_confidence: null,
          human_review: false,
          warnings: [],
          detected_entity_count: 2,
          entity_type_counts: { NAME: 1, PHONE: 1 },
          fields: [
            { data_type: "NAME", redact_type: "TB" },
            { data_type: "PHONE", redact_type: "FP" },
          ],
          section26_categories: [],
          after_png_b64: btoa("png-after"),
          redacted_pdf_b64: PDF_B64,
        }),
      });
    const input = document.getElementById("pdfFile");
    Object.defineProperty(input, "files", {
      configurable: true,
      value: [new File(["synthetic"], "fixture.pdf", { type: "application/pdf" })],
    });

    input.dispatchEvent(new Event("change"));
    await flush();

    expect(fetch).toHaveBeenCalledWith(
      "/api/redact-pdf",
      expect.objectContaining({ method: "POST", body: expect.any(FormData) }),
    );
    expect(document.getElementById("cmpWrap").hidden).toBe(false);
    expect(document.getElementById("imgAfter").src).toContain("data:image/png;base64,");
    expect(document.getElementById("pdfDownload").hidden).toBe(false);

    document.getElementById("pdfDownload").click();

    expect(clickedDownloads).toEqual([{ href: "blob:aiguard-test", download: "redacted_fixture.pdf" }]);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:aiguard-test");
  });

  it("downloads the aggregate PDPA report with its fixed safe filename", async () => {
    fetch
      .mockResolvedValueOnce(response(healthBody()))
      .mockResolvedValueOnce(
        response({ report_pdf_b64: PDF_B64, overall_score: 12, overall_grade: "B" })
      );
    document.getElementById("editor").value = "synthetic acceptance input";

    document.getElementById("reportBtn").click();
    await flush();

    expect(fetch).toHaveBeenCalledWith(
      "/api/analyze-report",
      expect.objectContaining({ method: "POST" }),
    );
    expect(clickedDownloads).toEqual([{ href: "blob:aiguard-test", download: "pdpa_report.pdf" }]);
    expect(document.getElementById("meta").textContent).toContain("คะแนนรวม 12 เกรด B");
    expect(document.getElementById("reportBtn").disabled).toBe(false);
  });
});

describe("playground HTTP v2 boundary", () => {
  it("bypasses browser caches for contract discovery", () => {
    expect(fetch.mock.calls[0]).toEqual(["/api/health", { cache: "no-store" }]);
  });

  it("keeps PII controls disabled until exact health succeeds", async () => {
    document.body.innerHTML = "";
    fetch.mockReset();
    fetch.mockResolvedValueOnce(response(healthBody({ contract_version: 1 })));
    loadPlayground();
    await flush();

    expect(document.getElementById("send").disabled).toBe(true);
    expect(document.getElementById("reportBtn").disabled).toBe(true);
    expect(document.getElementById("pdfPick").disabled).toBe(true);
  });

  it("asserts v2 and writes a fully validated complete roundtrip", async () => {
    fetch
      .mockResolvedValueOnce(response(healthBody()))
      .mockResolvedValueOnce(response(roundtripBody()));
    document.getElementById("editor").value = "synthetic";

    document.getElementById("send").click();
    await flush();

    const operation = fetch.mock.calls.find(([url]) => url === "/api/roundtrip");
    expect(operation[1].headers).toEqual({
      "Content-Type": "application/json",
      [CONTRACT_HEADER]: "2",
    });
    expect(document.getElementById("masked").textContent).toBe("[ชื่อ_1]");
    expect(document.getElementById("restored").textContent).toBe("สวัสดี บุคคลทดสอบ");
  });

  it.each([
    ["unknown mapping field", roundtripBody({ original_text: "synthetic" }), "2"],
    [
      "unsafe safety",
      roundtripBody({ safety: { status: "pass", residual_count: 1 } }),
      "2",
    ],
    [
      "incomplete restoration",
      roundtripBody({
        restoration: { status: "incomplete", replaced_count: 0, leftover_count: 1 },
      }),
      "2",
    ],
    [
      "non-canonical Section 26 order",
      roundtripBody({
        section26_categories: ["HEALTH", "RACE_ETHNICITY"],
      }),
      "2",
    ],
    ["missing assertion", roundtripBody(), null],
  ])("does not place result text in the DOM after %s", async (_label, body, version) => {
    fetch
      .mockResolvedValueOnce(response(healthBody()))
      .mockResolvedValueOnce(response(body, { version }));
    document.getElementById("editor").value = "synthetic";
    const maskedBefore = document.getElementById("masked").textContent;
    const restoredBefore = document.getElementById("restored").textContent;

    document.getElementById("send").click();
    await flush();

    expect(document.getElementById("masked").textContent).toBe(maskedBefore);
    expect(document.getElementById("restored").textContent).toBe(restoredBefore);
  });

  it("converts detect code-point offsets before highlighting emoji and combining text", async () => {
    vi.useFakeTimers();
    fetch
      .mockResolvedValueOnce(response(healthBody()))
      .mockResolvedValueOnce(
        response({
          detected_entity_count: 1,
          entity_type_counts: { NAME: 1 },
          highlights: [{ start: 4, end: 12, data_type: "NAME", redact_type: "TB" }],
        })
      )
      .mockResolvedValueOnce(response(healthBody()))
      .mockResolvedValueOnce(
        response({ flagged: false, guard_findings: [] })
      );
    const editor = document.getElementById("editor");
    editor.value = "😀e\u0301 [ชื่อ_1]";
    editor.dispatchEvent(new Event("input"));

    await vi.advanceTimersByTimeAsync(400);
    await Promise.resolve();

    expect(document.getElementById("highlight").innerHTML).toContain(
      "<mark"
    );
    expect(document.getElementById("highlight").textContent).toContain("[ชื่อ_1]");
    vi.useRealTimers();
  });

  it("disables controls after a valid contract error and sends no next operation", async () => {
    fetch
      .mockResolvedValueOnce(response(healthBody()))
      .mockResolvedValueOnce(
        response(
          {
            error: {
              code: "contract_version_required",
              category: "contract",
              count: 0,
              retryable: false,
              status: 426,
            },
          },
          { ok: false, status: 426 }
        )
      );
    document.getElementById("editor").value = "synthetic";

    document.getElementById("send").click();
    await flush();

    expect(document.getElementById("send").disabled).toBe(true);
    expect(document.getElementById("reportBtn").disabled).toBe(true);
    expect(document.getElementById("pdfPick").disabled).toBe(true);
    const callCount = fetch.mock.calls.length;
    document.getElementById("send").click();
    await flush();
    expect(fetch).toHaveBeenCalledTimes(callCount);
  });
});
