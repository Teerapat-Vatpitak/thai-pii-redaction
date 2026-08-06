import type { GuardMode } from "./types";

const CONTRACT_HEADER = "X-AIGuard-Contract-Version";
const CONTRACT_VERSION = "2";
const DATA_TYPE = /^[A-Z][A-Z0-9_]*$/u;

const GRADES = ["A", "B", "C", "D", "F"] as const;
const RISK_LABELS = [
  "Very Low Risk",
  "Low Risk",
  "Medium Risk",
  "High Risk",
  "Very High Risk",
] as const;
const REDACT_TYPES = ["FP", "TB"] as const;
const SECTION26_CATEGORIES = [
  "RACE_ETHNICITY",
  "POLITICAL_OPINION",
  "RELIGION",
  "HEALTH",
  "SEXUAL_BEHAVIOR",
  "CRIMINAL_RECORD",
  "DISABILITY",
  "LABOR_UNION",
] as const;
const GUARD_CATEGORIES = [
  "instruction_override",
  "role_hijack",
  "exfiltration",
  "hidden_chars",
  "suspicious_payload",
] as const;
const GUARD_SEVERITIES = ["low", "medium", "high"] as const;
const QI_CATEGORIES = [
  "gender",
  "date_of_birth",
  "age",
  "district",
  "province",
  "occupation",
  "religion",
] as const;
const RESTORE_WARNING_CODES = ["generated_pii", "foreign_replacement"] as const;
const RECOMMENDATION_TEMPLATES = [
  {
    level: "high",
    title: "Direct PII detected",
    desc: "ใช้ AI Guard เพื่อปกปิดข้อมูลทั้งหมดก่อนส่งให้ AI ภายนอก",
  },
  {
    level: "high",
    title: "Section 26 sensitive data detected",
    desc: "ต้องได้รับความยินยอมโดยชัดแจ้งจากเจ้าของข้อมูลก่อนประมวลผล ตาม PDPA มาตรา 26",
  },
  {
    level: "medium",
    title: "High re-identification risk",
    desc: "ลดการรวมข้อมูลกึ่งระบุตัวบุคคลก่อนนำข้อมูลไปใช้",
  },
  {
    level: "info",
    title: "Consider data minimization",
    desc: "เก็บเฉพาะข้อมูลที่จำเป็นตามวัตถุประสงค์ที่กำหนด ตาม PDPA มาตรา 22",
  },
  {
    level: "info",
    title: "No significant PDPA risk detected",
    desc: "ไม่พบข้อมูลส่วนบุคคลที่มีความเสี่ยงสูงในข้อความนี้",
  },
] as const;

type Grade = typeof GRADES[number];
type RiskLabel = typeof RISK_LABELS[number];
type RedactType = typeof REDACT_TYPES[number];
type Section26Category = typeof SECTION26_CATEGORIES[number];
type GuardCategory = typeof GUARD_CATEGORIES[number];
type GuardSeverity = typeof GUARD_SEVERITIES[number];
type QiCategory = typeof QI_CATEGORIES[number];
export type RestoreWarningCode = typeof RESTORE_WARNING_CODES[number];

export interface HighlightDto {
  start: number;
  end: number;
  data_type: string;
  redact_type: RedactType;
}

export interface GuardFindingDto {
  category: GuardCategory;
  severity: GuardSeverity;
}

export interface WarningDto {
  code: RestoreWarningCode;
  count: number;
}

export interface HealthResponse {
  status: "ok";
  version: string;
  contract_version: 2;
  capabilities: {
    control_token_required: boolean;
    api_key_required: boolean;
  };
}

export interface SanitizeResponse {
  session_id: string;
  sanitized_text: string;
  detected_entity_count: number;
  replacement_count: number;
  entity_type_counts: Record<string, number>;
  highlights: HighlightDto[];
  section26_categories: Section26Category[];
  guard_findings: GuardFindingDto[];
  warnings: WarningDto[];
  safety: {
    status: "pass";
    residual_count: 0;
  };
}

export interface ReidentifyResponse {
  restored_text: string;
  replaced_count: number;
  leftover_count: number;
  warnings: WarningDto[];
}

export interface DetectResponse {
  detected_entity_count: number;
  entity_type_counts: Record<string, number>;
  highlights: HighlightDto[];
}

export interface AnalyzeRecommendation {
  level: "high" | "medium" | "info";
  title: string;
  desc: string;
}

