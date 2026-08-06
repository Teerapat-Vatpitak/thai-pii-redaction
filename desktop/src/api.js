import {
  CONTRACT_HEADER,
  CONTRACT_VERSION,
  hasV2ResponseHeader,
  validateAnalyze,
  validateAnalyzeReport,
  validateAuditLog,
  validateErrorEnvelope,
  validateHealth,
  validateRedactPdf,
  validateReidentify,
  validateSanitize,
} from "./contract-v2.js";

const BASE = "http://127.0.0.1:8000";
let healthReady = false;

export class ApiError extends Error {
  constructor(code, status = 0) {
    super(`AI Guard request failed: ${code}`);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
  }
}

async function readJson(response) {
  try {
    return await response.json();
  } catch {
    throw new Error("invalid HTTP v2 response");
  }
}

function assertResponseHeader(response) {
  if (!hasV2ResponseHeader(response)) {
    healthReady = false;
    throw new Error("HTTP v2 contract response assertion failed");
  }
}

async function requestV2(path, options, validator) {
  // A sidecar restart can replace the process behind the same loopback URL.
  // Re-establish the exact contract before every operation that may carry PII.
  await health();
  const headers = {
    ...(options && options.headers ? options.headers : {}),
    [CONTRACT_HEADER]: CONTRACT_VERSION,
  };
  let response;
  try {
    response = await fetch(BASE + path, { ...options, headers });
  } catch {
    healthReady = false;
    throw new Error("AI Guard backend is unavailable");
  }
  assertResponseHeader(response);
  const body = await readJson(response);
  if (!response.ok) {
    const projected = validateErrorEnvelope(body, response.status);
    throw new ApiError(projected.error.code, projected.error.status);
  }
  try {
    return validator(body);
  } catch {
    healthReady = false;
    throw new Error("invalid HTTP v2 operation response");
  }
}

export async function health() {
  healthReady = false;
  let response;
  try {
    response = await fetch(BASE + "/api/health", { cache: "no-store" });
  } catch {
    throw new Error("AI Guard backend is unavailable");
  }
  assertResponseHeader(response);
  const body = await readJson(response);
  if (!response.ok) {
    const projected = validateErrorEnvelope(body, response.status);
    throw new ApiError(projected.error.code, projected.error.status);
  }
  let projected;
  try {
    projected = validateHealth(body);
  } catch {
    throw new Error("invalid HTTP v2 health response");
  }
  if (projected.capabilities.api_key_required) {
    throw new Error("AI Guard data-plane authentication is required");
  }
  healthReady = true;
  return projected;
}

export function sanitize(text, mode = "token", sessionId = null) {
  const body = { text, mode };
  if (typeof sessionId === "string" && sessionId.length > 0) {
    body.session_id = sessionId;
  }
  return requestV2(
    "/api/sanitize",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
    validateSanitize
  );
}

export function reidentify(sessionId, text) {
  return requestV2(
    "/api/reidentify",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, text }),
    },
    validateReidentify
  );
}

export function analyze(text) {
  return requestV2(
    "/api/analyze",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    },
    validateAnalyze
  );
}

export function analyzeReport(text) {
  return requestV2(
    "/api/analyze-report",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    },
    validateAnalyzeReport
  );
}

export function redactPdf(file) {
  const body = new FormData();
  body.append("pdf_file", file);
  return requestV2("/api/redact-pdf", { method: "POST", body }, validateRedactPdf);
}

export function auditLog(limit = 100, offset = 0) {
  if (
    !Number.isInteger(limit) ||
    limit < 1 ||
    limit > 1000 ||
    !Number.isInteger(offset) ||
    offset < 0
  ) {
    return Promise.reject(new Error("invalid audit pagination"));
  }
  return requestV2(
    `/api/audit-log?limit=${limit}&offset=${offset}`,
    { method: "GET" },
    validateAuditLog
  );
}
