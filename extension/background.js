// AI Guard service worker.
//
// All backend calls happen here: the worker has cross-origin access to
// localhost via host_permissions, so content scripts on chatgpt.com /
// claude.ai do not hit page CORS restrictions. The token -> original vault
// never reaches the extension; we only remember the session_id per tab,
// in memory, so a Restore can find the right session on the backend.

const BACKENDS = ["http://localhost:8000", "http://127.0.0.1:8000"];
const tabSession = {}; // tabId -> session_id (in-memory only)

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
      const resp = await postJSON("/api/sanitize", { text: msg.text });
      if (resp.ok && resp.data && resp.data.session_id) {
        if (tabId != null) tabSession[tabId] = resp.data.session_id;
      }
      sendResponse(resp);
      return;
    }
    if (msg.type === "reidentify") {
      // Popup passes session_id explicitly; content script relies on the
      // session stored for its tab.
      const sid = msg.session_id || (tabId != null ? tabSession[tabId] : null);
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
  delete tabSession[tabId];
});
