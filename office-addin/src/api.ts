import type { GuardMode } from "./types";

export interface EntityDto {
  start: number;
  end: number;
  data_type: string;
  redact_type: string;
  token?: string;
}

export interface HealthResponse {
  status: string;
  version: string;
  capabilities?: Record<string, unknown>;
}

export interface SanitizeResponse {
  session_id: string;
  sanitized_text: string;
  entities: EntityDto[];
  entity_type_counts: Record<string, number>;
  warnings: string[];
}

export interface ReidentifyResponse {
  restored_text: string;
  replaced_count: number;
  leftover_tokens: string[];
  warnings: string[];
}

export interface DetectResponse {
  entities: EntityDto[];
  entity_type_counts: Record<string, number>;
}

export interface AnalyzeResponse {
  overall_score: number;
  overall_grade: string;
  risk_label: string;
  direct_pii_count: number;
  recommendations: string[];
}

export interface RoundtripResponse {
  sanitized_text: string;
  ai_response_masked: string;
  restored_text: string;
  entity_type_counts: Record<string, number>;
  provider_used: string;
  warnings: string[];
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
    public readonly code: "offline" | "expired" | "missing-key" | "provider" | "request",
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export interface AIGuardApi {
  health(): Promise<HealthResponse>;
  detect(text: string): Promise<DetectResponse>;
  analyze(text: string): Promise<AnalyzeResponse>;
  sanitize(text: string, mode: GuardMode, sessionId?: string): Promise<SanitizeResponse>;
  reidentify(sessionId: string, text: string): Promise<ReidentifyResponse>;
  roundtrip(text: string, mode: GuardMode): Promise<RoundtripResponse>;
}

export class ApiClient implements AIGuardApi {
  constructor(
    private readonly baseUrl = "/api",
    private readonly fetcher: typeof fetch = fetch,
  ) {}

  async health(): Promise<HealthResponse> {
    return this.request<HealthResponse>("/health", { method: "GET" });
  }

  async detect(text: string): Promise<DetectResponse> {
    return this.post<DetectResponse>("/detect", { text });
  }

  async analyze(text: string): Promise<AnalyzeResponse> {
    return this.post<AnalyzeResponse>("/analyze", { text });
  }

  async sanitize(text: string, mode: GuardMode, sessionId?: string): Promise<SanitizeResponse> {
    return this.post<SanitizeResponse>("/sanitize", {
      text,
      mode,
      ...(sessionId ? { session_id: sessionId } : {}),
    });
  }

  async reidentify(sessionId: string, text: string): Promise<ReidentifyResponse> {
    return this.post<ReidentifyResponse>("/reidentify", { session_id: sessionId, text });
  }

  async roundtrip(text: string, mode: GuardMode): Promise<RoundtripResponse> {
    return this.post<RoundtripResponse>("/roundtrip", { text, mode, provider: "pathumma" });
  }

  private post<T>(path: string, body: Record<string, unknown>): Promise<T> {
    return this.request<T>(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  }

  private async request<T>(path: string, init: RequestInit): Promise<T> {
    let response: Response;
    try {
      // Calling a native Window.fetch through an object property changes its
      // receiver to ApiClient. WebView2 rejects that with "Illegal invocation".
      // Detach it before calling so the browser supplies the correct receiver.
      const requestFetch = this.fetcher;
      response = await requestFetch(`${this.baseUrl}${path}`, {
        ...init,
        credentials: "omit",
        cache: "no-store",
      });
    } catch {
      throw new ApiError(
        0,
        "ติดต่อ AI Guard ไม่ได้ กรุณาเปิดแอป AI Guard แล้วลองใหม่",
        "offline",
      );
    }

    if (!response.ok) {
      const status = response.status;
      if (path === "/health") {
        throw new ApiError(status, "ติดต่อ AI Guard ไม่ได้ กรุณาเปิดแอป AI Guard แล้วลองใหม่", "offline");
      }
      if (path === "/reidentify" && (status === 404 || status === 410)) {
        throw new ApiError(status, "Session หมดอายุหรือไม่พบ ไม่สามารถเดาข้อมูลเดิมได้", "expired");
      }
      if (path === "/roundtrip" && status === 503) {
        throw new ApiError(status, "Pathumma ยังไม่พร้อมหรือ backend ไม่มี API key", "missing-key");
      }
      if (path === "/roundtrip" && status === 502) {
        throw new ApiError(status, "Pathumma ตอบกลับล้มเหลว กรุณาลองใหม่", "provider");
      }
      throw new ApiError(status, `คำขอล้มเหลว (HTTP ${status})`, "request");
    }

    try {
      return (await response.json()) as T;
    } catch {
      throw new ApiError(response.status, "รูปแบบคำตอบจาก AI Guard ไม่ถูกต้อง", "request");
    }
  }
}
