import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const V2_HEADER = "X-AIGuard-Contract-Version";

function headers(value = "2") {
  return {
    get: (name) => (name.toLowerCase() === V2_HEADER.toLowerCase() ? value : null),
  };
}

function response(body, { ok = true, status = 200, version = "2" } = {}) {
  return {
    ok,
    status,
    headers: headers(version),
    json: vi.fn().mockResolvedValue(body),
  };
}

function healthBody(overrides = {}) {
  return {
    status: "ok",
    version: "2.5.0",
    contract_version: 2,
    capabilities: {
      control_token_required: true,
      api_key_required: false,
    },
    ...overrides,
  };
}

function sanitizeBody(overrides = {}) {
  return {
    session_id: "session-1",
    sanitized_text: "😀 [ชื่อ_1]",
    detected_entity_count: 1,
    replacement_count: 1,
    entity_type_counts: { NAME: 1 },
    highlights: [{ start: 2, end: 10, data_type: "NAME", redact_type: "TB" }],
    section26_categories: [],
    guard_findings: [],
    warnings: [],
    safety: { status: "pass", residual_count: 0 },
    ...overrides,
  };
}

function makeChrome() {
  const listeners = {};
  const sessionStore = {};
  return {
    _listeners: listeners,
    _sessionStore: sessionStore,
    runtime: {
      onInstalled: { addListener: () => {} },
      onMessage: { addListener: (cb) => (listeners.message = cb) },
    },
    tabs: { onRemoved: { addListener: () => {} } },
    sidePanel: { setPanelBehavior: () => Promise.resolve() },
    storage: {
      session: {
        get: async (key) => ({ [key]: sessionStore[key] }),
        set: async (value) => Object.assign(sessionStore, value),
        remove: async (key) => delete sessionStore[key],
      },
      local: { get: async () => ({ mode: "token" }) },
    },
  };
}

function invoke(
  chrome,
  message,
  sender = {
    tab: { id: 7, url: "https://chatgpt.com/c/synthetic" },
    frameId: 0,
    documentId: "doc-1",
    documentLifecycle: "active",
    origin: "https://chatgpt.com",
    url: "https://chatgpt.com/c/synthetic",
  }
) {
  return new Promise((resolve) => chrome._listeners.message(message, sender, resolve));
}

async function loadWorker(chrome) {
  global.chrome = chrome;
  vi.resetModules();
  await import("../contract-v2.js");
  await import("../background.js");
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  delete global.chrome;
  delete global.AIGUARD_CONTRACT_V2;
});

describe("extension HTTP v2 boundary", () => {
  it("refuses to send PII when exact v2 health has not passed", async () => {
    fetch.mockResolvedValueOnce(response(healthBody({ contract_version: 1 })));
    const chrome = makeChrome();
    await loadWorker(chrome);

    const result = await invoke(chrome, { type: "sanitize", text: "synthetic", mode: "token" });

    expect(result.ok).toBe(false);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0]).toEqual([
      expect.stringMatching(/\/api\/health$/),
      { cache: "no-store" },
    ]);
  });

  it("asserts v2 on sanitize and returns only a fresh strict DTO", async () => {
    const backend = sanitizeBody();
    fetch
      .mockResolvedValueOnce(response(healthBody()))
      .mockResolvedValueOnce(response(backend));
    const chrome = makeChrome();
    await loadWorker(chrome);

    const result = await invoke(chrome, { type: "sanitize", text: "synthetic", mode: "token" });

    expect(fetch.mock.calls[1][1].headers).toEqual({
      "Content-Type": "application/json",
      [V2_HEADER]: "2",
    });
    expect(result).toEqual({ ok: true, status: 200, data: sanitizeBody() });
    expect(result.data).not.toBe(backend);
    expect(result.data.safety).not.toBe(backend.safety);
    expect(chrome._sessionStore.aiguard_sid_7).toEqual({
      session_id: "session-1",
      origin: "https://chatgpt.com",
    });
  });

  it.each([
    ["missing response assertion", null],
    ["duplicate response assertion", "2, 2"],
    ["malformed response assertion", "02"],
    ["mismatched response assertion", "1"],
  ])("rejects a %s before publishing the session", async (_label, version) => {
    fetch
      .mockResolvedValueOnce(response(healthBody()))
      .mockResolvedValueOnce(response(sanitizeBody(), { version }));
    const chrome = makeChrome();
    await loadWorker(chrome);

    const result = await invoke(chrome, { type: "sanitize", text: "synthetic" });

    expect(result.ok).toBe(false);
    expect(chrome._sessionStore.aiguard_sid_7).toBeUndefined();
  });

  it("rejects unknown mapping-oriented response fields", async () => {
    fetch
      .mockResolvedValueOnce(response(healthBody()))
      .mockResolvedValueOnce(response(sanitizeBody({ original_text: "synthetic" })));
    const chrome = makeChrome();
    await loadWorker(chrome);

    const result = await invoke(chrome, { type: "sanitize", text: "synthetic" });

    expect(result.ok).toBe(false);
    expect(result.data).toBeUndefined();
    expect(chrome._sessionStore.aiguard_sid_7).toBeUndefined();
  });

  it("rejects unsafe safety state", async () => {
    fetch
      .mockResolvedValueOnce(response(healthBody()))
      .mockResolvedValueOnce(
        response(sanitizeBody({ safety: { status: "pass", residual_count: 1 } }))
      );
    const chrome = makeChrome();
    await loadWorker(chrome);

    const result = await invoke(chrome, { type: "sanitize", text: "synthetic" });

    expect(result.ok).toBe(false);
    expect(chrome._sessionStore.aiguard_sid_7).toBeUndefined();
  });

  it("rejects an empty sanitize result before publishing the session", async () => {
    fetch
      .mockResolvedValueOnce(response(healthBody()))
      .mockResolvedValueOnce(
        response(
          sanitizeBody({
            sanitized_text: "",
            detected_entity_count: 0,
            replacement_count: 0,
            entity_type_counts: {},
            highlights: [],
          })
        )
      );
    const chrome = makeChrome();
    await loadWorker(chrome);

    const result = await invoke(chrome, { type: "sanitize", text: "synthetic" });

    expect(result.ok).toBe(false);
    expect(result.data).toBeUndefined();
    expect(chrome._sessionStore.aiguard_sid_7).toBeUndefined();
  });

  it("rejects non-canonical Section 26 category order", async () => {
    fetch
      .mockResolvedValueOnce(response(healthBody()))
      .mockResolvedValueOnce(
        response(
          sanitizeBody({
            section26_categories: ["HEALTH", "RACE_ETHNICITY"],
          })
        )
      );
    const chrome = makeChrome();
    await loadWorker(chrome);

    const result = await invoke(chrome, { type: "sanitize", text: "synthetic" });

    expect(result.ok).toBe(false);
    expect(chrome._sessionStore.aiguard_sid_7).toBeUndefined();
  });

  it("rejects nonzero count for a fixed-count safe error", async () => {
    const chrome = makeChrome();
    await loadWorker(chrome);

    expect(() =>
      global.AIGUARD_CONTRACT_V2.validateError(
        {
          error: {
            code: "internal_error",
            category: "internal",
            count: 1,
            retryable: false,
            status: 500,
          },
        },
        500
      )
    ).toThrow(/error/i);
  });
});
