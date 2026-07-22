import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../src/api.js", () => ({ redactPdf: vi.fn() }));

import { redactPdf } from "../src/api.js";
import { renderRedact } from "../src/screen-redact.js";

function response(fields) {
  return {
    filename: "sample.pdf",
    source_type: "pdf_text",
    ocr_confidence: null,
    human_review: false,
    entity_count: 2,
    fields,
    redacted_pdf_b64: "JVBERg==",
    before_png_b64: "",
    after_png_b64: "",
  };
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
    expect(labels).toEqual(["PHONE", "NAME"]);
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
});
