import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { analyzeReport } from "../src/api.js";

const invoke = vi.fn();

beforeEach(() => {
  invoke.mockReset();
  window.__TAURI__ = { core: { invoke } };
});

afterEach(() => {
  delete window.__TAURI__;
});

describe("analyzeReport native API", () => {
  it("sends current text only through the typed broker command", async () => {
    invoke.mockResolvedValue({
      operation: "analyze_report",
      result: { report_pdf_b64: "JVBERi0=", overall_score: "10", overall_grade: "A" },
    });

    await expect(analyzeReport("ข้อความปัจจุบัน")).resolves.toEqual({
      report_pdf_b64: "JVBERi0=",
      overall_score: 10,
      overall_grade: "A",
    });
    expect(invoke).toHaveBeenCalledWith("desktop_analyze_report", {
      text: "ข้อความปัจจุบัน",
    });
  });
});