export interface AnalyzeResponse {
  overall_score: number;
  overall_grade: Grade;
  risk_label: RiskLabel;
  direct_pii_count: number;
  fp_count: number;
  tb_count: number;
  section26_categories: Section26Category[];
  reidentification: {
    score: number;
    grade: Grade;
    quasi_identifier_categories: QiCategory[];
    high_risk_combination: boolean;
  };
  breakdown: Array<{
    data_type: string;
    redact_type: RedactType;
    count: number;
  }>;
  recommendations: AnalyzeRecommendation[];
}

export interface RoundtripResponse {
  sanitized_text: string;
  ai_response_masked: string;
  restored_text: string;
  detected_entity_count: number;
  entity_type_counts: Record<string, number>;
  provider_used: "pathumma";
  section26_categories: Section26Category[];
  guard_findings: GuardFindingDto[];
  warnings: WarningDto[];
  safety: {
    status: "pass";
    residual_count: 0;
  };
  restoration: {
    status: "complete" | "incomplete" | "unsafe";
    replaced_count: number;
    leftover_count: number;
  };
}

export type ApiErrorCode =
  | "offline"
  | "contract"
  | "authentication"
  | "expired"
  | "privacy"
  | "missing-key"
  | "provider"
  | "request";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
    public readonly code: ApiErrorCode,
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

type JsonRecord = Record<string, unknown>;
type ResponseValidator<T> = (value: unknown) => T;

function invalidResponse(): never {
  // A backend response can contain document data, so the error stays constant.
  throw new Error("invalid response shape");
}

function record(value: unknown): JsonRecord {
  if (typeof value !== "object" || value === null || Array.isArray(value)) invalidResponse();
  return value as JsonRecord;
}

function exactRecord<const K extends readonly string[]>(
  value: unknown,
  keys: K,
): JsonRecord {
  const body = record(value);
  const actual = Object.keys(body);
  if (
    actual.length !== keys.length
    || keys.some((key) => !Object.prototype.hasOwnProperty.call(body, key))
  ) {
    invalidResponse();
  }
  return body;
}

function stringValue(value: unknown, nonEmpty = false): string {
  if (typeof value !== "string" || (nonEmpty && value.length === 0)) invalidResponse();
  return value;
}

function booleanValue(value: unknown): boolean {
  if (typeof value !== "boolean") invalidResponse();
  return value;
}

function nonNegativeInteger(value: unknown): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0) invalidResponse();
  return value;
}

function positiveInteger(value: unknown): number {
  const result = nonNegativeInteger(value);
  if (result === 0) invalidResponse();
  return result;
}

function score(value: unknown): number {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0 || value > 100) {
    invalidResponse();
  }
  return value;
}

function enumValue<const T extends readonly string[]>(value: unknown, allowed: T): T[number] {
  if (typeof value !== "string" || !allowed.includes(value)) invalidResponse();
  return value as T[number];
}

function orderedEnumArray<const T extends readonly string[]>(
  value: unknown,
  allowed: T,
): Array<T[number]> {
  if (!Array.isArray(value)) invalidResponse();
  let previous = -1;
  return value.map((item) => {
    const selected = enumValue(item, allowed);
    const index = allowed.indexOf(selected);
    if (index <= previous) invalidResponse();
    previous = index;
    return selected;
  });
}

function countMap(value: unknown): Record<string, number> {
  const counts = record(value);
  const projected: Record<string, number> = {};
  for (const [key, rawCount] of Object.entries(counts)) {
    if (!DATA_TYPE.test(key)) invalidResponse();
    projected[key] = positiveInteger(rawCount);
  }
  return projected;
}

function highlights(value: unknown, codePointLength: number): HighlightDto[] {
  if (!Array.isArray(value)) invalidResponse();
  let previousEnd = 0;
  return value.map((item) => {
    const entity = exactRecord(item, ["start", "end", "data_type", "redact_type"]);
    const start = nonNegativeInteger(entity.start);
    const end = positiveInteger(entity.end);
    const dataType = stringValue(entity.data_type, true);
    if (!DATA_TYPE.test(dataType)) invalidResponse();
    const redactType = enumValue(entity.redact_type, REDACT_TYPES);
    if (start < previousEnd || end <= start || end > codePointLength) invalidResponse();
    previousEnd = end;
    return {
      start,
      end,
      data_type: dataType,
      redact_type: redactType,
    };
  });
}

function section26Categories(value: unknown): Section26Category[] {
  return orderedEnumArray(value, SECTION26_CATEGORIES);
}

