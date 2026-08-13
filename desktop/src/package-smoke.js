import {
  analyze,
  analyzeReport,
  auditLog,
  copyMasked,
  disposeSession,
  health,
  redactPdf,
  reidentify,
  resetScope,
  sanitize,
} from "./api.js";
import { ApiError } from "./errors.js";

const SOURCE = "Synthetic contact 081-234-5678";
const CONTINUATION = "Synthetic follow-up 089-876-5432";
const SAMPLE_PDF_B64 =
  "JVBERi0xLjMKJZOMi54gUmVwb3J0TGFiIEdlbmVyYXRlZCBQREYgZG9jdW1lbnQgKG9wZW5zb3VyY2UpCjEgMCBvYmoKPDwKL0YxIDIgMCBSCj4+CmVuZG9iagoyIDAgb2JqCjw8Ci9CYXNlRm9udCAvSGVsdmV0aWNhIC9FbmNvZGluZyAvV2luQW5zaUVuY29kaW5nIC9OYW1lIC9GMSAvU3VidHlwZSAvVHlwZTEgL1R5cGUgL0ZvbnQKPj4KZW5kb2JqCjMgMCBvYmoKPDwKL0NvbnRlbnRzIDcgMCBSIC9NZWRpYUJveCBbIDAgMCAzMDAgMjAwIF0gL1BhcmVudCA2IDAgUiAvUmVzb3VyY2VzIDw8Ci9Gb250IDEgMCBSIC9Qcm9jU2V0IFsgL1BERiAvVGV4dCAvSW1hZ2VCIC9JbWFnZUMgL0ltYWdlSSBdCj4+IC9Sb3RhdGUgMCAvVHJhbnMgPDwKCj4+IAogIC9UeXBlIC9QYWdlCj4+CmVuZG9iago0IDAgb2JqCjw8Ci9QYWdlTW9kZSAvVXNlTm9uZSAvUGFnZXMgNiAwIFIgL1R5cGUgL0NhdGFsb2cKPj4KZW5kb2JqCjUgMCBvYmoKPDwKL0F1dGhvciAoYW5vbnltb3VzKSAvQ3JlYXRpb25EYXRlIChEOjIwMDAwMTAxMDAwMDAwKzAwJzAwJykgL0NyZWF0b3IgKGFub255bW91cykgL0tleXdvcmRzICgpIC9Nb2REYXRlIChEOjIwMDAwMTAxMDAwMDAwKzAwJzAwJykgL1Byb2R1Y2VyIChSZXBvcnRMYWIgUERGIExpYnJhcnkgLSBcKG9wZW5zb3VyY2VcKSkgCiAgL1N1YmplY3QgKHVuc3BlY2lmaWVkKSAvVGl0bGUgKHVudGl0bGVkKSAvVHJhcHBlZCAvRmFsc2UKPj4KZW5kb2JqCjYgMCBvYmoKPDwKL0NvdW50IDEgL0tpZHMgWyAzIDAgUiBdIC9UeXBlIC9QYWdlcwo+PgplbmRvYmoKNyAwIG9iago8PAovRmlsdGVyIFsgL0FTQ0lJODVEZWNvZGUgL0ZsYXRlRGVjb2RlIF0gL0xlbmd0aCAxMjYKPj4Kc3RyZWFtCkdhcFFoMEU9RiwwVVxIM1RccE5ZVF5RS2s/dGM+SVAsO1cjVTFeMjNpaFBFTV9NKE04JjhIa1FPPiZGZCNnJCluI2QyQiVhW2UjKjlORl4wY1JWUlwvbD09LDBbcXM4MlVPQj4xVWtfMSNnI3NNZC9uI2BodVdsblhXOjF+PmVuZHN0cmVhbQplbmRvYmoKeHJlZgowIDgKMDAwMDAwMDAwMCA2NTUzNSBmIAowMDAwMDAwMDYxIDAwMDAwIG4gCjAwMDAwMDAwOTIgMDAwMDAgbiAKMDAwMDAwMDE5OSAwMDAwMCBuIAowMDAwMDAwMzkyIDAwMDAwIG4gCjAwMDAwMDA0NjAgMDAwMDAgbiAKMDAwMDAwMDcyMSAwMDAwMCBuIAowMDAwMDAwNzgwIDAwMDAwIG4gCnRyYWlsZXIKPDwKL0lEIApbPDFjMTc4MTk4ZmJkZmE1MWIyNTk5NWQ4OWQ0MTAyMDQzPjwxYzE3ODE5OGZiZGZhNTFiMjU5OTVkODlkNDEwMjA0Mz5dCiUgUmVwb3J0TGFiIGdlbmVyYXRlZCBQREYgZG9jdW1lbnQgLS0gZGlnZXN0IChvcGVuc291cmNlKQoKL0luZm8gNSAwIFIKL1Jvb3QgNCAwIFIKL1NpemUgOAo+PgpzdGFydHhyZWYKOTk2CiUlRU9GCg==";

