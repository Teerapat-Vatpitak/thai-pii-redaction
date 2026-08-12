import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const EXTENSION_ID = "efocdbdljgaaiflfleofbjpenncenhee";

function event() {
  const listeners = [];
  return {
    addListener(listener) {
      listeners.push(listener);
    },
    emit(...arguments_) {
      return listeners.map((listener) => listener(...arguments_));
    },
    listeners,
  };
}

function sanitizeResult(text = "[NAME_1]") {
  return {
    detected_entity_count: 1,
    entity_type_counts: { NAME: 1 },
    guard_findings: [],
    highlights: [{ data_type: "NAME", end: 8, redact_type: "TB", start: 0 }],
    replacement_count: 1,
    safety: { residual_count: 0, status: "pass" },
    sanitized_text: text,
    section26_categories: [],
    warnings: [],
  };
}

function nativeResponse(request, result) {
  return {
    native_protocol_version: 1,
    ok: true,
    request_id: request.request_id,
    result,
  };
}

function defaultNativeHandler(request) {
  if (request.operation === "health") {
    return nativeResponse(request, { product_version: "2.5.0", status: "ok" });
  }
  if (request.operation === "scope_open") {
    return nativeResponse(request, { status: "ready" });
  }
  if (request.operation === "scope_close") {
    return nativeResponse(request, { closed: true });
  }
  if (request.operation === "sanitize") {
    return nativeResponse(request, sanitizeResult());
  }
  if (request.operation === "reidentify") {
    return nativeResponse(request, {
      leftover_count: 0,
      replaced_count: 1,
      restored_text: "synthetic-restored",
      warnings: [],
    });
  }
  throw new Error("unexpected native operation");
}

class NativePort {
  constructor(handler = defaultNativeHandler) {
    this.handler = handler;
    this.onMessage = event();
    this.onDisconnect = event();
    this.sent = [];
    this.closed = false;
  }

  postMessage(message) {
    if (this.closed) throw new Error("closed");
    this.sent.push(structuredClone(message));
    const response = this.handler(message, this);
    if (response !== undefined) queueMicrotask(() => this.onMessage.emit(response));
  }

  respond(response) {
    queueMicrotask(() => this.onMessage.emit(response));
  }

  disconnect() {
    if (this.closed) return;
    this.closed = true;
    this.onDisconnect.emit();
  }
}

function makeChrome(portFactory = () => new NativePort()) {
  const ports = [];
  const runtimeMessage = event();
  const runtimeConnect = event();
  const tabRemoved = event();
  const tabUpdated = event();
  const chrome = {
    _ports: ports,
    runtime: {
      id: EXTENSION_ID,
      lastError: null,
      onConnect: runtimeConnect,
      onInstalled: event(),
      onMessage: runtimeMessage,
      connectNative: vi.fn(() => {
        const port = portFactory(ports.length);
        ports.push(port);
        return port;
      }),
    },
    sidePanel: { setPanelBehavior: vi.fn(() => Promise.resolve()) },
    storage: {
      local: { get: vi.fn(async () => ({ mode: "token" })) },
      session: { clear: vi.fn(async () => {}) },
    },
    tabs: {
      onRemoved: tabRemoved,
      onUpdated: tabUpdated,
      sendMessage: vi.fn(() => Promise.resolve()),
    },
  };
  return chrome;
}

function tabSender(tabId = 7, origin = "https://chatgpt.com", documentId = "doc-1") {
  return {
    documentId,
    documentLifecycle: "active",
    frameId: 0,
    origin,
    tab: { id: tabId, url: `${origin}/c/synthetic` },
    url: `${origin}/c/synthetic`,
  };
}

function invoke(chrome, message, sender = tabSender()) {
  const listener = chrome.runtime.onMessage.listeners.at(-1);
  return new Promise((resolve) => listener(message, sender, resolve));
}

function makePanelPort() {
  return {
    name: "aiguard-side-panel-v1",
    onDisconnect: event(),
    onMessage: event(),
    outgoing: [],
    sender: {
      id: EXTENSION_ID,
      url: `chrome-extension://${EXTENSION_ID}/sidepanel.html`,
    },
    disconnect: vi.fn(),
    postMessage(message) {
      this.outgoing.push(structuredClone(message));
    },
  };
}

async function flush() {
  await Promise.resolve();
  await Promise.resolve();
  await vi.advanceTimersByTimeAsync(0);
  await Promise.resolve();
}

