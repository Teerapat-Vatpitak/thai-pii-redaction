// EXT-4: restored text is real PII. Rendering it into the host page's DOM
// hands it to every script the AI site runs (session replay, analytics) —
// the exact audience the whole product exists to keep it from. The overlay
// must live inside a CLOSED shadow root: the host element is visible in the
// page tree, but no page-side traversal can reach the text inside.
import { afterEach, describe, expect, it, vi } from "vitest";

const SECRET_PHONE = "081-234-5678";
const SECRET_NAME = "สมชาย ใจดี";

function makeSite() {
  const textarea = document.createElement("textarea");
  const reply = document.createElement("div");
  reply.textContent = "ติดต่อ [ชื่อ_1] ที่ [โทรศัพท์_1]";
  return {
    _textarea: textarea,
    _reply: reply,
    name: "fake",
    composer: () => textarea,
    assistantMessages: () => [reply],
    readComposer: (el) => el.value || "",
    sameComposerText: (_el, actual, expected) => actual === expected,
    writeComposer: (el, text) => {
      el.value = text;
      return true;
    },
  };
}

function makeChrome(dataOverrides = {}, lifecycleListeners = []) {
  return {
    runtime: {
      getURL: (p) => "chrome-extension://aiguard/" + p,
      onMessage: {
        addListener: (listener) => lifecycleListeners.push(listener),
      },
      sendMessage: (msg, cb) => {
        if (msg.type === "health") {
          cb({
            ok: true,
            data: {
              status: "ok",
              version: "2.5.0",
              contract_version: 2,
              capabilities: {
                control_token_required: true,
                api_key_required: false,
              },
            },
          });
          return;
        }
        if (msg.type === "sanitize") {
          cb({
            ok: true,
            data: {
              sanitized_text: "[NAME_1]",
              detected_entity_count: 1,
              replacement_count: 1,
              entity_type_counts: { NAME: 1 },
              highlights: [
                { start: 0, end: 8, data_type: "NAME", redact_type: "TB" },
              ],
              section26_categories: [],
              guard_findings: [],
              warnings: [],
              safety: { status: "pass", residual_count: 0 },
            },
          });
          return;
        }
        cb({
          ok: true,
          data: {
            restored_text: `ติดต่อ ${SECRET_NAME} ที่ ${SECRET_PHONE}`,
            replaced_count: 2,
            leftover_count: 0,
            warnings: [],
            ...dataOverrides,
          },
        });
      },
    },
  };
}

// Test-side hook: capture shadow roots as they are created so assertions can
// look INSIDE the closed tree. A real host page cannot do this — content
// scripts run in an isolated world with their own Element.prototype, so a
// page-side attachShadow patch never sees our calls.
let capturedShadows;
function captureAttachShadow() {
  capturedShadows = [];
  const orig = Element.prototype.attachShadow;
  vi.spyOn(Element.prototype, "attachShadow").mockImplementation(function (init) {
    const root = orig.call(this, init);
    capturedShadows.push(root);
    return root;
  });
}

async function loadAndRestore(dataOverrides = {}, lifecycleListeners = []) {
  const site = makeSite();
  document.documentElement.innerHTML = "<head></head><body></body>";
  document.body.appendChild(site._textarea);
  document.body.appendChild(site._reply);
  global.chrome = makeChrome(dataOverrides, lifecycleListeners);
  window.AIGUARD_SITES = site;
  captureAttachShadow();
  vi.resetModules();
  await import("../contract-v2.js");
  await import("../content.js");
  await Promise.resolve();
  site._textarea.value = "synthetic";
  // A fresh native connection requires a user-initiated Mask before Restore.
  document.querySelectorAll("button.aiguard-btn")[0].click();
  await new Promise((r) => setTimeout(r, 0));
  document.querySelectorAll("button.aiguard-btn")[1].click();
  await new Promise((r) => setTimeout(r, 0));
}

afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
  vi.restoreAllMocks();
  delete global.chrome;
  delete window.AIGUARD_SITES;
  delete global.AIGUARD_CONTRACT_V2;
});

