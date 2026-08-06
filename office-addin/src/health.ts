import type { HealthResponse } from "./api";

export interface BackendAvailability {
  ready: boolean;
  message: string;
}

export function evaluateBackendHealth(health: HealthResponse): BackendAvailability {
  if (health.capabilities.api_key_required) {
    return {
      ready: false,
      message: "Backend นี้ต้องใช้ API key แต่ Office Add-in ไม่อ่านหรือเก็บ credential กรุณาเปิด AI Guard แบบ local",
    };
  }
  return { ready: true, message: `AI Guard พร้อมใช้งาน · ${health.version}` };
}
