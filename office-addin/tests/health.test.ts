import { describe, expect, it } from "vitest";
import { evaluateBackendHealth } from "../src/health";

describe("evaluateBackendHealth", () => {
  it("enables the task pane only for a healthy local backend", () => {
    expect(evaluateBackendHealth({ status: "ok", version: "2.4.0", capabilities: { token_required: false } })).toEqual({
      ready: true,
      message: "AI Guard พร้อมใช้งาน · 2.4.0",
    });
  });

  it("fails closed when the backend requires a credential channel the add-in does not have", () => {
    const result = evaluateBackendHealth({ status: "ok", version: "2.4.0", capabilities: { token_required: true } });
    expect(result.ready).toBe(false);
    expect(result.message).toContain("ไม่อ่านหรือเก็บ credential");
  });

  it("fails closed for an unhealthy status", () => {
    expect(evaluateBackendHealth({ status: "degraded", version: "2.4.0" }).ready).toBe(false);
  });
});
