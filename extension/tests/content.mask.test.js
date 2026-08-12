// EXT-2/EXT-3: Mask must fail closed and visibly.
//
// EXT-2: doMask captured the composer before the await and trusted
// writeComposer's unconditional `true`, reporting "ปกปิด n รายการ" even when
// the raw text was still sitting in the composer (fails-open false positive).
// After the fix, success is only reported when a re-queried composer actually
// reads back the sanitized text.
//
// EXT-3: a failed Mask only flipped a small corner status while the site's
// Send button stayed live. After the fix, any mask failure raises a prominent
// blocking overlay warning on top of the tiny status.
import { afterEach, describe, expect, it, vi } from "vitest";

function makeSite({ writeActuallyWrites, writeTransform = (text) => text }) {
  const textarea = document.createElement("textarea");
  document.body.appendChild(textarea);
  return {
    _textarea: textarea,
    name: "fake",
    composer: () => textarea,
    assistantMessages: () => [],
    readComposer: (el) => el.value || "",
    sameComposerText: (_el, actual, expected) => actual === expected,
    // Mirrors the real writeComposer contract under attack: claims success
    // unconditionally, whether or not the write landed.
    writeComposer: (el, text) => {
      if (writeActuallyWrites) el.value = writeTransform(text);
      return true;
    },
  };
}

function makeChrome(resp, sent = []) {
  return {
    runtime: {
      getURL: (p) => "chrome-extension://aiguard/" + p,
      sendMessage: (msg, cb) => {
        sent.push(msg);
        cb(
          msg.type === "health"
            ? {
                ok: true,
                status: 200,
                data: {
                  status: "ok",
                  version: "2.5.0",
                  contract_version: 2,
                  capabilities: {
                    control_token_required: true,
                    api_key_required: false,
                  },
                },
              }
            : resp
        );
      },
    },
  };
}

function sanitizeData() {
  return {
    sanitized_text: "ผมชื่อ [ชื่อ_1] โทร [โทรศัพท์_1]",
    detected_entity_count: 2,
    replacement_count: 2,
    entity_type_counts: { NAME: 1, PHONE: 1 },
    highlights: [
      { start: 7, end: 15, data_type: "NAME", redact_type: "TB" },
      { start: 20, end: 32, data_type: "PHONE", redact_type: "FP" },
    ],
    section26_categories: [],
    guard_findings: [],
    warnings: [],
    safety: { status: "pass", residual_count: 0 },
  };
}

// Capture shadow roots on creation so tests can read inside the closed
// overlay tree (EXT-4 moved it out of page reach; content scripts run in an
// isolated world, so a real page cannot replicate this hook).
let capturedShadows;

async function loadContent(site, chrome) {
  document.documentElement.innerHTML = "<head></head><body></body>";
  document.body.appendChild(site._textarea);
  global.chrome = chrome;
  window.AIGUARD_SITES = site;
  capturedShadows = [];
  const orig = Element.prototype.attachShadow;
  vi.spyOn(Element.prototype, "attachShadow").mockImplementation(function (init) {
    const root = orig.call(this, init);
    capturedShadows.push(root);
    return root;
  });
  vi.resetModules();
  await import("../contract-v2.js");
  await import("../content.js");
  await Promise.resolve();
}

function statusEl() {
  return document.querySelector("span.aiguard-status");
}

function warningOverlay() {
  return document.querySelector(".aiguard-overlay-host");
}

function warningText() {
  return capturedShadows.map((s) => s.textContent).join(" ");
}

async function clickMask(waitMs = 600) {
  // bar order: logo, Mask PII, Restore PII, status — Mask is the first button
  document.querySelector("button.aiguard-btn").click();
  await new Promise((r) => setTimeout(r, waitMs));
}

afterEach(() => {
  vi.restoreAllMocks();
  delete global.chrome;
  delete window.AIGUARD_SITES;
  delete global.AIGUARD_CONTRACT_V2;
});