function guardFindings(value: unknown): GuardFindingDto[] {
  if (!Array.isArray(value)) invalidResponse();
  const seen = new Set<string>();
  return value.map((item) => {
    const finding = exactRecord(item, ["category", "severity"]);
    const category = enumValue(finding.category, GUARD_CATEGORIES);
    const severity = enumValue(finding.severity, GUARD_SEVERITIES);
    const key = `${category}:${severity}`;
    if (seen.has(key)) invalidResponse();
    seen.add(key);
    return { category, severity };
  });
}

function restoreWarnings(value: unknown): WarningDto[] {
  if (!Array.isArray(value)) invalidResponse();
  let previous = -1;
  return value.map((item) => {
    const warning = exactRecord(item, ["code", "count"]);
    const code = enumValue(warning.code, RESTORE_WARNING_CODES);
    const index = RESTORE_WARNING_CODES.indexOf(code);
    if (index <= previous) invalidResponse();
    previous = index;
    return { code, count: positiveInteger(warning.count) };
  });
}

function noWarnings(value: unknown): WarningDto[] {
  if (!Array.isArray(value) || value.length !== 0) invalidResponse();
  return [];
}

function safety(value: unknown): SanitizeResponse["safety"] {
  const body = exactRecord(value, ["status", "residual_count"]);
  if (body.status !== "pass" || body.residual_count !== 0) invalidResponse();
  return { status: "pass", residual_count: 0 };
}

function codePointLength(value: string): number {
  return Array.from(value).length;
}

export function codePointOffsetToUtf16(text: string, offset: number): number {
  if (!Number.isSafeInteger(offset) || offset < 0) invalidResponse();
  let codePoints = 0;
  let utf16 = 0;
  for (const character of text) {
    if (codePoints === offset) return utf16;
    codePoints += 1;
    utf16 += character.length;
  }
  if (codePoints === offset) return utf16;
  return invalidResponse();
}

function validateHealth(value: unknown): HealthResponse {
  const body = exactRecord(value, ["status", "version", "contract_version", "capabilities"]);
  if (body.status !== "ok" || body.contract_version !== 2) invalidResponse();
  const version = stringValue(body.version, true);
  const capabilities = exactRecord(
    body.capabilities,
    ["control_token_required", "api_key_required"],
  );
  return {
    status: "ok",
    version,
    contract_version: 2,
    capabilities: {
      control_token_required: booleanValue(capabilities.control_token_required),
      api_key_required: booleanValue(capabilities.api_key_required),
    },
  };
}

function validateDetect(value: unknown, input: string): DetectResponse {
  const body = exactRecord(
    value,
    ["detected_entity_count", "entity_type_counts", "highlights"],
  );
  const detectedEntityCount = nonNegativeInteger(body.detected_entity_count);
  const entityTypeCounts = countMap(body.entity_type_counts);
  const projectedHighlights = highlights(body.highlights, codePointLength(input));
  if (
    detectedEntityCount !== Object.values(entityTypeCounts).reduce((sum, count) => sum + count, 0)
    || detectedEntityCount !== projectedHighlights.length
  ) {
    invalidResponse();
  }
  return {
    detected_entity_count: detectedEntityCount,
    entity_type_counts: entityTypeCounts,
    highlights: projectedHighlights,
  };
}

function validateRecommendations(value: unknown): AnalyzeRecommendation[] {
  if (!Array.isArray(value) || value.length === 0) invalidResponse();
  let previous = -1;
  const projected = value.map((item) => {
    const recommendation = exactRecord(item, ["level", "title", "desc"]);
    const index = RECOMMENDATION_TEMPLATES.findIndex((template) => (
      template.level === recommendation.level
      && template.title === recommendation.title
      && template.desc === recommendation.desc
    ));
    if (index < 0 || index <= previous) invalidResponse();
    previous = index;
    const template = RECOMMENDATION_TEMPLATES[index];
    if (!template) invalidResponse();
    return {
      level: template.level,
      title: template.title,
      desc: template.desc,
    };
  });
  if (previous === RECOMMENDATION_TEMPLATES.length - 1 && projected.length !== 1) {
    invalidResponse();
  }
  return projected;
}

