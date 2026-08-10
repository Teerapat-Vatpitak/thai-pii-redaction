import {
  validateAnalyze,
  validateAnalyzeReport,
  validateAuditLog,
  validateBrokerHealth,
  validateRedactPdf,
  validateReidentify,
  validateSanitize,
} from "./contract-v2.js";
import { ApiError } from "./errors.js";

export { ApiError } from "./errors.js";

export const MAX_PDF_RAW_BYTES_V1 = 52_428_800;

function nativeInvoke() {
  const invoke = window.__TAURI__?.core?.invoke;
  if (typeof invoke !== "function") {
    throw new ApiError("broker_unavailable", { restartRequired: true });
  }
  return invoke;
}

function projectNativeError(value) {
  if (
    value !== null &&
    typeof value === "object" &&
    !Array.isArray(value) &&
    Object.keys(value).every((key) =>
      ["code", "sessionInvalidated", "restartRequired"].includes(key)
    ) &&
    typeof value.code === "string" &&
    typeof value.sessionInvalidated === "boolean" &&
    typeof value.restartRequired === "boolean"
  ) {
    return new ApiError(value.code, value);
  }
  return new ApiError("operation_failed", {
    sessionInvalidated: true,
    restartRequired: true,
  });
}

function exactEnvelope(value, operation) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("invalid native broker response");
  }
  const keys = Object.keys(value).sort();
  if (
    keys.length !== 2 ||
    keys[0] !== "operation" ||
    keys[1] !== "result" ||
    value.operation !== operation
  ) {
    throw new Error("invalid native broker response");
  }
  return value.result;
}

async function attemptScopeReset() {
  try {
    await nativeInvoke()("desktop_scope_reset");
  } catch {
    // The native boundary owns fail-closed teardown when cleanup is unconfirmed.
  }
}

async function request(command, operation, args, validator) {
  let envelope;
  try {
    envelope = args === undefined
      ? await nativeInvoke()(command)
      : await nativeInvoke()(command, args);
  } catch (error) {
    const failure = error instanceof ApiError ? error : projectNativeError(error);
    if (failure.sessionInvalidated && operation !== "scope_close") {
      await attemptScopeReset();
    }
    throw failure;
  }
  try {
    const result = exactEnvelope(envelope, operation);
    return validator(result);
  } catch {
    if (operation !== "broker_health" && operation !== "scope_close") {
      await attemptScopeReset();
    }
    throw new ApiError("operation_failed", {
      sessionInvalidated: operation !== "broker_health",
      restartRequired: true,
    });
  }
}

export function health() {
  return request(
    "desktop_health",
    "broker_health",
    undefined,
    validateBrokerHealth
  );
}
export function analyze(text) {
  return request("desktop_analyze", "analyze", { text }, validateAnalyze);
}

export function sanitize(text, mode = "token", sessionId = null) {
  const args = { text, mode };
  if (typeof sessionId === "string" && sessionId.length > 0) {
    args.sessionId = sessionId;
  }
  return request("desktop_sanitize", "sanitize", args, validateSanitize);
}

export function reidentify(sessionId, text) {
  return request(
    "desktop_reidentify",
    "reidentify",
    { sessionId, text },
    validateReidentify
  );
}

export function copyMasked(sessionId, text) {
  return request(
    "desktop_copy_masked",
    "copy_masked",
    { sessionId, text },
    (value) => {
      if (
        value === null ||
        typeof value !== "object" ||
        Array.isArray(value) ||
        Object.keys(value).length !== 1 ||
        value.copied !== true
      ) {
        throw new Error("invalid masked-copy response");
      }
      return { copied: true };
    }
  );
}

export function analyzeReport(text) {
  return request(
    "desktop_analyze_report",
    "analyze_report",
    { text },
    validateAnalyzeReport
  );
}

function bytesToBase64(bytes) {
  let binary = "";
  const chunkSize = 32 * 1024;
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + chunkSize));
  }
  return btoa(binary);
}

export async function redactPdf(file) {
  if (
    !(file instanceof File) ||
    file.type !== "application/pdf" ||
    file.size === 0 ||
    file.size > MAX_PDF_RAW_BYTES_V1
  ) {
    throw new ApiError(
      file?.size > MAX_PDF_RAW_BYTES_V1
        ? "payload_too_large"
        : "document_invalid"
    );
  }
  const bytes = new Uint8Array(await file.arrayBuffer());
  if (bytes.length !== file.size) {
    throw new ApiError("document_invalid");
  }
  return request(
    "desktop_redact_pdf",
    "redact_pdf",
    { pdfB64: bytesToBase64(bytes) },
    validateRedactPdf
  );
}

export function auditLog(limit = 100, offset = 0) {
  if (
    !Number.isInteger(limit) ||
    limit < 1 ||
    limit > 1000 ||
    !Number.isInteger(offset) ||
    offset < 0
  ) {
    return Promise.reject(new ApiError("request_invalid"));
  }
  return request(
    "desktop_audit_log",
    "audit_log",
    { limit, offset },
    validateAuditLog
  );
}

export function disposeSession(sessionId) {
  return request(
    "desktop_session_dispose",
    "session_dispose",
    { sessionId },
    (value) => {
      if (
        value === null ||
        typeof value !== "object" ||
        Array.isArray(value) ||
        Object.keys(value).length !== 1 ||
        value.disposed !== true
      ) {
        throw new Error("invalid session disposal response");
      }
      return { disposed: true };
    }
  );
}

export function resetScope() {
  return request(
    "desktop_scope_reset",
    "scope_close",
    undefined,
    (value) => {
      if (
        value === null ||
        typeof value !== "object" ||
        Array.isArray(value) ||
        Object.keys(value).length !== 1 ||
        value.closed !== true
      ) {
        throw new Error("invalid scope close response");
      }
      return { closed: true };
    }
  );
}

export function rotateScope() {
  return request(
    "desktop_scope_rotate",
    "scope_rotate",
    undefined,
    (value) => {
      if (
        value === null ||
        typeof value !== "object" ||
        Array.isArray(value) ||
        Object.keys(value).length !== 1 ||
        value.rotated !== true
      ) {
        throw new Error("invalid scope rotation response");
      }
      return { rotated: true };
    }
  );
}