describe("doMask verification (EXT-2)", () => {
  it("reports success only after reading the sanitized text back", async () => {
    const site = makeSite({ writeActuallyWrites: true });
    site._textarea.value = "ผมชื่อ สมชาย โทร 081-234-5678";
    const chrome = makeChrome({
      ok: true,
      data: sanitizeData(),
    });
    await loadContent(site, chrome);
    await clickMask();
    expect(site._textarea.value).toBe("ผมชื่อ [ชื่อ_1] โทร [โทรศัพท์_1]");
    expect(statusEl().textContent).toContain("ปกปิด 2 รายการ");
    expect(statusEl().className).toContain("aiguard-ok");
    expect(warningOverlay()).toBeNull();
  });

  it("fails closed when the write did not land in the composer", async () => {
    const site = makeSite({ writeActuallyWrites: false });
    site._textarea.value = "ผมชื่อ สมชาย โทร 081-234-5678";
    const chrome = makeChrome({
      ok: true,
      data: sanitizeData(),
    });
    await loadContent(site, chrome);
    await clickMask();
    // The raw text is still in the composer: no success report allowed.
    expect(statusEl().textContent).not.toContain("ปกปิด 2 รายการ");
    expect(statusEl().className).toContain("aiguard-err");
    // EXT-3: the failure must be prominent, not a corner whisper.
    expect(warningOverlay()).not.toBeNull();
  });

  it("accepts a controlled editor update that lands on the next cycle", async () => {
    const site = makeSite({ writeActuallyWrites: false });
    site._textarea.value = "ผมชื่อ สมชาย โทร 081-234-5678";
    site.writeComposer = (el, text) => {
      setTimeout(() => {
        el.value = text;
      }, 25);
      return true;
    };
    const chrome = makeChrome({
      ok: true,
      data: sanitizeData(),
    });
    await loadContent(site, chrome);
    await clickMask();
    expect(site._textarea.value).toBe("ผมชื่อ [ชื่อ_1] โทร [โทรศัพท์_1]");
    expect(statusEl().textContent).toContain("ปกปิด 2 รายการ");
    expect(warningOverlay()).toBeNull();
  });

  it("sends the exact composer representation to sanitize", async () => {
    const source = "  ผมชื่อ สมชาย\r\nโทร 081-234-5678\u200b  ";
    const sent = [];
    const site = makeSite({ writeActuallyWrites: true });
    site._textarea.value = source;
    const browserSource = site._textarea.value;
    const chrome = makeChrome({ ok: true, data: sanitizeData() }, sent);
    await loadContent(site, chrome);
    await clickMask();

    expect(sent.find((message) => message.type === "sanitize").text).toBe(browserSource);
  });

  it("fails closed when a host collapses sanitized whitespace", async () => {
    const site = makeSite({
      writeActuallyWrites: true,
      writeTransform: (text) => text.replace(/\s+/g, " "),
    });
    site._textarea.value = "source";
    const data = sanitizeData();
    data.sanitized_text = "A  [ชื่อ_1]\nB";
    const chrome = makeChrome({ ok: true, data });
    await loadContent(site, chrome);
    await clickMask();

    expect(statusEl().className).toContain("aiguard-err");
    expect(warningOverlay()).not.toBeNull();
  });

  it("does not erase the composer when a success payload has empty masked text", async () => {
    const source = "ข้อความต้นฉบับสังเคราะห์";
    const site = makeSite({ writeActuallyWrites: true });
    site._textarea.value = source;
    const data = sanitizeData();
    Object.assign(data, {
      sanitized_text: "",
      detected_entity_count: 0,
      replacement_count: 0,
      entity_type_counts: {},
      highlights: [],
    });
    const chrome = makeChrome({ ok: true, data });
    await loadContent(site, chrome);
    await clickMask();

    expect(site._textarea.value).toBe(source);
    expect(statusEl().className).toContain("aiguard-err");
    expect(warningOverlay()).not.toBeNull();
  });
});

describe("mask failure warning (EXT-3)", () => {
  it("raises a blocking overlay when the backend call fails", async () => {
    const site = makeSite({ writeActuallyWrites: true });
    site._textarea.value = "ผมชื่อ สมชาย โทร 081-234-5678";
    const chrome = makeChrome({ ok: false, status: 0, error: "unreachable" });
    await loadContent(site, chrome);
    await clickMask();
    expect(statusEl().className).toContain("aiguard-err");
    expect(warningOverlay()).not.toBeNull();
    // The warning must tell the user the raw text is still there.
    expect(warningText()).toContain("ยังไม่ได้ปกปิด");
  });

  it("overlay dismisses on close so the user can retry", async () => {
    const site = makeSite({ writeActuallyWrites: true });
    site._textarea.value = "ข้อความยาวพอสมควรหนึ่งบรรทัด";
    const chrome = makeChrome({ ok: false, status: 0, error: "unreachable" });
    await loadContent(site, chrome);
    await clickMask();
    expect(warningOverlay()).not.toBeNull();
    // The close button lives inside the closed shadow; reach it via the hook.
    capturedShadows[capturedShadows.length - 1].querySelector("button").click();
    expect(warningOverlay()).toBeNull();
  });
});
