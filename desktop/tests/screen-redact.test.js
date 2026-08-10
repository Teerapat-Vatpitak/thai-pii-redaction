import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../src/api.js", () => ({ redactPdf: vi.fn() }));

import { redactPdf } from "../src/api.js";
import { renderRedact } from "../src/screen-redact.js";

function response(fields) {
  return {
    source_type: "pdf_text",
    ocr_confidence: null,
    human_review: false,
    warnings: [],
    detected_entity_count: 2,
    entity_type_counts: { PHONE: 1, NAME: 1 },
    fields,
    section26_categories: [],
    redacted_pdf_b64: "JVBERg==",
    after_png_b64: "cG5n",
  };
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((onResolve, onReject) => {
    resolve = onResolve;
    reject = onReject;
  });
  return { promise, reject, resolve };
}

function selectFile(root, name) {
  const input = root.querySelector("#r-file");
  const file = new File(["synthetic"], name, { type: "application/pdf" });
  Object.defineProperty(input, "files", { configurable: true, value: [file] });
  input.dispatchEvent(new Event("change"));
  return file;
}

async function flush() {
  await new Promise((resolve) => setTimeout(resolve, 0));
}

async function uploadWith(fields) {
  const root = document.getElementById("root");
  renderRedact(root);
  redactPdf.mockResolvedValue(response(fields));

  const input = root.querySelector("#r-file");
  const file = new File(["synthetic"], "sample.pdf", { type: "application/pdf" });
  Object.defineProperty(input, "files", { configurable: true, value: [file] });
  input.dispatchEvent(new Event("change"));

  await vi.waitFor(() => expect(root.querySelector("#r-out").classList).not.toContain("hidden"));
  return root;
}

beforeEach(() => {
  document.body.innerHTML = '<div id="root"></div>';
  vi.clearAllMocks();
});

describe("desktop PDF redaction result", () => {
  it("renders only approved data_type labels and never response values", async () => {
    const root = await uploadWith([
      { data_type: "PHONE", redact_type: "FP", value: "081-234-5678" },
      { data_type: "NAME", redact_type: "TB", original: "นายทดสอบ ใจดี" },
      { data_type: "PHONE", value: "089-000-0000" },
      { data_type: '<img src=x onerror="window.__pwned=1">', value: "raw" },
      { data_type: { nested: "EMAIL" }, value: "person@example.com" },
      { value: "secret-only" },
      "raw primitive",
      null,
    ]);

    const labels = [...root.querySelectorAll("#r-fields .chip")].map((node) => node.textContent);
    expect(labels).toEqual(["PHONE (FP)", "NAME (TB)"]);
    expect(root.querySelector("#r-fields img")).toBeNull();
    expect(root.querySelector("#r-fields").textContent).not.toContain("081-234-5678");
    expect(root.querySelector("#r-fields").textContent).not.toContain("นายทดสอบ ใจดี");
    expect(root.querySelector("#r-fields").textContent).not.toContain("person@example.com");
    expect(root.querySelector("#r-fields").textContent).not.toContain("[object Object]");
  });

  it("handles a malformed non-array fields payload without failing the result", async () => {
    const root = await uploadWith({ data_type: "PHONE", value: "081-234-5678" });
    expect(root.querySelectorAll("#r-fields .chip")).toHaveLength(0);
    expect(root.querySelector("#r-err").classList).toContain("hidden");
  });

  it("uses a Thai download label", () => {
    const root = document.getElementById("root");
    renderRedact(root);
    expect(root.querySelector("#r-download").textContent).toBe("ดาวน์โหลด PDF ที่ปกปิดแล้ว");
  });

  it("states the installed local-only detector boundary", () => {
    const root = document.getElementById("root");
    renderRedact(root);
    expect(root.textContent).toContain("Desktop ที่ติดตั้งใช้ตัวตรวจจับในเครื่องเท่านั้น");
    expect(root.textContent).not.toContain("TNER");
    expect(root.textContent).not.toContain("บริการภายนอก");
  });

  it("publishes only the newest result when two files overlap", async () => {
    const root = document.getElementById("root");
    renderRedact(root);
    const first = deferred();
    const second = deferred();
    redactPdf.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);

    selectFile(root, "first.pdf");
    selectFile(root, "second.pdf");
    first.resolve({ ...response([]), source_type: "stale-first" });
    await flush();
    expect(root.querySelector("#r-out").classList).toContain("hidden");
    expect(root.querySelector("#r-filename").textContent).toBe("second.pdf");

    second.resolve({ ...response([]), source_type: "current-second" });
    await flush();
    expect(root.querySelector("#r-out").classList).not.toContain("hidden");
    expect(root.querySelector("#r-source-type").textContent).toBe("current-second");
  });

  it("does not retain a superseded document when the current request fails", async () => {
    const root = document.getElementById("root");
    renderRedact(root);
    const first = deferred();
    const second = deferred();
    redactPdf.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    const anchorClick = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

    selectFile(root, "first.pdf");
    selectFile(root, "second.pdf");
    first.resolve(response([]));
    await flush();
    second.reject(new Error("synthetic failure"));
    await flush();

    expect(root.querySelector("#r-out").classList).toContain("hidden");
    expect(root.querySelector("#r-after").hasAttribute("src")).toBe(false);
    root.querySelector("#r-download").click();
    expect(anchorClick).not.toHaveBeenCalled();
  });

  it("drops a pending result after the PDF screen is unmounted", async () => {
    const root = document.getElementById("root");
    renderRedact(root);
    const request = deferred();
    redactPdf.mockReturnValueOnce(request.promise);

    selectFile(root, "abandoned.pdf");
    root.replaceChildren(document.createTextNode("หน้าจออื่น"));
    request.resolve(response([]));
    await flush();

    expect(root.textContent).toBe("หน้าจออื่น");
  });
});
