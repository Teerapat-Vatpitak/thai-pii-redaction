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

type ResponseValidator<T> = (value: unknown) => T;
type JsonRecord = Record<string, unknown>;

function invalidResponse(): never {
  // Keep the thrown value generic: a backend response can contain document data.
  throw new Error("invalid response shape");
}

function record(value: unknown): JsonRecord {
  if (typeof value !== "object" || value === null || Array.isArray(value)) invalidResponse();
  return value as JsonRecord;
}

function stringValue(value: unknown, nonEmpty = false): string {
  if (typeof value !== "string" || (nonEmpty && value.length === 0)) invalidResponse();
  return value;
}

function nonNegativeInteger(value: unknown): number {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0) invalidResponse();
  return value;
}

function finiteNumber(value: unknown): number {
  if (typeof value !== "number" || !Number.isFinite(value)) invalidResponse();
  return value;
}

function stringArray(value: unknown): string[] {
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string")) invalidResponse();
  return value as string[];
}

function countMap(value: unknown): Record<string, number> {
  const counts = record(value);
  for (const count of Object.values(counts)) nonNegativeInteger(count);
  return counts as Record<string, number>;
}

function entities(value: unknown): EntityDto[] {
  if (!Array.isArray(value)) invalidResponse();
  for (const item of value) {
    const entity = record(item);
    const start = nonNegativeInteger(entity.start);
    const end = nonNegativeInteger(entity.end);
    if (end < start) invalidResponse();
    stringValue(entity.data_type, true);
    stringValue(entity.redact_type, true);
    if (entity.token !== undefined) stringValue(entity.token);
  }
  return value as EntityDto[];
}

function validateHealth(value: unknown): HealthResponse {
  const body = record(value);
  stringValue(body.status, true);
  stringValue(body.version, true);
  if (body.capabilities !== undefined) record(body.capabilities);
  return value as HealthResponse;
}

function validateDetect(value: unknown): DetectResponse {
  const body = record(value);
  entities(body.entities);
  countMap(body.entity_type_counts);
  return value as DetectResponse;
}

function validateAnalyze(value: unknown): AnalyzeResponse {
  const body = record(value);
  finiteNumber(body.overall_score);
  stringValue(body.overall_grade, true);
  stringValue(body.risk_label, true);
  nonNegativeInteger(body.direct_pii_count);
  stringArray(body.recommendations);
  return value as AnalyzeResponse;
}

function validateSanitize(value: unknown): SanitizeResponse {
  const body = record(value);
  stringValue(body.session_id, true);
  stringValue(body.sanitized_text);
  entities(body.entities);
  countMap(body.entity_type_counts);
  stringArray(body.warnings);
  return value as SanitizeResponse;
}

function validateReidentify(value: unknown): ReidentifyResponse {
  const body = record(value);
  stringValue(body.restored_text);
  nonNegativeInteger(body.replaced_count);
  stringArray(body.leftover_tokens);
  stringArray(body.warnings);
  return value as ReidentifyResponse;
}

function validateRoundtrip(value: unknown): RoundtripResponse {
  const body = record(value);
  stringValue(body.sanitized_text);
  stringValue(body.ai_response_masked);
  stringValue(body.restored_text);
  countMap(body.entity_type_counts);
  stringValue(body.provider_used, true);
  stringArray(body.warnings);
  if (body.entities !== undefined) entities(body.entities);
  return value as RoundtripResponse;
}

export class ApiClient implements AIGuardApi {
  constructor(
    private readonly baseUrl = "/api",
    private readonly fetcher: typeof fetch = fetch,
  ) {}

  async health(): Promise<HealthResponse> {
    return this.request("/health", { method: "GET" }, validateHealth);
  }

  async detect(text: string): Promise<DetectResponse> {
    return this.post("/detect", { text }, validateDetect);
  }

  async analyze(text: string): Promise<AnalyzeResponse> {
    return this.post("/analyze", { text }, validateAnalyze);
  }

  async sanitize(text: string, mode: GuardMode, sessionId?: string): Promise<SanitizeResponse> {
    return this.post("/sanitize", {
      text,
      mode,
      ...(sessionId ? { session_id: sessionId } : {}),
    }, validateSanitize);
  }

  async reidentify(sessionId: string, text: string): Promise<ReidentifyResponse> {
    return this.post("/reidentify", { session_id: sessionId, text }, validateReidentify);
  }

  async roundtrip(text: string, mode: GuardMode): Promise<RoundtripResponse> {
    return this.post("/roundtrip", { text, mode, provider: "pathumma" }, validateRoundtrip);
  }

  private post<T>(path: string, body: Record<string, unknown>, validate: ResponseValidator<T>): Promise<T> {
    return this.request(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }, validate);
  }

  private async request<T>(path: string, init: RequestInit, validate: ResponseValidator<T>): Promise<T> {
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
      return validate(await response.json());
    } catch {
      throw new ApiError(response.status, "รูปแบบคำตอบจาก AI Guard ไม่ถูกต้อง", "request");
    }
  }
}