function validateAnalyze(value: unknown): AnalyzeResponse {
  const body = exactRecord(value, [
    "overall_score",
    "overall_grade",
    "risk_label",
    "direct_pii_count",
    "fp_count",
    "tb_count",
    "section26_categories",
    "reidentification",
    "breakdown",
    "recommendations",
  ]);
  const overallScore = score(body.overall_score);
  const overallGrade = enumValue(body.overall_grade, GRADES);
  const riskLabel = enumValue(body.risk_label, RISK_LABELS);
  const directPiiCount = nonNegativeInteger(body.direct_pii_count);
  const fpCount = nonNegativeInteger(body.fp_count);
  const tbCount = nonNegativeInteger(body.tb_count);
  const projectedSection26 = section26Categories(body.section26_categories);
  const reidentification = exactRecord(body.reidentification, [
    "score",
    "grade",
    "quasi_identifier_categories",
    "high_risk_combination",
  ]);
  const projectedReidentification = {
    score: score(reidentification.score),
    grade: enumValue(reidentification.grade, GRADES),
    quasi_identifier_categories: orderedEnumArray(
      reidentification.quasi_identifier_categories,
      QI_CATEGORIES,
    ),
    high_risk_combination: booleanValue(reidentification.high_risk_combination),
  };
  if (!Array.isArray(body.breakdown)) invalidResponse();
  const seenBreakdown = new Set<string>();
  const breakdown = body.breakdown.map((item) => {
    const row = exactRecord(item, ["data_type", "redact_type", "count"]);
    const dataType = stringValue(row.data_type, true);
    if (!DATA_TYPE.test(dataType)) invalidResponse();
    const redactType = enumValue(row.redact_type, REDACT_TYPES);
    const key = `${dataType}:${redactType}`;
    if (seenBreakdown.has(key)) invalidResponse();
    seenBreakdown.add(key);
    return {
      data_type: dataType,
      redact_type: redactType,
      count: positiveInteger(row.count),
    };
  });
  if (
    directPiiCount !== fpCount + tbCount
    || directPiiCount !== breakdown.reduce((sum, row) => sum + row.count, 0)
    || fpCount !== breakdown
      .filter((row) => row.redact_type === "FP")
      .reduce((sum, row) => sum + row.count, 0)
    || tbCount !== breakdown
      .filter((row) => row.redact_type === "TB")
      .reduce((sum, row) => sum + row.count, 0)
  ) {
    invalidResponse();
  }
  return {
    overall_score: overallScore,
    overall_grade: overallGrade,
    risk_label: riskLabel,
    direct_pii_count: directPiiCount,
    fp_count: fpCount,
    tb_count: tbCount,
    section26_categories: projectedSection26,
    reidentification: projectedReidentification,
    breakdown,
    recommendations: validateRecommendations(body.recommendations),
  };
}

function validateSanitize(value: unknown): SanitizeResponse {
  const body = exactRecord(value, [
    "session_id",
    "sanitized_text",
    "detected_entity_count",
    "replacement_count",
    "entity_type_counts",
    "highlights",
    "section26_categories",
    "guard_findings",
    "warnings",
    "safety",
  ]);
  const sessionId = stringValue(body.session_id, true);
  const sanitizedText = stringValue(body.sanitized_text, true);
  const detectedEntityCount = nonNegativeInteger(body.detected_entity_count);
  const replacementCount = nonNegativeInteger(body.replacement_count);
  const entityTypeCounts = countMap(body.entity_type_counts);
  const projectedHighlights = highlights(
    body.highlights,
    codePointLength(sanitizedText),
  );
  if (
    detectedEntityCount !== Object.values(entityTypeCounts).reduce((sum, count) => sum + count, 0)
    || replacementCount !== projectedHighlights.length
    || replacementCount < detectedEntityCount
  ) {
    invalidResponse();
  }
  return {
    session_id: sessionId,
    sanitized_text: sanitizedText,
    detected_entity_count: detectedEntityCount,
    replacement_count: replacementCount,
    entity_type_counts: entityTypeCounts,
    highlights: projectedHighlights,
    section26_categories: section26Categories(body.section26_categories),
    guard_findings: guardFindings(body.guard_findings),
    warnings: noWarnings(body.warnings),
    safety: safety(body.safety),
  };
}

function validateReidentify(value: unknown): ReidentifyResponse {
  const body = exactRecord(
    value,
    ["restored_text", "replaced_count", "leftover_count", "warnings"],
  );
  return {
    restored_text: stringValue(body.restored_text),
    replaced_count: nonNegativeInteger(body.replaced_count),
    leftover_count: nonNegativeInteger(body.leftover_count),
    warnings: restoreWarnings(body.warnings),
  };
}

