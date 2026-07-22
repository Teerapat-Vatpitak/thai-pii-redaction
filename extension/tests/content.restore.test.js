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
    readComposer: (el) => (el.value || "").trim(),
    writeComposer: (el, text) => {
      el.value = text;
      return true;
    },
  };
}

function makeChrome() {
  return {
    runtime: {
      getURL: (p) => "chrome-extension://aiguard/" + p,
      sendMessage: (msg, cb) =>
        cb({
          ok: true,
          data: {
            restored_text: `ติดต่อ ${SECRET_NAME} ที่ ${SECRET_PHONE}`,
            replaced_count: 2,
            leftover_tokens: [],
          },
        }),
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

async function loadAndRestore() {
  const site = makeSite();
  document.documentElement.innerHTML = "<head></head><body></body>";
  document.body.appendChild(site._textarea);
  document.body.appendChild(site._reply);
  global.chrome = makeChrome();
  window.AIGUARD_SITES = site;
  captureAttachShadow();
  vi.resetModules();
  await import("../content.js");
  // bar order: logo, Mask PII, Restore PII — Restore is the second button
  document.querySelectorAll("button.aiguard-btn")[1].click();
  await new Promise((r) => setTimeout(r, 0));
}

afterEach(() => {
  vi.restoreAllMocks();
  delete global.chrome;
  delete window.AIGUARD_SITES;
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
});
