// AI Guard service worker.
//
// All backend calls happen here: the worker has cross-origin access to
// localhost via host_permissions, so content scripts on chatgpt.com /
// claude.ai do not hit page CORS restrictions. This worker is the HTTP v2
// projection boundary: content scripts receive only fresh, validated DTOs.
//
// MV3 service workers are ephemeral -- Chrome evicts them after a short idle
// period and in-memory variables are lost. The wait for an AI reply easily
// outlasts the worker, so the per-tab session_id and its site origin are kept in
// chrome.storage.session (survives worker restarts, never written to disk,
// cleared when the browser closes -- consistent with the vault invariant),
// with an in-memory write-through cache for the fast path.

if (!globalThis.AIGUARD_CONTRACT_V2 && typeof importScripts === "function") {
  importScripts("contract-v2.js");
}
const CONTRACT = globalThis.AIGUARD_CONTRACT_V2;
if (!CONTRACT) throw new Error("HTTP v2 contract helpers are unavailable");

const BACKENDS = ["http://localhost:8000", "http://127.0.0.1:8000"];
const sessionCache = Object.create(null); // tabId -> bound session record
const activeTabOrigins = Object.create(null); // blocks stale cross-navigation writes
let activeBackend = null;

// Clicking the toolbar icon opens the docked side panel (no popup). The
// behavior is persisted by Chrome, but re-asserting it on install and on
// worker startup keeps it correct across updates and profile reloads.
function enableSidePanelOnClick() {
  if (!chrome.sidePanel || !chrome.sidePanel.setPanelBehavior) return;
  chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {});
}
chrome.runtime.onInstalled.addListener(enableSidePanelOnClick);
enableSidePanelOnClick();

function sessionKey(tabId) {
  return "aiguard_sid_" + tabId;
}

function httpsOrigin(value) {
  try {
    const parsed = new URL(value);
    return parsed.protocol === "https:" ? parsed.origin : null;
  } catch {
    return null;
  }
}

function sessionScope(sender) {
  if (!sender || !sender.tab) return null;
  const tabId = sender.tab.id;
  if (!Number.isInteger(tabId) || tabId < 0) return null;

  // Content scripts are installed in the top frame only. Rejecting other
  // frames prevents a future manifest change from silently sharing a vault
  // between different frame origins.
  if (sender.frameId !== 0) return null;
  if (sender.documentLifecycle && sender.documentLifecycle !== "active") return null;

  const values = [sender.origin, sender.url, sender.tab.url].filter(
    (value) => typeof value === "string" && value.length > 0
  );
  if (values.length === 0) return null;
  const origins = values.map(httpsOrigin);
  if (origins.some((origin) => !origin)) return null;
  if (origins.some((origin) => origin !== origins[0])) return null;

  // Do not bind documentId: a same-origin reload should keep multi-turn token
  // identity. Origin changes still invalidate the tab's vault reference.
  return { tabId, origin: origins[0] };
}

function isBoundSession(record, scope) {
  if (!record || typeof record !== "object" || Array.isArray(record)) return false;
  const keys = Object.keys(record).sort();
  return (
    keys.length === 2 &&
    keys[0] === "origin" &&
    keys[1] === "session_id" &&
    typeof record.session_id === "string" &&
    record.session_id.length > 0 &&
    record.origin === scope.origin
  );
}

async function clearStoredSession(tabId) {
  if (!Number.isInteger(tabId) || tabId < 0) return;
  delete sessionCache[tabId];
  try {
    await chrome.storage.session.remove(sessionKey(tabId));
  } catch {
    /* the in-memory reference is still gone */
  }
}

async function activateSessionScope(scope) {
  const previousOrigin = activeTabOrigins[scope.tabId];
  activeTabOrigins[scope.tabId] = scope.origin;
  if (previousOrigin && previousOrigin !== scope.origin) {
    await clearStoredSession(scope.tabId);
  }
}

async function storeSession(scope, sid) {
  if (!scope || activeTabOrigins[scope.tabId] !== scope.origin) return;
  const record = { session_id: sid, origin: scope.origin };
  sessionCache[scope.tabId] = record;
  try {
    await chrome.storage.session.set({ [sessionKey(scope.tabId)]: record });
  } catch {
    /* cache still holds it for this worker's lifetime */
  }
}

async function loadSession(scope) {
  if (!scope) return null;
  const cached = sessionCache[scope.tabId];
  if (isBoundSession(cached, scope)) return cached.session_id;
  if (cached) delete sessionCache[scope.tabId];

  try {
    const key = sessionKey(scope.tabId);
    const stored = (await chrome.storage.session.get(key))[key];
    if (!isBoundSession(stored, scope)) {
      if (stored != null) await chrome.storage.session.remove(key);
      return null;
    }
    sessionCache[scope.tabId] = stored;
    return stored.session_id;
  } catch {
    return null;
  }
}

