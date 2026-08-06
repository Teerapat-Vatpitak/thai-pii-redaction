import { afterEach, describe, expect, it, vi } from "vitest";

import { analyzeReport } from "../src/api.js";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("analyzeReport API", () => {
  it("posts the current text to the PDF report endpoint", async () => {
    const response = { report_pdf_b64: "JVBERi0=", overall_score: 10, overall_grade: "A" };
    const headers = {
      get: (name) => (name.toLowerCase() === "x-aiguard-contract-version" ? "2" : null),
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        headers,
        json: vi.fn().mockResolvedValue({
          status: "ok",
          version: "2.5.0",
          contract_version: 2,
          capabilities: { control_token_required: true, api_key_required: false },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        headers,
        json: vi.fn().mockResolvedValue(response),
      });
    vi.stubGlobal("fetch", fetchMock);

    await expect(analyzeReport("ข้อความปัจจุบัน")).resolves.toEqual(response);
    expect(fetchMock).toHaveBeenLastCalledWith("http://127.0.0.1:8000/api/analyze-report", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-AIGuard-Contract-Version": "2",
      },
      body: JSON.stringify({ text: "ข้อความปัจจุบัน" }),
    });
  });
});
