import { afterEach, describe, expect, it, vi } from "vitest";

import { analyzeReport } from "../src/api.js";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("analyzeReport API", () => {
  it("posts the current text to the PDF report endpoint", async () => {
    const response = { report_pdf_b64: "JVBERi0=", overall_score: 10, overall_grade: "A" };
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: vi.fn().mockResolvedValue(response) });
    vi.stubGlobal("fetch", fetchMock);

    await expect(analyzeReport("ข้อความปัจจุบัน")).resolves.toEqual(response);
    expect(fetchMock).toHaveBeenCalledWith("http://127.0.0.1:8000/api/analyze-report", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: "ข้อความปัจจุบัน" }),
    });
  });
});