async function loadWorker(chrome) {
  global.chrome = chrome;
  vi.resetModules();
  await import("../contract-v2.js");
  await import("../background.js");
  await flush();
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.clearAllTimers();
  vi.useRealTimers();
  delete global.chrome;
  delete global.AIGUARD_CONTRACT_V2;
});

describe("MV3 native transport ownership", () => {
  it("fails closed when the exact native host is not registered", async () => {
    const chrome = makeChrome();
    chrome.runtime.connectNative.mockImplementation(() => {
      throw new Error("synthetic missing host");
    });
    await loadWorker(chrome);

    const health = await invoke(chrome, { type: "health" });
    const sanitize = await invoke(chrome, { type: "sanitize", text: "synthetic" });

    expect(health).toMatchObject({ ok: false, error: "native-unavailable" });
    expect(sanitize).toMatchObject({ ok: false, error: "native-unavailable" });
    expect(chrome.runtime.connectNative).toHaveBeenCalledWith(
      "th.ac.psu.aiguard.native_host"
    );
    expect(chrome._ports).toHaveLength(0);
    expect(chrome.storage.session.clear).toHaveBeenCalled();
  });

  it("uses one native port and keeps broker sessions out of JavaScript messages", async () => {
    const chrome = makeChrome();
    await loadWorker(chrome);

    const first = await invoke(chrome, { type: "sanitize", text: "synthetic-a" });
    const second = await invoke(chrome, { type: "sanitize", text: "synthetic-b" });
    const restored = await invoke(chrome, { type: "reidentify", text: "[NAME_1]" });

    expect(first.ok && second.ok && restored.ok).toBe(true);
    expect(chrome.runtime.connectNative).toHaveBeenCalledTimes(1);
    expect(chrome.runtime.connectNative).toHaveBeenCalledWith(
      "th.ac.psu.aiguard.native_host"
    );
    const sent = chrome._ports[0].sent;
    expect(sent.map((message) => message.operation)).toEqual([
      "health",
      "scope_open",
      "sanitize",
      "sanitize",
      "reidentify",
    ]);
    expect(sent[2].context_id).toBe(sent[3].context_id);
    expect(JSON.stringify(sent)).not.toContain("session_id");
    expect(JSON.stringify(first)).not.toContain("session_id");
  });

  it("confirms disposal before a user-selected mode change and never replays data", async () => {
    const chrome = makeChrome();
    await loadWorker(chrome);

    const token = await invoke(chrome, {
      type: "sanitize",
      text: "synthetic-token",
      mode: "token",
    });
    const surrogate = await invoke(chrome, {
      type: "sanitize",
      text: "synthetic-surrogate",
      mode: "surrogate",
    });

    expect(token.ok && surrogate.ok).toBe(true);
    const sent = chrome._ports[0].sent;
    expect(sent.map((message) => message.operation)).toEqual([
      "health",
      "scope_open",
      "sanitize",
      "scope_close",
      "scope_open",
      "sanitize",
    ]);
    expect(sent.filter((message) => message.operation === "sanitize")).toHaveLength(2);
    expect(sent[2].payload.mode).toBe("token");
    expect(sent[5].payload.mode).toBe("surrogate");
  });

  it("keeps simultaneous tabs in separate native contexts", async () => {
    const chrome = makeChrome();
    await loadWorker(chrome);
    await Promise.all([
      invoke(chrome, { type: "sanitize", text: "synthetic-a" }, tabSender(7)),
      invoke(chrome, { type: "sanitize", text: "synthetic-b" }, tabSender(8)),
    ]);
    await Promise.all([
      invoke(chrome, { type: "reidentify", text: "masked-a" }, tabSender(7)),
      invoke(chrome, { type: "reidentify", text: "masked-b" }, tabSender(8)),
    ]);

    const operations = chrome._ports[0].sent.filter((message) => message.context_id);
    const tabContexts = new Set(
      operations.filter((message) => message.operation === "sanitize").map((message) => message.context_id)
    );
    expect(tabContexts.size).toBe(2);
    for (const context of tabContexts) {
      expect(operations.filter((message) => message.context_id === context)).toHaveLength(3);
    }
  });

  it("invalidates the old scope on cross-origin navigation", async () => {
    const chrome = makeChrome();
    await loadWorker(chrome);
    await invoke(chrome, { type: "sanitize", text: "synthetic" }, tabSender(7));
    const oldContext = chrome._ports[0].sent.find(
      (message) => message.operation === "sanitize"
    ).context_id;

    chrome.tabs.onUpdated.emit(7, { url: "https://claude.ai/new" });
    await flush();
    const expired = await invoke(
      chrome,
      { type: "reidentify", text: "masked" },
      tabSender(7, "https://claude.ai", "doc-2")
    );
    expect(expired.error).toBe("session-expired");
    expect(chrome._ports[0].sent).toContainEqual(
      expect.objectContaining({ context_id: oldContext, operation: "scope_close" })
    );
    expect(chrome._ports[0].sent.filter((message) => message.operation === "reidentify")).toHaveLength(0);
  });

  it("drops a sanitize response queued behind tab closure and confirms disposal", async () => {
    let deferred;
    const chrome = makeChrome(
      () =>
        new NativePort((request) => {
          if (request.operation === "sanitize") {
            deferred = request;
            return undefined;
          }
          return defaultNativeHandler(request);
        })
    );
    await loadWorker(chrome);
    const operation = invoke(chrome, { type: "sanitize", text: "synthetic" });
    await flush();
    chrome.tabs.onRemoved.emit(7);
    chrome._ports[0].respond(nativeResponse(deferred, sanitizeResult()));
    const response = await operation;
    await flush();

    expect(response.error).toBe("session-expired");
    expect(chrome._ports[0].sent.some((message) => message.operation === "scope_close")).toBe(true);
  });

  it("tears down the connection when a closing tab has an unconfirmed scope open", async () => {
    const chrome = makeChrome(
      () =>
        new NativePort((request) =>
          request.operation === "scope_open" ? undefined : defaultNativeHandler(request)
        )
    );
    await loadWorker(chrome);
    const operation = invoke(chrome, { type: "sanitize", text: "synthetic" });
    await flush();

    chrome.tabs.onRemoved.emit(7);
    await flush();

    expect(chrome._ports[0].closed).toBe(true);
    expect((await operation).error).toBe("native-unavailable");
    expect(
      chrome._ports[0].sent.filter((message) => message.operation === "sanitize")
    ).toHaveLength(0);
  });

  it("drops a response queued behind a same-origin document replacement", async () => {
    let deferred;
    const chrome = makeChrome(
      () =>
        new NativePort((request) => {
          if (request.operation === "sanitize") {
            deferred = request;
            return undefined;
          }
          return defaultNativeHandler(request);
        })
    );
    await loadWorker(chrome);
    const operation = invoke(chrome, { type: "sanitize", text: "synthetic" });
    await flush();
    const replaced = await invoke(
      chrome,
      { type: "reidentify", text: "masked" },
      tabSender(7, "https://chatgpt.com", "doc-2")
    );
    chrome._ports[0].respond(nativeResponse(deferred, sanitizeResult()));

    expect(replaced.error).toBe("session-expired");
    expect((await operation).error).toBe("session-expired");
    expect(chrome._ports[0].sent.filter((message) => message.operation === "reidentify")).toHaveLength(0);
  });

  it("disposes a completed scope when a same-origin document is replaced", async () => {
    const chrome = makeChrome();
    await loadWorker(chrome);
    expect(
      (
        await invoke(
          chrome,
          { type: "sanitize", text: "synthetic-old-document" },
          tabSender(7, "https://chatgpt.com", "doc-1")
        )
      ).ok
    ).toBe(true);
    const oldContext = chrome._ports[0].sent.find(
      (message) => message.operation === "sanitize"
    ).context_id;

    expect(
      (
        await invoke(
          chrome,
          { type: "health" },
          tabSender(7, "https://chatgpt.com", "doc-2")
        )
      ).ok
    ).toBe(true);
    const expired = await invoke(
      chrome,
      { type: "reidentify", text: "masked-from-old-document" },
      tabSender(7, "https://chatgpt.com", "doc-2")
    );
    const fresh = await invoke(
      chrome,
      { type: "sanitize", text: "synthetic-new-document" },
      tabSender(7, "https://chatgpt.com", "doc-2")
    );
    const sanitizeContexts = chrome._ports[0].sent
      .filter((message) => message.operation === "sanitize")
      .map((message) => message.context_id);

    expect(expired.error).toBe("session-expired");
    expect(fresh.ok).toBe(true);
    expect(chrome._ports[0].sent).toContainEqual(
      expect.objectContaining({ context_id: oldContext, operation: "scope_close" })
    );
    expect(sanitizeContexts).toHaveLength(2);
    expect(sanitizeContexts[1]).not.toBe(oldContext);
    expect(chrome._ports[0].sent.filter((message) => message.operation === "reidentify")).toHaveLength(0);
  });

  it("does not open a scope after deferred mode lookup loses its tab document", async () => {
    let resolveMode;
    const mode = new Promise((resolve) => {
      resolveMode = resolve;
    });
    const chrome = makeChrome();
    chrome.storage.local.get.mockReturnValueOnce(mode);
    await loadWorker(chrome);
    const operation = invoke(
      chrome,
      { type: "sanitize", text: "synthetic-stale-tab" },
      tabSender(7, "https://chatgpt.com", "doc-1")
    );
    await flush();

    expect(
      (
        await invoke(
          chrome,
          { type: "health" },
          tabSender(7, "https://chatgpt.com", "doc-2")
        )
      ).ok
    ).toBe(true);
    resolveMode({ mode: "token" });
    await flush();

    expect((await operation).error).toBe("session-expired");
    expect(
      chrome._ports[0].sent.filter((message) =>
        ["scope_open", "sanitize"].includes(message.operation)
      )
    ).toHaveLength(0);
  });

  it("disconnect invalidates pending data, clears state, and never replays it", async () => {
    const chrome = makeChrome(
      () =>
        new NativePort((request) =>
          request.operation === "sanitize" ? undefined : defaultNativeHandler(request)
        )
    );
    await loadWorker(chrome);
    const operation = invoke(chrome, { type: "sanitize", text: "synthetic-sentinel" });
    await flush();
    chrome._ports[0].disconnect();
    expect((await operation).error).toBe("native-unavailable");
    expect(chrome.storage.session.clear).toHaveBeenCalled();
    expect(chrome.tabs.sendMessage).toHaveBeenCalledWith(7, {
      type: "aiguard-native-state",
      state: "session-expired",
    });
    expect(chrome._ports.flatMap((port) => port.sent).filter((message) => message.operation === "sanitize")).toHaveLength(1);
    const expired = await invoke(chrome, { type: "reidentify", text: "masked" });
    expect(expired.error).toBe("session-expired");
  });

  it("a new worker generation starts empty and cannot restore an old mapping", async () => {
    const firstGeneration = makeChrome();
    await loadWorker(firstGeneration);
    expect((await invoke(firstGeneration, { type: "sanitize", text: "synthetic" })).ok).toBe(true);

    const secondGeneration = makeChrome();
    await loadWorker(secondGeneration);
    const expired = await invoke(secondGeneration, {
      type: "reidentify",
      text: "masked-from-old-generation",
    });

    expect(expired.error).toBe("session-expired");
    expect(secondGeneration.storage.session.clear).toHaveBeenCalled();
    expect(
      secondGeneration._ports[0].sent.map((message) => message.operation)
    ).toEqual(["health"]);
  });

  it("rejects non-top, inactive, missing-document, and inconsistent-origin senders before PII", async () => {
    const chrome = makeChrome();
    await loadWorker(chrome);
    const senders = [
      { ...tabSender(), frameId: 1 },
      { ...tabSender(), documentLifecycle: "prerender" },
      { ...tabSender(), documentId: "" },
      { ...tabSender(), origin: "https://claude.ai" },
    ];
    for (const sender of senders) {
      const response = await invoke(chrome, { type: "sanitize", text: "synthetic" }, sender);
      expect(response.error).toBe("invalid-sender-context");
    }
    expect(chrome._ports[0].sent.filter((message) => message.operation === "sanitize")).toHaveLength(0);
  });

  it("uses isolated panel scopes and closes only the disconnected panel", async () => {
    const chrome = makeChrome();
    await loadWorker(chrome);
    const first = makePanelPort();
    first.sender.tab = { id: 23, url: "https://chatgpt.com/c/synthetic" };
    first.sender.frameId = 0;
    first.sender.documentLifecycle = "active";
    const second = makePanelPort();
    chrome.runtime.onConnect.emit(first);
    chrome.runtime.onConnect.emit(second);
    first.onMessage.emit({
      message: { type: "sanitize", text: "panel-a", mode: "token" },
      panel_request_id: "panel-a",
    });
    second.onMessage.emit({
      message: { type: "sanitize", text: "panel-b", mode: "surrogate" },
      panel_request_id: "panel-b",
    });
    await flush();
    const contexts = chrome._ports[0].sent
      .filter((message) => message.operation === "sanitize")
      .map((message) => message.context_id);
    expect(new Set(contexts).size).toBe(2);

    first.onDisconnect.emit();
    await flush();
    const closes = chrome._ports[0].sent.filter((message) => message.operation === "scope_close");
    expect(closes).toHaveLength(1);
    expect(closes[0].context_id).toBe(contexts[0]);
    expect(first.outgoing.at(-1).response.ok).toBe(true);
    expect(second.outgoing.at(-1).response.ok).toBe(true);
  });

  it("drops an in-flight panel result and closes only that panel scope", async () => {
    let deferred;
    const chrome = makeChrome(
      () =>
        new NativePort((request) => {
          if (request.operation === "sanitize") {
            deferred = request;
            return undefined;
          }
          return defaultNativeHandler(request);
        })
    );
    await loadWorker(chrome);
    const panel = makePanelPort();
    chrome.runtime.onConnect.emit(panel);
    panel.onMessage.emit({
      message: { type: "sanitize", text: "panel-synthetic", mode: "token" },
      panel_request_id: "panel-inflight",
    });
    await flush();
    panel.onDisconnect.emit();
    chrome._ports[0].respond(nativeResponse(deferred, sanitizeResult()));
    await flush();

    expect(panel.outgoing).toHaveLength(0);
    expect(chrome._ports[0].sent.filter((message) => message.operation === "scope_close")).toHaveLength(1);
  });

  it("does not open a scope after deferred mode lookup loses its panel", async () => {
    let resolveMode;
    const mode = new Promise((resolve) => {
      resolveMode = resolve;
    });
    const chrome = makeChrome();
    chrome.storage.local.get.mockReturnValueOnce(mode);
    await loadWorker(chrome);
    const panel = makePanelPort();
    chrome.runtime.onConnect.emit(panel);
    panel.onMessage.emit({
      message: { type: "sanitize", text: "panel-stale-synthetic" },
      panel_request_id: "panel-stale-mode",
    });
    await flush();

    panel.onDisconnect.emit();
    resolveMode({ mode: "token" });
    await flush();

    expect(panel.outgoing).toHaveLength(0);
    expect(
      chrome._ports[0].sent.filter((message) =>
        ["scope_open", "sanitize"].includes(message.operation)
      )
    ).toHaveLength(0);
  });

  it("fails closed on a malformed native response before returning a DTO", async () => {
    const chrome = makeChrome(
      () =>
        new NativePort((request) => {
          const response = defaultNativeHandler(request);
          if (request.operation === "sanitize") response.unknown = "synthetic-sentinel";
          return response;
        })
    );
    await loadWorker(chrome);
    const response = await invoke(chrome, { type: "sanitize", text: "synthetic" });
    expect(response).toEqual({ ok: false, status: 0, error: "contract-invalid" });
    expect(chrome._ports[0].closed).toBe(true);
  });

  it("resolves an admitted fixed broker failure and disposes only its scope", async () => {
    const chrome = makeChrome(
      () =>
        new NativePort((request) => {
          if (request.operation === "sanitize") {
            return {
              error: { code: "residual_pii" },
              native_protocol_version: 1,
              ok: false,
              request_id: request.request_id,
            };
          }
          return defaultNativeHandler(request);
        })
    );
    await loadWorker(chrome);

    const response = await invoke(chrome, { type: "sanitize", text: "synthetic" });

    expect(response).toEqual({ ok: false, status: 0, error: "residual_pii" });
    expect(chrome._ports[0].closed).toBe(false);
    expect(chrome._ports[0].sent.map((message) => message.operation)).toEqual([
      "health",
      "scope_open",
      "sanitize",
      "scope_close",
    ]);
  });

  it("resolves the current request while rejecting an unknown fixed error", async () => {
    const chrome = makeChrome(
      () =>
        new NativePort((request) => {
          if (request.operation === "sanitize") {
            return {
              error: { code: "synthetic-unknown" },
              native_protocol_version: 1,
              ok: false,
              request_id: request.request_id,
            };
          }
          return defaultNativeHandler(request);
        })
    );
    await loadWorker(chrome);

    const response = await invoke(chrome, { type: "sanitize", text: "synthetic" });

    expect(response).toEqual({ ok: false, status: 0, error: "contract-invalid" });
    expect(chrome._ports[0].closed).toBe(true);
  });
});
