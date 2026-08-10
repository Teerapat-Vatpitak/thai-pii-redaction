// DESK-4: numeric-looking fields from the backend must not reach innerHTML
// unescaped. A squatted backend (DESK-2) can return a string where a number is
// expected; `${b.count}` / `${r.direct_pii_count}` then inject markup into a
// webview that holds IPC grants (DESK-3) — count fields must be coerced or
// escaped like every other field on this screen already is.
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../src/api.js", () => ({ analyze: vi.fn(), analyzeReport: vi.fn() }));

import { analyze } from "../src/api.js";
import { renderReport } from "../src/screen-report.js";

const XSS = '<img src=x onerror="window.__pwned=1">';

function maliciousReport() {
  return {
    overall_score: 42.0,
    overall_grade: "C",
    risk_label: "Medium Risk",
    direct_pii_count: XSS,
    fp_count: 0,
    tb_count: 0,
    reidentification: {
      score: 10.0,
      grade: "B",
      quasi_identifier_categories: [],
      high_risk_combination: false,
    },
    section26_categories: [],
    breakdown: [{ data_type: "PHONE", redact_type: "FP", count: XSS }],
    recommendations: [],
  };
}

async function renderWithMaliciousBackend() {
  document.body.innerHTML = "<div id='root'></div>";
  const root = document.getElementById("root");
  renderReport(root);
  analyze.mockResolvedValueOnce(maliciousReport());
  root.querySelector("#a-input").value = "ข้อความทดสอบ";
  root.querySelector("#a-go").click();
  await new Promise((r) => setTimeout(r, 0));
  return root;
}

beforeEach(() => {
  vi.resetAllMocks();
});

describe("screen-report count fields (DESK-4)", () => {
  it("does not let a string count from the backend become markup", async () => {
    const root = await renderWithMaliciousBackend();
    expect(root.querySelector("#a-out img")).toBeNull();
    expect(root.querySelector("#a-out").innerHTML).not.toContain("<img");
  });

  it("clears a prior report before a later analysis and keeps it cleared on failure", async () => {
    const root = await renderWithMaliciousBackend();
    expect(root.querySelector("#a-out .stat-band")).not.toBeNull();

    let rejectRequest;
    analyze.mockReturnValueOnce(
      new Promise((_resolve, reject) => {
        rejectRequest = reject;
      })
    );
    root.querySelector("#a-go").click();
    expect(root.querySelector("#a-out").textContent).toBe("");

    rejectRequest(new Error("synthetic failure"));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(root.querySelector("#a-out").textContent).toBe("");
    expect(root.querySelector("#a-err").classList).not.toContain("hidden");
  });
});
