// EXT-1 (side-panel path): the side panel must reuse its own session_id on the
// next Mask so multi-turn token numbering stays consistent. The panel's message
// sender has no tab, so background.js cannot key reuse on tabId — the panel has
// to pass its stored session_id explicitly in the sanitize message.
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

let sent;

function setupChrome() {
  sent = [];
  global.chrome = {
    runtime: {
      lastError: null,
      sendMessage: (message, cb) => {
        sent.push(message);
        // sanitize returns a session_id the panel should remember and resend
        if (message.type === "sanitize") {
          cb({ ok: true, status: 200, data: { session_id: "SP1", sanitized_text: "[ชื่อ_1]", entities: [] } });
        } else if (message.type === "health") {
          cb({ ok: true, status: 200, data: { version: "test" } });
        } else {
          cb({ ok: true, status: 200, data: {} });
        }
      },
    },
    storage: { local: { get: (_k, cb) => cb({ mode: "token" }), set: () => {} } },
  };
}

function setupBrowserApis() {
  window.matchMedia = () => ({ matches: false, addEventListener: () => {} });
  Object.defineProperty(navigator, "clipboard", {
    value: { writeText: () => Promise.resolve() },
    configurable: true,
  });
  vi.spyOn(global, "setInterval").mockReturnValue(0);
}

afterEach(() => {
  vi.restoreAllMocks();
  delete global.chrome;
  document.body.innerHTML = "";
});

describe("side panel sanitize session reuse (EXT-1)", () => {
  it("resends the panel's session_id on the second Mask", async () => {
    setupDom();
    setupChrome();
    setupBrowserApis();
    vi.resetModules();
    await import("../sidepanel.js");

    const flush = () => new Promise((r) => setTimeout(r, 0));

    document.getElementById("input").value = "นาย ก";
    document.getElementById("maskBtn").click();
    await flush();

    document.getElementById("input").value = "นาย ข";
    document.getElementById("maskBtn").click();
    await flush();

    const sanitizes = sent.filter((m) => m.type === "sanitize");
    expect(sanitizes.length).toBe(2);
    expect(sanitizes[1].session_id).toBe("SP1");
  });
});