function validateRoundtrip(value: unknown, selectedProvider: "pathumma"): RoundtripResponse {
  const body = exactRecord(value, [
    "sanitized_text",
    "ai_response_masked",
    "restored_text",
    "detected_entity_count",
    "entity_type_counts",
    "provider_used",
    "section26_categories",
    "guard_findings",
    "warnings",
    "safety",
    "restoration",
  ]);
  const detectedEntityCount = nonNegativeInteger(body.detected_entity_count);
  const entityTypeCounts = countMap(body.entity_type_counts);
  if (
    detectedEntityCount !== Object.values(entityTypeCounts).reduce((sum, count) => sum + count, 0)
    || body.provider_used !== selectedProvider
  ) {
    invalidResponse();
  }
  const warnings = restoreWarnings(body.warnings);
  const restoration = exactRecord(
    body.restoration,
    ["status", "replaced_count", "leftover_count"],
  );
  const status = enumValue(
    restoration.status,
    ["complete", "incomplete", "unsafe"] as const,
  );
  const replacedCount = nonNegativeInteger(restoration.replaced_count);
  const leftoverCount = nonNegativeInteger(restoration.leftover_count);
  const expectedStatus = warnings.length > 0
    ? "unsafe"
    : leftoverCount > 0
      ? "incomplete"
      : "complete";
  if (status !== expectedStatus) invalidResponse();
  return {
    sanitized_text: stringValue(body.sanitized_text, true),
    ai_response_masked: stringValue(body.ai_response_masked),
    restored_text: stringValue(body.restored_text),
    detected_entity_count: detectedEntityCount,
    entity_type_counts: entityTypeCounts,
    provider_used: selectedProvider,
    section26_categories: section26Categories(body.section26_categories),
    guard_findings: guardFindings(body.guard_findings),
    warnings,
    safety: safety(body.safety),
    restoration: {
      status,
      replaced_count: replacedCount,
      leftover_count: leftoverCount,
    },
  };
}

const ERROR_SPECS: Record<string, {
  status: number;
  category: string;
  retryable: boolean;
}> = {
  contract_version_required: { status: 426, category: "contract", retryable: false },
  invalid_request: { status: 400, category: "request", retryable: false },
  request_schema_invalid: { status: 422, category: "request", retryable: false },
  authentication_required: { status: 401, category: "authentication", retryable: false },
  control_forbidden: { status: 403, category: "authentication", retryable: false },
  route_not_found: { status: 404, category: "request", retryable: false },
  session_unavailable: { status: 404, category: "session", retryable: false },
  method_not_allowed: { status: 405, category: "request", retryable: false },
  rate_limited: { status: 429, category: "service", retryable: true },
  payload_too_large: { status: 413, category: "request", retryable: false },
  residual_pii: { status: 422, category: "privacy", retryable: false },
  document_invalid: { status: 422, category: "document", retryable: false },
  provider_unavailable: { status: 502, category: "upstream", retryable: true },
  provider_rejected: { status: 502, category: "upstream", retryable: false },
  provider_response_invalid: { status: 502, category: "upstream", retryable: false },
  ner_incomplete: { status: 502, category: "upstream", retryable: false },
  provider_configuration: { status: 503, category: "configuration", retryable: false },
  dependency_unavailable: { status: 503, category: "dependency", retryable: false },
  ocr_unavailable: { status: 503, category: "dependency", retryable: false },
  service_unavailable: { status: 503, category: "service", retryable: true },
  restore_failed: { status: 500, category: "internal", retryable: false },
  internal_error: { status: 500, category: "internal", retryable: false },
};

const COUNT_BEARING_ERROR_CODES = new Set([
  "request_schema_invalid",
  "residual_pii",
  "ner_incomplete",
  "ner_unavailable",
]);

interface SafeError {
  code: string;
  status: number;
}

function validateError(value: unknown, responseStatus: number): SafeError {
  const envelope = exactRecord(value, ["error"]);
  const error = exactRecord(
    envelope.error,
    ["code", "category", "count", "retryable", "status"],
  );
  const code = stringValue(error.code, true);
  const status = nonNegativeInteger(error.status);
  const category = stringValue(error.category, true);
  const retryable = booleanValue(error.retryable);
  const count = nonNegativeInteger(error.count);
  if (!COUNT_BEARING_ERROR_CODES.has(code) && count !== 0) invalidResponse();
  if (status !== responseStatus) invalidResponse();
  if (code === "ner_unavailable") {
    const validPair = (
      (category === "configuration" || category === "dependency") && !retryable
    ) || (
      (category === "network" || category === "upstream") && retryable
    );
    if (status !== 503 || !validPair) invalidResponse();
  } else {
    const spec = ERROR_SPECS[code];
    if (
      !spec
      || spec.status !== status
      || spec.category !== category
      || spec.retryable !== retryable
    ) {
      invalidResponse();
    }
  }
  return { code, status };
}

