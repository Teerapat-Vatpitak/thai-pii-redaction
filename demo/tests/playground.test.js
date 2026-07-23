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

async function flush() {
  await Promise.resolve();
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

beforeEach(() => {
  clickedDownloads = [];
  vi.stubGlobal("fetch", vi.fn());
  vi.stubGlobal("URL", {
    createObjectURL: vi.fn(() => "blob:aiguard-test"),
    revokeObjectURL: vi.fn(),
  });
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function () {
    clickedDownloads.push({ href: this.href, download: this.download });
  });
  loadPlayground();
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  delete globalThis.meta;
  document.body.innerHTML = "";
});

describe("playground browser artifacts", () => {
  it("turns a successful PDF-redaction response into previews and a redacted download", async () => {
    fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        before_png_b64: btoa("png-before"),
        after_png_b64: btoa("png-after"),
        redacted_pdf_b64: PDF_B64,
        filename: "fixture.pdf",
        entity_count: 2,
        section26: [],
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
    expect(document.getElementById("imgBefore").src).toContain("data:image/png;base64,");
    expect(document.getElementById("imgAfter").src).toContain("data:image/png;base64,");
    expect(document.getElementById("pdfDownload").hidden).toBe(false);

    document.getElementById("pdfDownload").click();

    expect(clickedDownloads).toEqual([{ href: "blob:aiguard-test", download: "redacted_fixture.pdf" }]);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:aiguard-test");
  });

  it("downloads the aggregate PDPA report with its fixed safe filename", async () => {
    fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ report_pdf_b64: PDF_B64, overall_score: 12, overall_grade: "B" }),
    });
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
