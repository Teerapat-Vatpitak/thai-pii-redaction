import { describe, expect, it } from "vitest";
import type { HealthResponse } from "../src/api";
import { evaluateBackendHealth } from "../src/health";

function health(
  controlTokenRequired: boolean,
  apiKeyRequired: boolean,
): HealthResponse {
  return {
    status: "ok",
    version: "2.5.0",
    contract_version: 2,
    capabilities: {
      control_token_required: controlTokenRequired,
      api_key_required: apiKeyRequired,
    },
  };
}

describe("evaluateBackendHealth", () => {
  it.each([
    [false, false, true],
    [true, false, true],
    [false, true, false],
    [true, true, false],
  ])(
    "separates control-token and API-key readiness (%s, %s)",
    (controlTokenRequired, apiKeyRequired, ready) => {
      const result = evaluateBackendHealth(health(controlTokenRequired, apiKeyRequired));
      expect(result.ready).toBe(ready);
      if (ready) {
        expect(result.message).toBe("AI Guard พร้อมใช้งาน · 2.5.0");
      } else {
        expect(result.message).toContain("ไม่อ่านหรือเก็บ credential");
      }
    },
  );
});
