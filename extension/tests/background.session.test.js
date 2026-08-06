// EXT-1: the service worker reuses the per-tab session_id so multi-turn
// mappings remain available. A replacement session uses a new token namespace,
// so an older reply fails closed instead of restoring through the wrong vault.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const TOKEN = `[ชื่อ_${"a".repeat(25)}_${"n".repeat(20)}_1]`;

function makeChrome() {
  const listeners = {};
  const sessionStore = {};
  return {
    _listeners: listeners,
    _sessionStore: sessionStore,
    runtime: {
      onInstalled: { addListener: () => {} },
      onMessage: {
        addListener: (cb) => {
          listeners.message = cb;
        },
      },
    },
    tabs: {
      onRemoved: {
        addListener: (cb) => {
          listeners.tabRemoved = cb;
        },
      },
    },
    sidePanel: { setPanelBehavior: () => Promise.resolve() },
    storage: {
      session: {
        get: (k) => Promise.resolve({ [k]: sessionStore[k] }),
        set: (o) => {
          Object.assign(sessionStore, o);
          return Promise.resolve();
        },
        remove: (k) => {
          delete sessionStore[k];
          return Promise.resolve();
        },
      },
      local: { get: () => Promise.resolve({}) },
    },
  };
}

function siteSender({
  tabId = 42,
  origin = "https://chatgpt.com",
  path = "/c/synthetic",
  documentId = "doc-1",
} = {}) {
  const url = origin + path;
  return {
    tab: { id: tabId, url },
    frameId: 0,
    documentId,
    documentLifecycle: "active",
    origin,
    url,
  };
}

// Invoke the registered onMessage listener and resolve with sendResponse's arg.
function invoke(chrome, msg, sender) {
  return new Promise((resolve) => {
    chrome._listeners.message(msg, sender, resolve);
  });
}

let calls;

function headers() {
  return { get: (name) => (name.toLowerCase() === "x-aiguard-contract-version" ? "2" : null) };
}

function healthBody() {
  return {
    status: "ok",
    version: "2.5.0",
    contract_version: 2,
    capabilities: { control_token_required: true, api_key_required: false },
  };
}

function sanitizeBody(sessionId) {
  return {
    session_id: sessionId,
    sanitized_text: TOKEN,
    detected_entity_count: 1,
    replacement_count: 1,
    entity_type_counts: { NAME: 1 },
    highlights: [
      {
        start: 0,
        end: Array.from(TOKEN).length,
        data_type: "NAME",
        redact_type: "TB",
      },
    ],
    section26_categories: [],
    guard_findings: [],
    warnings: [],
    safety: { status: "pass", residual_count: 0 },
  };
}

function installFetch(sessionId = "S1") {
  calls = [];
  global.fetch = vi.fn((url, opts) => {
    const body = opts && opts.body ? JSON.parse(opts.body) : null;
    calls.push({ url, body });
    const data = url.endsWith("/api/health") ? healthBody() : sanitizeBody(sessionId);
    return Promise.resolve({
      ok: true,
      status: 200,
      headers: headers(),
      json: () => Promise.resolve(data),
    });
  });
}

async function loadWorker(chrome) {
  global.chrome = chrome;
  vi.resetModules();
  await import("../contract-v2.js");
  await import("../background.js");
}

afterEach(() => {
  vi.restoreAllMocks();
  delete global.fetch;
  delete global.chrome;
  delete global.AIGUARD_CONTRACT_V2;
});

