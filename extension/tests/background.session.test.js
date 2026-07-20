// EXT-1: the service worker must reuse the per-tab session_id on /api/sanitize
// so multi-turn token numbering stays consistent. Without it, every Mask mints
// a new session (tokens restart at _1) and a later Restore maps [ชื่อ_1] with
// the wrong session's vault -> wrong person's PII.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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
    tabs: { onRemoved: { addListener: () => {} } },
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

// Invoke the registered onMessage listener and resolve with sendResponse's arg.
function invoke(chrome, msg, sender) {
  return new Promise((resolve) => {
    chrome._listeners.message(msg, sender, resolve);
  });
}

let calls;

function installFetch(sessionId = "S1") {
  calls = [];
  global.fetch = vi.fn((url, opts) => {
    const body = opts && opts.body ? JSON.parse(opts.body) : null;
    calls.push({ url, body });
    return Promise.resolve({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ session_id: sessionId, sanitized_text: "[ชื่อ_1]" }),
    });
  });
}

async function loadWorker(chrome) {
  global.chrome = chrome;
  vi.resetModules();
  await import("../background.js");
}

afterEach(() => {
  vi.restoreAllMocks();
  delete global.fetch;
  delete global.chrome;
});

describe("background sanitize session reuse (EXT-1)", () => {
  it("omits session_id on the first Mask, then reuses it on the next", async () => {
    const chrome = makeChrome();
    installFetch("S1");
    await loadWorker(chrome);
    const sender = { tab: { id: 42 } };

    await invoke(chrome, { type: "sanitize", text: "นาย ก", mode: "token" }, sender);
    const first = calls.find((c) => c.url.endsWith("/api/sanitize"));
    expect(first.body.session_id).toBeUndefined();

    calls.length = 0;
    await invoke(chrome, { type: "sanitize", text: "นาย ข", mode: "token" }, sender);
    const second = calls.find((c) => c.url.endsWith("/api/sanitize"));
    expect(second.body.session_id).toBe("S1");
  });

  it("retries without session_id when a stored session is rejected (400/404)", async () => {
    const chrome = makeChrome();
    // Seed a stored session for the tab, then make the backend reject reuse
    // (e.g. mode locked / expired) on the first call and accept a fresh one.
    chrome._sessionStore["aiguard_sid_42"] = "OLD";
    calls = [];
    let call = 0;
    global.fetch = vi.fn((url, opts) => {
      const body = opts && opts.body ? JSON.parse(opts.body) : null;
      calls.push({ url, body });
      call += 1;
      const rejected = call === 1; // first attempt (with OLD) is rejected
      return Promise.resolve({
        ok: !rejected,
        status: rejected ? 400 : 200,
        json: () => Promise.resolve(rejected ? { detail: "mode mismatch" } : { session_id: "NEW" }),
      });
    });
    vi.resetModules();
    global.chrome = chrome;
    await import("../background.js");

    const resp = await invoke(
      chrome,
      { type: "sanitize", text: "นาย ก", mode: "surrogate" },
      { tab: { id: 42 } }
    );
    const sanitizeCalls = calls.filter((c) => c.url.endsWith("/api/sanitize"));
    // two localhost bases exist, so count distinct attempts by their body shape
    expect(sanitizeCalls[0].body.session_id).toBe("OLD");
    expect(sanitizeCalls[sanitizeCalls.length - 1].body.session_id).toBeUndefined();
    expect(resp.ok).toBe(true);
    expect(chrome._sessionStore["aiguard_sid_42"]).toBe("NEW");
  });
});