const METRICS = [
  "healthConnectMs",
  "analyzeMs",
  "sanitizeMs",
  "continuationMs",
  "copyMs",
  "reidentifyMs",
  "reportMs",
  "pdfMs",
  "auditMs",
  "cleanupMs",
  "workflowMs",
];

function emptyEvidence() {
  return Object.fromEntries(METRICS.map((name) => [name, 0]));
}

async function measured(evidence, name, operation) {
  const started = performance.now();
  const result = await operation();
  evidence[name] = Math.max(0, performance.now() - started);
  return result;
}

function samplePdf() {
  const binary = atob(SAMPLE_PDF_B64);
  const bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0));
  return new File([bytes], "synthetic-package-smoke.pdf", {
    type: "application/pdf",
  });
}

function requireResult(condition) {
  if (!condition) throw new Error("package smoke validation failed");
}

const UPGRADE_CONNECTION_FAILURES = new Set([
  "broker_unauthorized",
  "broker_unavailable",
]);

async function requireUpgradeInvalidation(
  operation,
  requireSessionInvalidated = false
) {
  let failure;
  try {
    await operation();
  } catch (error) {
    failure = error;
  }
  requireResult(
    failure instanceof ApiError &&
      failure.restartRequired === true &&
      (!requireSessionInvalidated || failure.sessionInvalidated === true) &&
      (UPGRADE_CONNECTION_FAILURES.has(failure.code) ||
        (failure.code === "operation_timeout" &&
          failure.sessionInvalidated === true))
  );
}

async function appReadyAfterPageLoad() {
  if (document.readyState !== "complete") {
    await new Promise((resolve) => {
      window.addEventListener("load", resolve, { once: true });
    });
  }
  return (await window.__AIGUARD_APP_READY__) === true;
}

export async function runPackageSmoke() {
  const invoke = window.__TAURI__?.core?.invoke;
  if (typeof invoke !== "function") return;
  const evidence = emptyEvidence();
  const workflowStarted = performance.now();
  let stage = "app_ready";
  try {
    const appReady = await appReadyAfterPageLoad();
    if (!appReady) {
      stage = "health";
      await health();
      stage = "app_ready";
      requireResult(false);
    }
    stage = "health";
    await measured(evidence, "healthConnectMs", health);
    stage = "sanitize";
    const first = await measured(evidence, "sanitizeMs", () => sanitize(SOURCE));
    requireResult(first.session_id && first.sanitized_text !== SOURCE);
    stage = "ready_signal";
    const liveUpgrade = (await invoke("desktop_package_smoke_ready")) === true;

    if (liveUpgrade) {
      stage = "continuation";
      await requireUpgradeInvalidation(
        () => sanitize(CONTINUATION, "token", first.session_id)
      );
      stage = "reidentify";
      await requireUpgradeInvalidation(
        () => reidentify(first.session_id, first.sanitized_text),
        true
      );
      stage = "upgrade_invalidation";
      await invoke("desktop_package_smoke_upgrade_invalidated");
      return;
    }

    stage = "analyze";
    const analysis = await measured(evidence, "analyzeMs", () => analyze(SOURCE));
    requireResult(analysis.direct_pii_count > 0);

    stage = "continuation";
    const continuation = await measured(evidence, "continuationMs", () =>
      sanitize(CONTINUATION, "token", first.session_id)
    );
    requireResult(continuation.session_id === first.session_id);

    stage = "copy";
    await measured(evidence, "copyMs", () =>
      copyMasked(first.session_id, first.sanitized_text)
    );
    stage = "reidentify";
    const restored = await measured(evidence, "reidentifyMs", () =>
      reidentify(first.session_id, first.sanitized_text)
    );
    requireResult(
      restored.restored_text === SOURCE &&
        restored.leftover_count === 0 &&
        restored.warnings.length === 0
    );

    stage = "report";
    const report = await measured(evidence, "reportMs", () => analyzeReport(SOURCE));
    requireResult(report.report_pdf_b64.startsWith("JVBER"));
    stage = "pdf";
    const redacted = await measured(evidence, "pdfMs", () => redactPdf(samplePdf()));
    requireResult(redacted.redacted_pdf_b64.startsWith("JVBER"));
    stage = "audit";
    const audit = await measured(evidence, "auditMs", () => auditLog());
    requireResult(audit.status === "ok");

    stage = "cleanup";
    await measured(evidence, "cleanupMs", async () => {
      await disposeSession(first.session_id);
      await resetScope();
    });
    evidence.workflowMs = Math.max(0, performance.now() - workflowStarted);
  } catch {
    await invoke("desktop_package_smoke_fail", { stage });
    return;
  }
  stage = "finish";
  await invoke("desktop_package_smoke_finish", { evidence });
}