async function readJson(response) {
  try {
    return await response.json();
  } catch {
    throw new Error("invalid-json");
  }
}

function contractFailure() {
  activeBackend = null;
  return { ok: false, status: 0, error: "contract-invalid" };
}

async function getHealth() {
  activeBackend = null;
  for (const base of BACKENDS) {
    let response;
    try {
      response = await fetch(base + "/api/health", { cache: "no-store" });
    } catch {
      continue;
    }
    try {
      if (!CONTRACT.hasHeader(response)) return contractFailure();
      const body = await readJson(response);
      if (!response.ok) {
        const error = CONTRACT.validateError(body, response.status);
        return {
          ok: false,
          status: error.error.status,
          error: error.error.code,
        };
      }
      const data = CONTRACT.validateHealth(body);
      if (data.capabilities.api_key_required) {
        return { ok: false, status: 401, error: "authentication-required" };
      }
      activeBackend = base;
      return { ok: true, status: response.status, data };
    } catch {
      return contractFailure();
    }
  }
  return { ok: false, status: 0, error: "backend-unavailable" };
}

async function postJSON(path, body, validator) {
  if (!activeBackend) return contractFailure();
  let response;
  try {
    response = await fetch(activeBackend + path, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        [CONTRACT.HEADER]: CONTRACT.VERSION,
      },
      body: JSON.stringify(body),
    });
  } catch {
    activeBackend = null;
    return { ok: false, status: 0, error: "backend-unavailable" };
  }
  try {
    if (!CONTRACT.hasHeader(response)) return contractFailure();
    const payload = await readJson(response);
    if (!response.ok) {
      const projected = CONTRACT.validateError(payload, response.status);
      return {
        ok: false,
        status: projected.error.status,
        error: projected.error.code,
      };
    }
    return {
      ok: true,
      status: response.status,
      data: validator(payload),
    };
  } catch {
    return contractFailure();
  }
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  (async () => {
    if (msg.type === "health") {
      sendResponse(await getHealth());
      return;
    }
    const isTabSender = Boolean(sender && sender.tab);
    const scope = isTabSender ? sessionScope(sender) : null;
    if (isTabSender && !scope) {
      sendResponse({ ok: false, status: 0, error: "invalid-sender-context" });
      return;
    }
    if (scope) await activateSessionScope(scope);

    if (msg.type === "sanitize") {
      const health = await getHealth();
      if (!health.ok) {
        sendResponse(health);
        return;
      }
      // mode comes from the side panel message, else the saved toggle (so the
      // in-page Mask button honors the same choice), else token.
      let mode = msg.mode;
      if (!mode) {
        try {
          const o = await chrome.storage.local.get("mode");
          mode = o.mode;
        } catch (e) {
          /* default below */
        }
      }
      mode = mode === "surrogate" ? "surrogate" : "token";
      // Reuse the tab's session so multi-turn mappings remain available. A
      // replacement session has a different token namespace, so an older reply
      // is reported as foreign instead of restoring through the wrong vault.
      // Explicit session IDs belong only to extension pages such as the side
      // panel. A tab caller can use only the session bound to its own origin.
      const priorSid = scope ? await loadSession(scope) : msg.session_id || null;
      let resp = await postJSON(
        "/api/sanitize",
        priorSid ? { text: msg.text, mode, session_id: priorSid } : { text: msg.text, mode },
        CONTRACT.validateSanitize
      );
      // Retry only the two exact session-reset outcomes. Other 400/404 errors
      // stay failed instead of being reinterpreted from their HTTP status.
      const retryFresh =
        priorSid &&
        ((resp.status === 404 && resp.error === "session_unavailable") ||
          (resp.status === 400 && resp.error === "invalid_request"));
      if (retryFresh) {
        resp = await postJSON(
          "/api/sanitize",
          { text: msg.text, mode },
          CONTRACT.validateSanitize
        );
      }
      if (resp.ok && resp.data && resp.data.session_id) {
        await storeSession(scope, resp.data.session_id);
      }
      sendResponse(resp);
      return;
    }
    if (msg.type === "reidentify") {
      const health = await getHealth();
      if (!health.ok) {
        sendResponse(health);
        return;
      }
      // The side panel passes session_id explicitly; content script relies on
      // the session stored for its tab and site origin.
      const sid = scope ? await loadSession(scope) : msg.session_id || null;
      if (!sid) {
        sendResponse({ ok: false, status: 0, error: "no-session" });
        return;
      }
      sendResponse(
        await postJSON(
          "/api/reidentify",
          { session_id: sid, text: msg.text },
          CONTRACT.validateReidentify
        )
      );
      return;
    }
    sendResponse({ ok: false, status: 0, error: "unknown-message" });
  })();
  return true; // keep the message channel open for the async response
});

chrome.tabs.onRemoved.addListener((tabId) => {
  delete activeTabOrigins[tabId];
  void clearStoredSession(tabId);
});
