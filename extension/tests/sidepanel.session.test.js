import { afterEach, describe, expect, it, vi } from "vitest";

function setupDom() {
  document.body.innerHTML = `
    <span id="dot"></span><span id="conn"></span>
    <div class="seg__opt" data-mode="token" aria-selected="true"></div>
    <div class="seg__opt" data-mode="surrogate"></div>
    <textarea id="input"></textarea>
    <button id="maskBtn"></button>
    <div id="maskedWrap" hidden><div id="masked"></div><span id="count"></span></div>
    <button id="copyBtn" hidden></button>
    <button id="restoreBtn" disabled></button>
    <textarea id="reply"></textarea>
    <div id="out" hidden></div>
    <div id="msg"></div>
    <button id="themeBtn"></button>
  `;
}

function event() {
  const listeners = [];
  return {
    addListener(listener) {
      listeners.push(listener);
    },
    emit(value) {
      for (const listener of listeners) listener(value);
    },
  };
}

function healthData() {
  return {
    status: "ok",
    version: "2.5.0",
    contract_version: 2,
    capabilities: { control_token_required: true, api_key_required: false },
  };
}

function sanitizeData(text = "[ชื่อ_1]") {
  return {
    sanitized_text: text,
    detected_entity_count: 1,
    replacement_count: 1,
    entity_type_counts: { NAME: 1 },
    highlights: [
      {
        start: Array.from(text).length - 8,
        end: Array.from(text).length,
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

function setupChrome(handler = null) {
  const sent = [];
  const ports = [];
  const respond =
    handler ||
    ((message) => {
      if (message.type === "health") return { ok: true, status: 200, data: healthData() };
      if (message.type === "sanitize") {
        return { ok: true, status: 200, data: sanitizeData() };
      }
      return {
        ok: true,
        status: 200,
        data: {
          restored_text: "synthetic-restored",
          replaced_count: 1,
          leftover_count: 0,
          warnings: [],
        },
      };
    });
  global.chrome = {
    runtime: {
      connect: vi.fn(() => {
        const onMessage = event();
        const onDisconnect = event();
        const port = {
          onDisconnect,
          onMessage,
          postMessage(envelope) {
            sent.push(structuredClone(envelope.message));
            const response = respond(envelope.message);
            queueMicrotask(() =>
              onMessage.emit({
                panel_request_id: envelope.panel_request_id,
                response,
                type: "response",
              })
            );
          },
        };
        ports.push(port);
        return port;
      }),
      lastError: null,
    },
    storage: { local: { get: (_key, callback) => callback({ mode: "token" }), set: () => {} } },
  };
  return { ports, sent };
}

function setupBrowserApis() {
  window.matchMedia = () => ({ matches: false, addEventListener: () => {} });
  Object.defineProperty(navigator, "clipboard", {
    value: { writeText: () => Promise.resolve() },
    configurable: true,
  });
  vi.spyOn(global, "setInterval").mockReturnValue(0);
}

async function flush() {
  await Promise.resolve();
  await new Promise((resolve) => setTimeout(resolve, 0));
}

async function loadPanel(handler = null) {
  setupDom();
  const harness = setupChrome(handler);
  setupBrowserApis();
  vi.resetModules();
  await import("../contract-v2.js");
  await import("../sidepanel.js");
  await flush();
  return harness;
}

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  delete global.chrome;
  delete global.AIGUARD_CONTRACT_V2;
  document.body.innerHTML = "";
});

describe("side panel service-worker scope", () => {
  it("reuses one panel port without receiving or sending a session handle", async () => {
    const { sent } = await loadPanel();
    document.getElementById("input").value = "synthetic-a";
    document.getElementById("maskBtn").click();
    await flush();
    document.getElementById("input").value = "synthetic-b";
    document.getElementById("maskBtn").click();
    await flush();
    const sanitizes = sent.filter((message) => message.type === "sanitize");
    expect(sanitizes).toHaveLength(2);
    expect(JSON.stringify(sanitizes)).not.toContain("session_id");
    expect(chrome.runtime.connect).toHaveBeenCalledTimes(1);
  });

  it("sends source and restore text without trimming", async () => {
    const { sent } = await loadPanel();
    const source = "  synthetic source\r\n\u200b  ";
    document.getElementById("input").value = source;
    document.getElementById("maskBtn").click();
    await flush();
    const reply = "  [NAME_1]\r\n  ";
    document.getElementById("reply").value = reply;
    document.getElementById("restoreBtn").click();
    await flush();
    expect(sent.find((message) => message.type === "sanitize").text).toBe(
      document.getElementById("input").value
    );
    expect(sent.find((message) => message.type === "reidentify").text).toBe(
      document.getElementById("reply").value
    );
  });

  it("keeps all write surfaces disabled for malformed sanitize success", async () => {
    await loadPanel((message) => {
      if (message.type === "health") return { ok: true, status: 200, data: healthData() };
      return {
        ok: true,
        status: 200,
        data: sanitizeData(""),
      };
    });
    document.getElementById("input").value = "synthetic";
    document.getElementById("maskBtn").click();
    await flush();
    expect(document.getElementById("maskedWrap").hidden).toBe(true);
    expect(document.getElementById("copyBtn").hidden).toBe(true);
    expect(document.getElementById("restoreBtn").disabled).toBe(true);
  });

  it("blocks warning-bearing restore text", async () => {
    await loadPanel((message) => {
      if (message.type === "health") return { ok: true, status: 200, data: healthData() };
      if (message.type === "sanitize") return { ok: true, status: 200, data: sanitizeData() };
      return {
        ok: true,
        status: 200,
        data: {
          restored_text: "synthetic-restored",
          replaced_count: 1,
          leftover_count: 0,
          warnings: [{ code: "foreign_replacement", count: 3 }],
        },
      };
    });
    document.getElementById("input").value = "synthetic";
    document.getElementById("maskBtn").click();
    await flush();
    document.getElementById("reply").value = "[NAME_1]";
    document.getElementById("restoreBtn").click();
    await flush();
    expect(document.getElementById("out").hidden).toBe(true);
    expect(document.body.textContent).not.toContain("synthetic-restored");
  });

  it("invalidates restore immediately on native lifecycle loss", async () => {
    const { ports } = await loadPanel();
    document.getElementById("input").value = "synthetic";
    document.getElementById("maskBtn").click();
    await flush();
    expect(document.getElementById("restoreBtn").disabled).toBe(false);
    ports[0].onMessage.emit({ type: "lifecycle", state: "session-expired" });
    expect(document.getElementById("restoreBtn").disabled).toBe(true);
    expect(document.getElementById("copyBtn").hidden).toBe(true);
  });

  it("reconnects with PII-free health and never revives the old panel session", async () => {
    const { ports, sent } = await loadPanel();
    document.getElementById("input").value = "synthetic";
    document.getElementById("maskBtn").click();
    await flush();
    expect(document.getElementById("restoreBtn").disabled).toBe(false);

    const beforeDisconnect = sent.length;
    vi.useFakeTimers();
    ports[0].onDisconnect.emit();
    expect(document.getElementById("restoreBtn").disabled).toBe(true);
    expect(document.getElementById("copyBtn").hidden).toBe(true);

    await vi.advanceTimersByTimeAsync(250);
    expect(chrome.runtime.connect).toHaveBeenCalledTimes(2);
    expect(sent.slice(beforeDisconnect).map((message) => message.type)).toEqual(["health"]);
    expect(document.getElementById("maskBtn").disabled).toBe(false);

    document.getElementById("reply").value = "[NAME_1]";
    document.getElementById("restoreBtn").click();
    await vi.runAllTicks();
    expect(sent.slice(beforeDisconnect).some((message) => message.type === "reidentify")).toBe(
      false
    );
  });

  it("converts code-point highlight offsets before rendering", async () => {
    await loadPanel((message) => {
      if (message.type === "health") return { ok: true, status: 200, data: healthData() };
      return { ok: true, status: 200, data: sanitizeData("😀 [ชื่อ_1]") };
    });
    document.getElementById("input").value = "synthetic";
    document.getElementById("maskBtn").click();
    await flush();
    expect(document.getElementById("masked").innerHTML).toContain(
      '<span class="chip chip--token">[ชื่อ_1]</span>'
    );
  });
});