function contractError(status = 0): ApiError {
  return new ApiError(
    status,
    "AI Guard ใช้สัญญาการเชื่อมต่อที่ไม่รองรับ กรุณาอัปเดตและเปิด task pane ใหม่",
    "contract",
  );
}

function apiErrorFromSafe(error: SafeError): ApiError {
  if (error.code === "session_unavailable") {
    return new ApiError(
      error.status,
      "Session หมดอายุหรือไม่พบ ไม่สามารถเดาข้อมูลเดิมได้",
      "expired",
    );
  }
  if (error.code === "authentication_required") {
    return new ApiError(
      error.status,
      "Backend นี้ต้องใช้ API key แต่ Office Add-in ไม่อ่านหรือเก็บ credential",
      "authentication",
    );
  }
  if (error.code === "residual_pii") {
    return new ApiError(
      error.status,
      "ตรวจพบข้อมูลที่ยังปกปิดไม่ครบ จึงยกเลิกผลลัพธ์",
      "privacy",
    );
  }
  if (error.code === "provider_configuration") {
    return new ApiError(
      error.status,
      "Pathumma ยังไม่พร้อมหรือ backend ไม่มี API key",
      "missing-key",
    );
  }
  if (
    error.code.startsWith("provider_")
    || error.code.startsWith("ner_")
    || error.code === "dependency_unavailable"
    || error.code === "service_unavailable"
    || error.code === "rate_limited"
  ) {
    return new ApiError(
      error.status,
      "ผู้ให้บริการ AI ยังไม่พร้อม กรุณาลองใหม่",
      "provider",
    );
  }
  if (error.code === "contract_version_required") {
    return contractError(error.status);
  }
  return new ApiError(error.status, `คำขอล้มเหลว (HTTP ${error.status})`, "request");
}

export class ApiClient implements AIGuardApi {
  constructor(
    private readonly baseUrl = "/api",
    private readonly fetcher: typeof fetch = fetch,
  ) {}

  async health(): Promise<HealthResponse> {
    return this.request(
      "/health",
      { method: "GET" },
      validateHealth,
    );
  }

  async detect(text: string): Promise<DetectResponse> {
    return this.post("/detect", { text }, (value) => validateDetect(value, text));
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
    const provider = "pathumma" as const;
    return this.post(
      "/roundtrip",
      { text, mode, provider },
      (value) => validateRoundtrip(value, provider),
    );
  }

  private async post<T>(
    path: string,
    body: Record<string, unknown>,
    validate: ResponseValidator<T>,
  ): Promise<T> {
    const health = await this.health();
    if (health.capabilities.api_key_required) {
      throw new ApiError(
        0,
        "Backend นี้ต้องใช้ API key แต่ Office Add-in ไม่อ่านหรือเก็บ credential",
        "authentication",
      );
    }
    return this.request(path, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        [CONTRACT_HEADER]: CONTRACT_VERSION,
      },
      body: JSON.stringify(body),
    }, validate);
  }

  private async request<T>(
    path: string,
    init: RequestInit,
    validate: ResponseValidator<T>,
  ): Promise<T> {
    let response: Response;
    try {
      // Calling native fetch through an object property changes its receiver.
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

    if (response.headers.get(CONTRACT_HEADER) !== CONTRACT_VERSION) {
      throw contractError(response.status);
    }

    if (!response.ok) {
      let safeError: SafeError;
      try {
        safeError = validateError(await response.json(), response.status);
      } catch {
        throw new ApiError(
          response.status,
          "รูปแบบคำตอบจาก AI Guard ไม่ถูกต้อง",
          "contract",
        );
      }
      const error = apiErrorFromSafe(safeError);
      throw error;
    }

    try {
      return validate(await response.json());
    } catch {
      throw new ApiError(
        response.status,
        "รูปแบบคำตอบจาก AI Guard ไม่ถูกต้อง",
        "contract",
      );
    }
  }
}
