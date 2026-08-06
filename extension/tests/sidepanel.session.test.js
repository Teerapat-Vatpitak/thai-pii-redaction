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
    session_id: "SP1",
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

function setupChrome() {
  sent = [];
  global.chrome = {
    runtime: {
      lastError: null,
      sendMessage: (message, cb) => {
        sent.push(message);
        // sanitize returns a session_id the panel should remember and resend
        if (message.type === "sanitize") {
          cb({ ok: true, status: 200, data: sanitizeData() });
        } else if (message.type === "health") {
          cb({ ok: true, status: 200, data: healthData() });
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
  delete global.AIGUARD_CONTRACT_V2;
  document.body.innerHTML = "";
});

describe("side panel sanitize session reuse (EXT-1)", () => {
  it("resends the panel's session_id on the second Mask", async () => {
    setupDom();
    setupChrome();
    setupBrowserApis();
    vi.resetModules();
    await import("../contract-v2.js");
    await import("../sidepanel.js");

    const flush = () => new Promise((r) => setTimeout(r, 0));
    await flush();

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

  it("sends source and restore text without trimming", async () => {
    setupDom();
    setupChrome();
    global.chrome.runtime.sendMessage = (message, cb) => {
      sent.push(message);
      if (message.type === "health") {
        cb({ ok: true, status: 200, data: healthData() });
      } else if (message.type === "sanitize") {
        cb({ ok: true, status: 200, data: sanitizeData() });
      } else {
        cb({
          ok: true,
          status: 200,
          data: {
            restored_text: "  restored  ",
            replaced_count: 1,
            leftover_count: 0,
            warnings: [],
          },
        });
      }
    };
    setupBrowserApis();
    vi.resetModules();
    await import("../contract-v2.js");
    await import("../sidepanel.js");
    const flush = () => new Promise((resolve) => setTimeout(resolve, 0));
    await flush();

    const source = "  นาย ก\r\n\u200b  ";
    document.getElementById("input").value = source;
    const browserSource = document.getElementById("input").value;
    document.getElementById("maskBtn").click();
    await flush();
    const reply = "  [ชื่อ_1]\r\n  ";
    document.getElementById("reply").value = reply;
    const browserReply = document.getElementById("reply").value;
    document.getElementById("restoreBtn").click();
    await flush();

    expect(sent.find((message) => message.type === "sanitize").text).toBe(browserSource);
    expect(sent.find((message) => message.type === "reidentify").text).toBe(browserReply);
  });

  it("keeps preview and copy disabled for an empty sanitize success payload", async () => {
    setupDom();
    setupChrome();
    global.chrome.runtime.sendMessage = (message, cb) => {
      sent.push(message);
      if (message.type === "health") {
        cb({ ok: true, status: 200, data: healthData() });
      } else {
        cb({
          ok: true,
          status: 200,
          data: {
            ...sanitizeData(),
            sanitized_text: "",
            detected_entity_count: 0,
            replacement_count: 0,
            entity_type_counts: {},
            highlights: [],
          },
        });
      }
    };
    setupBrowserApis();
    vi.resetModules();
    await import("../contract-v2.js");
    await import("../sidepanel.js");
    const flush = () => new Promise((resolve) => setTimeout(resolve, 0));
    await flush();

    document.getElementById("input").value = "ข้อความต้นฉบับสังเคราะห์";
    document.getElementById("maskBtn").click();
    await flush();

    expect(document.getElementById("maskedWrap").hidden).toBe(true);
    expect(document.getElementById("copyBtn").hidden).toBe(true);
    expect(document.getElementById("restoreBtn").disabled).toBe(true);
    expect(document.getElementById("msg").className).toContain("err");
  });
});

describe("restore status blocks unsafe results", () => {
  it("shows a count-only warning and does not render restored text", async () => {
    setupDom();
    setupChrome();
    // restore reply carries a foreign_tokens warning from the backend
    global.chrome.runtime.sendMessage = (message, cb) => {
      sent.push(message);
      if (message.type === "sanitize") {
        cb({ ok: true, status: 200, data: sanitizeData() });
      } else if (message.type === "health") {
        cb({ ok: true, status: 200, data: healthData() });
      } else {
        cb({
          ok: true,
          status: 200,
          data: {
            restored_text: "สมชาย",
            replaced_count: 1,
            leftover_count: 0,
            warnings: [{ code: "foreign_replacement", count: 3 }],
          },
        });
      }
    };
    setupBrowserApis();
    vi.resetModules();
    await import("../contract-v2.js");
    await import("../sidepanel.js");
    const flush = () => new Promise((r) => setTimeout(r, 0));
    await flush();

    document.getElementById("input").value = "นาย ก";
    document.getElementById("maskBtn").click();
    await flush();
    document.getElementById("reply").value = "[ชื่อ_1]";
    document.getElementById("restoreBtn").click();
    await flush();

    const msg = document.getElementById("msg");
    expect(msg.textContent).toContain("คำเตือน 3 รายการ");
    // setMsg (sidepanel.js) sets: m.className = "msg" + (kind ? " " + kind : "")
    expect(msg.className).toContain("err");
    expect(document.getElementById("out").hidden).toBe(true);
    expect(document.body.textContent).not.toContain("สมชาย");
  });
});

describe("side panel sanitized-space highlighting", () => {
  it("converts code-point offsets before slicing JavaScript text", async () => {
    setupDom();
    setupChrome();
    global.chrome.runtime.sendMessage = (message, cb) => {
      sent.push(message);
      if (message.type === "health") {
        cb({ ok: true, status: 200, data: healthData() });
      } else if (message.type === "sanitize") {
        cb({ ok: true, status: 200, data: sanitizeData("😀 [ชื่อ_1]") });
      } else {
        cb({ ok: true, status: 200, data: {} });
      }
    };
    setupBrowserApis();
    vi.resetModules();
    await import("../contract-v2.js");
    await import("../sidepanel.js");
    const flush = () => new Promise((resolve) => setTimeout(resolve, 0));
    await flush();

    document.getElementById("input").value = "synthetic";
    document.getElementById("maskBtn").click();
    await flush();

    expect(document.getElementById("masked").innerHTML).toContain(
      '<span class="chip chip--token">[ชื่อ_1]</span>'
    );
    expect(document.getElementById("masked").textContent).toBe("😀 [ชื่อ_1]");
  });
});