describe("background sanitize session reuse (EXT-1)", () => {
  it("omits session_id on the first Mask, then reuses it after a same-origin reload", async () => {
    const chrome = makeChrome();
    installFetch("S1");
    await loadWorker(chrome);
    const sender = siteSender();

    await invoke(chrome, { type: "sanitize", text: "นาย ก", mode: "token" }, sender);
    const first = calls.find((c) => c.url.endsWith("/api/sanitize"));
    expect(first.body.session_id).toBeUndefined();

    calls.length = 0;
    await invoke(
      chrome,
      { type: "sanitize", text: "นาย ข", mode: "token" },
      siteSender({ path: "/c/reloaded", documentId: "doc-2" })
    );
    const second = calls.find((c) => c.url.endsWith("/api/sanitize"));
    expect(second.body.session_id).toBe("S1");
  });

  it("invalidates a tab session when the tab moves to a different allowed origin", async () => {
    const chrome = makeChrome();
    let sessionNumber = 0;
    calls = [];
    global.fetch = vi.fn((url, opts) => {
      const body = opts && opts.body ? JSON.parse(opts.body) : null;
      calls.push({ url, body });
      if (url.endsWith("/api/health")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          headers: headers(),
          json: () => Promise.resolve(healthBody()),
        });
      }
      sessionNumber += 1;
      return Promise.resolve({
        ok: true,
        status: 200,
        headers: headers(),
        json: () => Promise.resolve(sanitizeBody(`S${sessionNumber}`)),
      });
    });
    await loadWorker(chrome);

    await invoke(
      chrome,
      { type: "sanitize", text: "นาย ก", mode: "token" },
      siteSender({ origin: "https://chatgpt.com" })
    );

    calls.length = 0;
    const deniedRestore = await invoke(
      chrome,
      { type: "reidentify", text: "[ชื่อ_1]" },
      siteSender({
        origin: "https://claude.ai",
        path: "/chat/synthetic",
        documentId: "doc-2",
      })
    );
    expect(deniedRestore).toEqual({ ok: false, status: 0, error: "no-session" });
    expect(calls.some((call) => call.url.endsWith("/api/reidentify"))).toBe(false);

    calls.length = 0;
    await invoke(
      chrome,
      { type: "sanitize", text: "นาย ข", mode: "token" },
      siteSender({
        origin: "https://claude.ai",
        path: "/chat/synthetic",
        documentId: "doc-2",
      })
    );
    const sanitize = calls.find((call) => call.url.endsWith("/api/sanitize"));
    expect(sanitize.body.session_id).toBeUndefined();
    expect(chrome._sessionStore.aiguard_sid_42).toEqual({
      session_id: "S2",
      origin: "https://claude.ai",
    });
  });

  it("removes both cached and stored session state when a tab closes", async () => {
    const chrome = makeChrome();
    installFetch("S1");
    await loadWorker(chrome);
    const sender = siteSender();

    await invoke(chrome, { type: "sanitize", text: "นาย ก", mode: "token" }, sender);
    expect(chrome._sessionStore.aiguard_sid_42).toEqual({
      session_id: "S1",
      origin: "https://chatgpt.com",
    });

    chrome._listeners.tabRemoved(42);
    await Promise.resolve();
    expect(chrome._sessionStore.aiguard_sid_42).toBeUndefined();

    calls.length = 0;
    await invoke(chrome, { type: "sanitize", text: "นาย ข", mode: "token" }, sender);
    const sanitize = calls.find((call) => call.url.endsWith("/api/sanitize"));
    expect(sanitize.body.session_id).toBeUndefined();
  });

  it("keeps no-tab side-panel callers out of tab session storage", async () => {
    const chrome = makeChrome();
    const get = vi.spyOn(chrome.storage.session, "get");
    const set = vi.spyOn(chrome.storage.session, "set");
    const remove = vi.spyOn(chrome.storage.session, "remove");
    installFetch("SP1");
    await loadWorker(chrome);
    const sidePanelSender = {
      origin: "chrome-extension://synthetic-id",
      url: "chrome-extension://synthetic-id/sidepanel.html",
    };

    await invoke(
      chrome,
      { type: "sanitize", text: "นาย ก", mode: "token" },
      sidePanelSender
    );
    const restore = await invoke(
      chrome,
      { type: "reidentify", text: "[ชื่อ_1]" },
      sidePanelSender
    );

    expect(restore).toEqual({ ok: false, status: 0, error: "no-session" });
    expect(get).not.toHaveBeenCalled();
    expect(set).not.toHaveBeenCalled();
    expect(remove).not.toHaveBeenCalled();
    expect(Object.keys(chrome._sessionStore)).toEqual([]);
  });

  it("drops a legacy session that has no origin binding", async () => {
    const chrome = makeChrome();
    chrome._sessionStore.aiguard_sid_42 = "LEGACY";
    installFetch("S1");
    await loadWorker(chrome);

    await invoke(
      chrome,
      { type: "sanitize", text: "นาย ก", mode: "token" },
      siteSender()
    );

    const sanitize = calls.find((call) => call.url.endsWith("/api/sanitize"));
    expect(sanitize.body.session_id).toBeUndefined();
    expect(chrome._sessionStore.aiguard_sid_42).toEqual({
      session_id: "S1",
      origin: "https://chatgpt.com",
    });
  });

  it("rejects non-top-frame senders before any backend or session access", async () => {
    const chrome = makeChrome();
    const get = vi.spyOn(chrome.storage.session, "get");
    installFetch("S1");
    await loadWorker(chrome);
    const sender = siteSender();
    sender.frameId = 3;

    const result = await invoke(
      chrome,
      { type: "sanitize", text: "นาย ก", mode: "token" },
      sender
    );

    expect(result).toEqual({
      ok: false,
      status: 0,
      error: "invalid-sender-context",
    });
    expect(fetch).not.toHaveBeenCalled();
    expect(get).not.toHaveBeenCalled();
  });

  it.each([
    { status: 400, code: "invalid_request", category: "request" },
    { status: 404, code: "session_unavailable", category: "session" },
  ])("retries without session_id for the exact $code reset error", async (errorSpec) => {
    const chrome = makeChrome();
    // Seed a stored session for the tab, then make the backend reject reuse
    // (e.g. mode locked / expired) on the first call and accept a fresh one.
    chrome._sessionStore["aiguard_sid_42"] = {
      session_id: "OLD",
      origin: "https://chatgpt.com",
    };
    calls = [];
    let sanitizeCall = 0;
    global.fetch = vi.fn((url, opts) => {
      const body = opts && opts.body ? JSON.parse(opts.body) : null;
      calls.push({ url, body });
      if (url.endsWith("/api/health")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          headers: headers(),
          json: () => Promise.resolve(healthBody()),
        });
      }
      sanitizeCall += 1;
      const rejected = sanitizeCall === 1; // first attempt (with OLD) is rejected
      return Promise.resolve({
        ok: !rejected,
        status: rejected ? errorSpec.status : 200,
        headers: headers(),
        json: () =>
          Promise.resolve(
            rejected
              ? {
                  error: {
                    code: errorSpec.code,
                    category: errorSpec.category,
                    count: 0,
                    retryable: false,
                    status: errorSpec.status,
                  },
                }
              : sanitizeBody("NEW")
          ),
      });
    });
    vi.resetModules();
    global.chrome = chrome;
    await import("../contract-v2.js");
    await import("../background.js");

    const resp = await invoke(
      chrome,
      { type: "sanitize", text: "นาย ก", mode: "surrogate" },
      siteSender()
    );
    const sanitizeCalls = calls.filter((c) => c.url.endsWith("/api/sanitize"));
    // two localhost bases exist, so count distinct attempts by their body shape
    expect(sanitizeCalls[0].body.session_id).toBe("OLD");
    expect(sanitizeCalls[sanitizeCalls.length - 1].body.session_id).toBeUndefined();
    expect(resp.ok).toBe(true);
    expect(chrome._sessionStore["aiguard_sid_42"]).toEqual({
      session_id: "NEW",
      origin: "https://chatgpt.com",
    });
  });

  it("does not retry an unrelated valid v2 404 error", async () => {
    const chrome = makeChrome();
    chrome._sessionStore["aiguard_sid_42"] = {
      session_id: "OLD",
      origin: "https://chatgpt.com",
    };
    calls = [];
    global.fetch = vi.fn((url, opts) => {
      const body = opts && opts.body ? JSON.parse(opts.body) : null;
      calls.push({ url, body });
      if (url.endsWith("/api/health")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          headers: headers(),
          json: () => Promise.resolve(healthBody()),
        });
      }
      return Promise.resolve({
        ok: false,
        status: 404,
        headers: headers(),
        json: () =>
          Promise.resolve({
            error: {
              code: "route_not_found",
              category: "request",
              count: 0,
              retryable: false,
              status: 404,
            },
          }),
      });
    });
    await loadWorker(chrome);

    const response = await invoke(
      chrome,
      { type: "sanitize", text: "นาย ก", mode: "token" },
      siteSender()
    );

    const sanitizeCalls = calls.filter((call) => call.url.endsWith("/api/sanitize"));
    expect(sanitizeCalls).toHaveLength(1);
    expect(sanitizeCalls[0].body.session_id).toBe("OLD");
    expect(response).toEqual({
      ok: false,
      status: 404,
      error: "route_not_found",
    });
  });
});
