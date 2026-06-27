// AI Guard service worker.
//
// All backend calls happen here: the worker has cross-origin access to
// localhost via host_permissions, so content scripts on chatgpt.com /
// claude.ai do not hit page CORS restrictions. The token -> original vault
// never reaches the extension; we only remember the session_id per tab so a
// Restore can find the right session on the backend.
//
// MV3 service workers are ephemeral -- Chrome evicts them after a short idle
// period and in-memory variables are lost. The wait for an AI reply easily
// outlasts the worker, so the per-tab session_id is kept in
// chrome.storage.session (survives worker restarts, never written to disk,
// cleared when the browser closes -- consistent with the vault invariant),
// with an in-memory write-through cache for the fast path.

const BACKENDS = ["http://localhost:8000", "http://127.0.0.1:8000"];
const sessionCache = {}; // tabId -> session_id (fast path; may be wiped on evict)

function sessionKey(tabId) {
  return "aiguard_sid_" + tabId;
}

async function storeSession(tabId, sid) {
  if (tabId == null) return;
  sessionCache[tabId] = sid;
  try {
    await chrome.storage.session.set({ [sessionKey(tabId)]: sid });
  } catch (e) {
    /* cache still holds it for this worker's lifetime */
  }
}

async function loadSession(tabId) {
  if (tabId == null) return null;
  if (sessionCache[tabId]) return sessionCache[tabId];
  try {
    const o = await chrome.storage.session.get(sessionKey(tabId));
    const sid = o[sessionKey(tabId)] || null;
    if (sid) sessionCache[tabId] = sid;
    return sid;
  } catch (e) {
    return null;
  }
}

async function postJSON(path, body) {
  let lastErr;
  for (const base of BACKENDS) {
    try {
      const r = await fetch(base + path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await r.json().catch(() => ({}));
      return { ok: r.ok, status: r.status, data };
    } catch (e) {
      lastErr = e;
    }
  }
  return { ok: false, status: 0, error: String(lastErr) };
}

async function getJSON(path) {
  let lastErr;
  for (const base of BACKENDS) {
    try {
      const r = await fetch(base + path);
      const data = await r.json().catch(() => ({}));
      return { ok: r.ok, status: r.status, data };
    } catch (e) {
      lastErr = e;
    }
  }
  return { ok: false, status: 0, error: String(lastErr) };
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  const tabId = sender.tab && sender.tab.id;
  (async () => {
    if (msg.type === "health") {
      sendResponse(await getJSON("/api/health"));
      return;
    }
    if (msg.type === "sanitize") {
      // mode comes from the popup message, else the saved toggle (so the
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
      const resp = await postJSON("/api/sanitize", { text: msg.text, mode });
      if (resp.ok && resp.data && resp.data.session_id) {
        await storeSession(tabId, resp.data.session_id);
      }
      sendResponse(resp);
      return;
    }
    if (msg.type === "reidentify") {
      // Popup passes session_id explicitly; content script relies on the
      // session stored for its tab.
      const sid = msg.session_id || (await loadSession(tabId));
      if (!sid) {
        sendResponse({ ok: false, status: 0, error: "no-session" });
        return;
      }
      sendResponse(await postJSON("/api/reidentify", { session_id: sid, text: msg.text }));
      return;
    }
    sendResponse({ ok: false, status: 0, error: "unknown-message" });
  })();
  return true; // keep the message channel open for the async response
});

chrome.tabs.onRemoved.addListener((tabId) => {
  delete sessionCache[tabId];
  chrome.storage.session.remove(sessionKey(tabId)).catch(() => {});
});
