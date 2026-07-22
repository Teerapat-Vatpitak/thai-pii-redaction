import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../src/api.js", () => ({ analyze: vi.fn(), analyzeReport: vi.fn() }));

import { analyzeReport } from "../src/api.js";
import { renderReport } from "../src/screen-report.js";

const PDF_B64 = btoa("%PDF-test");

async function flush() {
  // One task settles the mocked request; the next lets the download helper
  // revoke its object URL after the WebView has consumed the click.
  await new Promise((resolve) => setTimeout(resolve, 0));
  await new Promise((resolve) => setTimeout(resolve, 0));
}

function mount(text = "ข้อความทดสอบ") {
  document.body.innerHTML = "<div id='root'></div>";
  const root = document.getElementById("root");
  renderReport(root);
  const input = root.querySelector("#a-input");
  input.value = text;
  input.dispatchEvent(new Event("input", { bubbles: true }));
  return root;
}

beforeEach(() => {
  vi.clearAllMocks();
  Object.defineProperty(URL, "createObjectURL", {
    configurable: true,
    value: vi.fn(() => "blob:pdpa-report"),
  });
  Object.defineProperty(URL, "revokeObjectURL", {
    configurable: true,
    value: vi.fn(),
  });
});

afterEach(() => {
  vi.restoreAllMocks();
  delete URL.createObjectURL;
  delete URL.revokeObjectURL;
});

describe("Desktop PDPA PDF report download", () => {
  it("requests the current input and downloads a PDF with a fixed safe filename", async () => {
    const root = mount("  ข้อความปัจจุบัน  ");
    analyzeReport.mockResolvedValue({ report_pdf_b64: PDF_B64, overall_score: 10, overall_grade: "A" });
    let clickedDownload = null;
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function () {
      clickedDownload = { download: this.download, href: this.href };
    });

    root.querySelector("#a-download").click();
    await flush();

    expect(analyzeReport).toHaveBeenCalledWith("ข้อความปัจจุบัน");
    expect(URL.createObjectURL).toHaveBeenCalledOnce();
    expect(URL.createObjectURL.mock.calls[0][0]).toBeInstanceOf(Blob);
    expect(URL.createObjectURL.mock.calls[0][0].type).toBe("application/pdf");
    expect(clickedDownload).toEqual({
      download: "aiguard-pdpa-report.pdf",
      href: "blob:pdpa-report",
    });
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:pdpa-report");
    expect(root.querySelector("#a-status").textContent).toContain("ดาวน์โหลดรายงาน PDPA PDF แล้ว");
    expect(root.querySelector("#a-status").classList.contains("banner--ok")).toBe(true);
  });

  it("shows Thai busy state while the report is being created", async () => {
    const root = mount();
    let resolveRequest;
    analyzeReport.mockReturnValue(new Promise((resolve) => (resolveRequest = resolve)));

    root.querySelector("#a-download").click();
    expect(root.querySelector("#a-download").disabled).toBe(true);
    expect(root.querySelector("#a-download").textContent).toBe("กำลังสร้าง PDF...");
    expect(root.querySelector("#a-status").textContent).toContain("กำลังสร้างรายงาน PDPA PDF");

    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    resolveRequest({ report_pdf_b64: PDF_B64 });
    await flush();
    expect(root.querySelector("#a-download").disabled).toBe(false);
    expect(root.querySelector("#a-download").textContent).toBe("ดาวน์โหลดรายงาน PDF");
  });

  it("renders backend failures as text and does not start a download", async () => {
    const root = mount();
    analyzeReport.mockRejectedValue(new Error('<img src=x onerror="window.__pwned=1">'));

    root.querySelector("#a-download").click();
    await flush();

    expect(URL.createObjectURL).not.toHaveBeenCalled();
    expect(root.querySelector("#a-err").textContent).toContain("สร้างรายงาน PDF ไม่สำเร็จ");
    expect(root.querySelector("#a-err img")).toBeNull();
    expect(root.querySelector("#a-download").disabled).toBe(false);
  });

  it("drops a pending result when the report screen is no longer mounted", async () => {
    const root = mount();
    let resolveRequest;
    analyzeReport.mockReturnValue(new Promise((resolve) => (resolveRequest = resolve)));
    const anchorClick = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

    root.querySelector("#a-download").click();
    root.replaceChildren(document.createTextNode("หน้าจออื่น"));
    resolveRequest({ report_pdf_b64: PDF_B64 });
    await flush();

    expect(URL.createObjectURL).not.toHaveBeenCalled();
    expect(anchorClick).not.toHaveBeenCalled();
    expect(root.textContent).toBe("หน้าจออื่น");
  });
});
