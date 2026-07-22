// DESK-4: numeric-looking fields from the backend must not reach innerHTML
// unescaped. A squatted backend (DESK-2) can return a string where a number is
// expected; `${b.count}` / `${r.direct_pii_count}` then inject markup into a
// webview that holds IPC grants (DESK-3) — count fields must be coerced or
// escaped like every other field on this screen already is.
import { describe, expect, it, vi } from "vitest";

vi.mock("../src/api.js", () => ({ analyze: vi.fn(), analyzeReport: vi.fn() }));

import { analyze } from "../src/api.js";
import { renderReport } from "../src/screen-report.js";

const XSS = '<img src=x onerror="window.__pwned=1">';

function maliciousReport() {
  return {
    overall_score: 42.0,
    overall_grade: "C",
    risk_label: "ปานกลาง",
    direct_pii_count: XSS,
    reid: { score: 10.0, grade: "B", high_risk_combo: false },
    section26: [],
    breakdown: [{ data_type: "PHONE", redact_type: "FP", count: XSS }],
    recommendations: [],
  };
}

async function renderWithMaliciousBackend() {
  document.body.innerHTML = "<div id='root'></div>";
  const root = document.getElementById("root");
  renderReport(root);
  analyze.mockResolvedValue(maliciousReport());
  root.querySelector("#a-input").value = "ข้อความทดสอบ";
  root.querySelector("#a-go").click();
  await new Promise((r) => setTimeout(r, 0));
  return root;
}

describe("screen-report count fields (DESK-4)", () => {
  it("does not let a string count from the backend become markup", async () => {
    const root = await renderWithMaliciousBackend();
    expect(root.querySelector("#a-out img")).toBeNull();
    expect(root.querySelector("#a-out").innerHTML).not.toContain("<img");
  });
});
