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

function makeSite({ writeActuallyWrites }) {
  const textarea = document.createElement("textarea");
  document.body.appendChild(textarea);
  return {
    _textarea: textarea,
    name: "fake",
    composer: () => textarea,
    assistantMessages: () => [],
    readComposer: (el) => (el.value || "").trim(),
    // Mirrors the real writeComposer contract under attack: claims success
    // unconditionally, whether or not the write landed.
    writeComposer: (el, text) => {
      if (writeActuallyWrites) el.value = text;
      return true;
    },
  };
}

function makeChrome(resp) {
  return {
    runtime: {
      getURL: (p) => "chrome-extension://aiguard/" + p,
      sendMessage: (msg, cb) => cb(resp),
    },
  };
}

async function loadContent(site, chrome) {
  document.documentElement.innerHTML = "<head></head><body></body>";
  document.body.appendChild(site._textarea);
  global.chrome = chrome;
  window.AIGUARD_SITES = site;
  vi.resetModules();
  await import("../content.js");
}

function statusEl() {
  return document.querySelector("span.aiguard-status");
}

function warningOverlay() {
  return document.querySelector(".aiguard-overlay-back");
}

async function clickMask() {
  // bar order: logo, Mask PII, Restore PII, status — Mask is the first button
  document.querySelector("button.aiguard-btn").click();
  await new Promise((r) => setTimeout(r, 0));
}

afterEach(() => {
  vi.restoreAllMocks();
  delete global.chrome;
  delete window.AIGUARD_SITES;
});

describe("doMask verification (EXT-2)", () => {
  it("reports success only after reading the sanitized text back", async () => {
    const site = makeSite({ writeActuallyWrites: true });
    site._textarea.value = "ผมชื่อ สมชาย โทร 081-234-5678";
    const chrome = makeChrome({
      ok: true,
      data: { sanitized_text: "ผมชื่อ [ชื่อ_1] โทร [โทรศัพท์_1]", entities: [{}, {}] },
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
      data: { sanitized_text: "ผมชื่อ [ชื่อ_1] โทร [โทรศัพท์_1]", entities: [{}, {}] },
    });
    await loadContent(site, chrome);
    await clickMask();
    // The raw text is still in the composer: no success report allowed.
    expect(statusEl().textContent).not.toContain("ปกปิด 2 รายการ");
    expect(statusEl().className).toContain("aiguard-err");
    // EXT-3: the failure must be prominent, not a corner whisper.
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
    expect(warningOverlay().textContent).toContain("ยังไม่ได้ปกปิด");
  });

  it("overlay dismisses on close so the user can retry", async () => {
    const site = makeSite({ writeActuallyWrites: true });
    site._textarea.value = "ข้อความยาวพอสมควรหนึ่งบรรทัด";
    const chrome = makeChrome({ ok: false, status: 0, error: "unreachable" });
    await loadContent(site, chrome);
    await clickMask();
    const overlay = warningOverlay();
    expect(overlay).not.toBeNull();
    overlay.querySelector("button").click();
    expect(warningOverlay()).toBeNull();
  });
});
