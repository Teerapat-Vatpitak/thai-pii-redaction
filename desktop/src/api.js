const BASE = "http://127.0.0.1:8000";

async function j(path, opts) {
  const res = await fetch(BASE + path, opts);
  if (!res.ok) throw new Error(`${path} -> HTTP ${res.status}`);
  return res.json();
}

export function health() {
  return j("/api/health");
}

export function sanitize(text, mode = "token") {
  return j("/api/sanitize", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, mode }),
  });
}

export function reidentify(sessionId, text) {
  return j("/api/reidentify", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, text }),
  });
}

export function analyze(text) {
  return j("/api/analyze", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
}

export function redactPdf(file) {
  const fd = new FormData();
  fd.append("pdf_file", file);
  return j("/api/redact-pdf", { method: "POST", body: fd });
}

export function auditLog(limit = 100, offset = 0) {
  return j(`/api/audit-log?limit=${limit}&offset=${offset}`);
}