describe("restore overlay isolation (EXT-4)", () => {
  it("keeps restored PII out of the page-reachable DOM", async () => {
    await loadAndRestore();
    // The overlay exists (its host is in the page tree)...
    const host = document.querySelector(".aiguard-overlay-host");
    expect(host).not.toBeNull();
    // ...but nothing a page script can traverse contains the restored PII.
    expect(document.documentElement.textContent).not.toContain(SECRET_PHONE);
    expect(document.documentElement.textContent).not.toContain(SECRET_NAME);
    expect(document.documentElement.innerHTML).not.toContain(SECRET_PHONE);
    // Closed shadow: the page cannot open the host's shadow tree either.
    expect(host.shadowRoot).toBeNull();
    // And the text genuinely IS displayed to the user inside the shadow —
    // hiding PII by not rendering it would pass the checks above.
    const shadowText = capturedShadows.map((s) => s.textContent).join(" ");
    expect(shadowText).toContain(SECRET_PHONE);
    expect(shadowText).toContain(SECRET_NAME);
  });

  it("dismisses on Escape so the PII does not linger on screen", async () => {
    await loadAndRestore();
    expect(document.querySelector(".aiguard-overlay-host")).not.toBeNull();
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    expect(document.querySelector(".aiguard-overlay-host")).toBeNull();
  });

  it("recovers Mask after a PII-free reconnect without reviving Restore", async () => {
    const lifecycleListeners = [];
    await loadAndRestore({}, lifecycleListeners);
    expect(document.querySelectorAll("button.aiguard-btn")[1].disabled).toBe(false);
    expect(document.querySelector(".aiguard-overlay-host")).not.toBeNull();

    lifecycleListeners[0]({
      type: "aiguard-native-state",
      state: "session-expired",
    });
    expect(document.querySelectorAll("button.aiguard-btn")[0].disabled).toBe(true);
    expect(document.querySelectorAll("button.aiguard-btn")[1].disabled).toBe(true);
    expect(document.querySelector(".aiguard-overlay-host")).toBeNull();

    await new Promise((resolve) => setTimeout(resolve, 300));
    expect(document.querySelectorAll("button.aiguard-btn")[0].disabled).toBe(false);
    expect(document.querySelectorAll("button.aiguard-btn")[1].disabled).toBe(true);
  });

  it("keeps retrying PII-free health after the initial backoff is exhausted", async () => {
    vi.useFakeTimers();
    const site = makeSite();
    document.documentElement.innerHTML = "<head></head><body></body>";
    document.body.appendChild(site._textarea);
    document.body.appendChild(site._reply);
    const messages = [];
    let healthAttempts = 0;
    global.chrome = makeChrome();
    const originalSend = global.chrome.runtime.sendMessage;
    global.chrome.runtime.sendMessage = (message, callback) => {
      messages.push(message);
      if (message.type === "health" && healthAttempts < 5) {
        healthAttempts += 1;
        callback({ ok: false, status: 503, error: "native-unavailable" });
        return;
      }
      originalSend(message, callback);
    };
    window.AIGUARD_SITES = site;
    vi.resetModules();
    await import("../contract-v2.js");
    await import("../content.js");
    await vi.advanceTimersByTimeAsync(8_000);

    expect(healthAttempts).toBe(5);
    expect(messages).toHaveLength(6);
    expect(messages.every((message) => message.type === "health")).toBe(true);
    expect(document.querySelectorAll("button.aiguard-btn")[0].disabled).toBe(false);
    expect(document.querySelectorAll("button.aiguard-btn")[1].disabled).toBe(true);
  });
});

describe("unsafe restoration blocking", () => {
  it("does not render warning-bearing restored text", async () => {
    await loadAndRestore({ warnings: [{ code: "foreign_replacement", count: 2 }] });
    const shadowText = capturedShadows.map((s) => s.textContent).join(" ");
    expect(shadowText).not.toContain(SECRET_PHONE);
    expect(document.querySelector(".aiguard-overlay-host")).toBeNull();
    expect(document.querySelector(".aiguard-status").className).toContain("aiguard-err");
  });

  it("does not render incomplete restored text", async () => {
    await loadAndRestore({ leftover_count: 1 });
    expect(document.querySelector(".aiguard-overlay-host")).toBeNull();
    expect(document.documentElement.textContent).not.toContain(SECRET_PHONE);
  });
});
