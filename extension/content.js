// AI Guard content script.
//
// Injects a floating control bar (Mask PII / Restore PII) on the supported AI
// chat sites (ChatGPT, Claude, Gemini, Grok, Perplexity, GLM/Z.ai), plus a
// best-effort "Restore PII" button on each AI message. All
// backend calls go through the service worker (background.js); this script
// only touches the DOM. DOM is built with createElement/textContent only --
// never innerHTML with backend data.

(function () {
  const SITE = window.AIGUARD_SITES;
  if (!SITE) return;
  const CONTRACT = globalThis.AIGUARD_CONTRACT_V2;
  if (!CONTRACT) return;

  const PREFIX = "aiguard-";
  const MAX_HEALTH_RETRY_DELAY_MS = 30_000;
  let backendReady = false;
  let healthRetryAttempts = 0;
  let healthRetryTimer = null;
  let sessionAvailable = false;

  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = PREFIX + cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function send(message) {
    return new Promise((resolve) => {
      try {
        chrome.runtime.sendMessage(message, (resp) => {
          if (chrome.runtime.lastError) {
            resolve({ ok: false, status: 0, error: "native-unavailable" });
          } else {
            resolve(resp);
          }
        });
      } catch {
        resolve({ ok: false, status: 0, error: "native-unavailable" });
      }
    });
  }

  function backendError(resp) {
    if (resp && resp.error === "session-expired") return "เซสชันหมดอายุ ปกปิดใหม่อีกครั้ง";
    return "ติดตั้งหรือซ่อมแซม AI Guard Desktop companion";
  }

  // ---- floating control bar ---------------------------------------------
  const bar = el("div", "bar");
  const logo = el("img", "logo");
  logo.src = chrome.runtime.getURL("icons/icon32.png");
  logo.alt = "AI Guard";
  const maskBtn = el("button", "btn", "Mask PII");
  // el() prefixes only the first token, so the ghost class is written pre-prefixed:
  // classes become "aiguard-btn aiguard-ghost" to match content.css .aiguard-btn.aiguard-ghost
  // (also keeps it prefixed so a host page's bare .ghost rule can't touch it).
  const restoreBtn = el("button", "btn aiguard-ghost", "Restore PII");
  maskBtn.disabled = true;
  restoreBtn.disabled = true;
  const status = el("span", "status", "");
  bar.appendChild(logo);
  bar.appendChild(maskBtn);
  bar.appendChild(restoreBtn);
  bar.appendChild(status);
  document.documentElement.appendChild(bar);

  function setStatus(text, kind) {
    status.textContent = text || "";
    status.className = PREFIX + "status" + (kind ? " " + PREFIX + kind : "");
  }

  function setBackendReady(ready) {
    backendReady = Boolean(ready);
    maskBtn.disabled = !backendReady;
    restoreBtn.disabled = !backendReady || !sessionAvailable;
    document.querySelectorAll("." + PREFIX + "msg-btn").forEach((button) => {
      button.disabled = !backendReady || !sessionAvailable;
    });
  }

  function resetHealthRetry() {
    healthRetryAttempts = 0;
    if (healthRetryTimer !== null) {
      clearTimeout(healthRetryTimer);
      healthRetryTimer = null;
    }
  }

  function scheduleHealthRetry() {
    if (healthRetryTimer !== null) return;
    const exponent = Math.min(healthRetryAttempts, 7);
    const delay = Math.min(250 * 2 ** exponent, MAX_HEALTH_RETRY_DELAY_MS);
    healthRetryAttempts = Math.min(healthRetryAttempts + 1, 7);
    healthRetryTimer = setTimeout(() => {
      healthRetryTimer = null;
      void checkHealth();
    }, delay);
  }

  async function checkHealth() {
    const response = await send({ type: "health" });
    const ready =
      response &&
      response.ok &&
      response.data &&
      response.data.status === "ok" &&
      response.data.contract_version === 2 &&
      response.data.capabilities &&
      response.data.capabilities.api_key_required === false;
    setBackendReady(ready);
    if (ready) {
      resetHealthRetry();
    } else {
      setStatus("backend ยังไม่พร้อมใช้งาน", "err");
      scheduleHealthRetry();
    }
  }

  // ---- overlay for restored text / prominent warnings --------------------
  //
  // EXT-4: the restored text is real PII, and anything placed in the host
  // page's DOM is readable by every script that page runs (session replay,
  // analytics). The overlay therefore lives inside a CLOSED shadow root: the
  // page tree only ever contains an empty host element — host.shadowRoot is
  // null to the page, and no traversal reaches the text. The page could still
  // *remove* the host node (that only hides the PII), and our content script's
  // isolated world means the page cannot pre-patch attachShadow to steal the
  // root. Styles must ride inside the shadow too (page-injected content.css
  // does not cross the boundary), so the overlay's CSS lives in the constant
  // below rather than content.css.
  const OVERLAY_CSS = `
:host { all: initial; }
.aiguard-overlay-back {
  --ag-surface-container: #efedf1;
  --ag-surface-container-high: #e9e7ec;
  --ag-on-surface: #1b1b1f;
  --ag-on-surface-variant: #45464f;
  --ag-primary: #0053db;
  --ag-error: #ba1a1a;
  --ag-scrim: #000000;
  /* MD3 elevation level3 -- the modal-dialog tier. */
  --ag-elevation-3: 0px 1px 3px 0px rgba(0, 0, 0, .3), 0px 4px 8px 3px rgba(0, 0, 0, .15);
  --ag-font: "Leelawadee UI", "Thonburi", "Noto Sans Thai", system-ui, sans-serif;
}
@media (prefers-color-scheme: dark) {
  .aiguard-overlay-back {
    --ag-surface-container: #1f1f23;
    --ag-surface-container-high: #292a2d;
    --ag-on-surface: #e4e2e6;
    --ag-on-surface-variant: #c5c6d0;
    --ag-primary: #b4c5ff;
    --ag-error: #ffb4ab;
  }
}
.aiguard-overlay-back {
  position: fixed; inset: 0; z-index: 2147483647;
  background: color-mix(in srgb, var(--ag-scrim) 32%, transparent);
  display: flex; align-items: center; justify-content: center; padding: 24px;
  animation: aiguard-fade 240ms ease;
}
.aiguard-overlay {
  position: relative; width: min(680px, 92vw); max-height: 80vh; overflow: auto;
  background: var(--ag-surface-container-high); color: var(--ag-on-surface);
  border-radius: 28px;
  box-shadow: var(--ag-elevation-3); padding: 24px; font-family: var(--ag-font);
  animation: aiguard-pop 240ms cubic-bezier(0.2, 0, 0, 1);
}
.aiguard-overlay.aiguard-overlay-warn { border: 2px solid var(--ag-error); }
.aiguard-overlay.aiguard-overlay-warn .aiguard-overlay-title { color: var(--ag-error); }
.aiguard-overlay.aiguard-overlay-warn .aiguard-overlay-body {
  border: 1px solid var(--ag-error); font-weight: 600;
}
@keyframes aiguard-fade { from { opacity: 0; } to { opacity: 1; } }
@keyframes aiguard-pop { from { opacity: 0; transform: scale(0.98); } to { opacity: 1; transform: none; } }
@media (prefers-reduced-motion: reduce) {
  .aiguard-overlay-back, .aiguard-overlay { animation: none; }
}
.aiguard-overlay-close {
  position: absolute; isolation: isolate; top: 8px; right: 10px; width: 28px; height: 28px;
  display: flex; align-items: center; justify-content: center; border: none;
  background: transparent; font-size: 20px; line-height: 1; color: var(--ag-on-surface-variant);
  cursor: pointer; border-radius: 9999px;
  --ag-state-color: var(--ag-on-surface-variant);
}
.aiguard-overlay-close::before {
  content: "";
  position: absolute; inset: 0; border-radius: inherit;
  background: var(--ag-state-color); opacity: 0;
  transition: opacity 100ms cubic-bezier(0.2, 0, 0, 1);
  pointer-events: none; z-index: -1;
}
.aiguard-overlay-close:hover::before { opacity: .08; }
.aiguard-overlay-close:focus-visible::before { opacity: .12; }
.aiguard-overlay-close:active::before { opacity: .12; }
.aiguard-overlay-close:hover { color: var(--ag-on-surface); }
.aiguard-overlay-close:focus-visible { outline: 2px solid var(--ag-primary); outline-offset: 2px; }
.aiguard-overlay-title {
  font-size: 1rem; line-height: 1.5rem; font-weight: 500; letter-spacing: 0.009375rem; /* title-medium */
  margin-bottom: 12px; padding-right: 32px;
}
.aiguard-overlay-body {
  margin: 0; white-space: pre-wrap; word-break: break-word;
  font-size: 0.875rem; line-height: 1.25rem; letter-spacing: 0.015625rem; /* body-medium */
  background: var(--ag-surface-container);
  border-radius: 12px; padding: 12px 14px; color: var(--ag-on-surface);
}
.aiguard-overlay-meta {
  margin-top: 10px;
  font-size: 0.75rem; line-height: 1rem; letter-spacing: 0.025rem; /* body-small */
  color: var(--ag-on-surface-variant);
}
`;

  function showOverlay(title, bodyText, meta, kind) {
    const host = el("div", "overlay-host");
    const shadow = host.attachShadow({ mode: "closed" });
    const style = document.createElement("style");
    style.textContent = OVERLAY_CSS;
    const back = el("div", "overlay-back");
    const card = el("div", "overlay" + (kind ? " " + PREFIX + "overlay-" + kind : ""));
    const close = el("button", "overlay-close", "×"); // multiplication sign
    close.setAttribute("aria-label", "Close");
    card.appendChild(close);
    card.appendChild(el("div", "overlay-title", title));
    card.appendChild(el("pre", "overlay-body", bodyText));
    if (meta) card.appendChild(el("div", "overlay-meta", meta));
    back.appendChild(card);
    shadow.appendChild(style);
    shadow.appendChild(back);
    document.documentElement.appendChild(host);

    function dismiss() {
      host.remove();
      document.removeEventListener("keydown", onKey);
    }
    function onKey(e) {
      if (e.key === "Escape") dismiss();
    }
    close.addEventListener("click", dismiss);
    back.addEventListener("click", (e) => {
      if (e.target === back) dismiss();
    });
    document.addEventListener("keydown", onKey);
  }

  // ---- Mask -------------------------------------------------------------
  // EXT-3: a failed Mask means the RAW text is still in the composer and the
  // site's own Send button is one keystroke away. A corner status is not
  // enough — raise the full-screen overlay (its backdrop also blocks the page
  // until the user consciously dismisses it).
  function maskFailed(reason) {
    setStatus("ยังไม่ได้ปกปิด", "err");
    showOverlay(
      "ยังไม่ได้ปกปิด",
      "ข้อความจริงยังอยู่ในช่องพิมพ์ อย่าเพิ่งกดส่ง\n" + reason,
      "ปิดหน้าต่างนี้แล้วลองกด Mask PII อีกครั้ง",
      "warn"
    );
  }

  async function waitForComposerText(expected) {
    // Controlled editors can commit a valid native edit on their next update
    // cycle. Re-read the current composer for a short, bounded window; never
    // trust writeComposer's return value, and still fail closed if the masked
    // text does not become the visible editor state.
    for (let attempt = 0; attempt < 8; attempt += 1) {
      const check = SITE.composer();
      const now = check ? SITE.readComposer(check) : "";
      if (check && SITE.sameComposerText(check, now, expected)) return true;
      if (attempt < 7) {
        await new Promise((resolve) => setTimeout(resolve, 50));
      }
    }
    return false;
  }

  async function doMask() {
    if (!backendReady) {
      setStatus("backend ยังไม่พร้อมใช้งาน", "err");
      return;
    }
    const composer = SITE.composer();
    if (!composer) {
      setStatus("ไม่พบช่องพิมพ์", "err");
      return;
    }
    const text = SITE.readComposer(composer);
    if (!text || !text.trim()) {
      setStatus("พิมพ์ข้อความก่อน", "err");
      return;
    }
    setStatus("กำลังปกปิด...");
    maskBtn.disabled = true;
    const resp = await send({ type: "sanitize", text });
    maskBtn.disabled = !backendReady;
    if (!resp || !resp.ok) {
      if (
        resp &&
        (resp.error === "contract-invalid" || resp.error === "backend-unavailable")
      ) {
        setBackendReady(false);
      }
      sessionAvailable = false;
      setBackendReady(backendReady);
      maskFailed(backendError(resp));
      return;
    }
    try {
      resp.data = CONTRACT.validateNativeSanitize(resp.data);
    } catch {
      sessionAvailable = false;
      setBackendReady(false);
      maskFailed("ผลลัพธ์ไม่ผ่านการตรวจความปลอดภัย");
      return;
    }
    if (
      !resp.data ||
      typeof resp.data.sanitized_text !== "string" ||
      resp.data.sanitized_text.length === 0 ||
      !resp.data.safety ||
      resp.data.safety.status !== "pass" ||
      resp.data.safety.residual_count !== 0
    ) {
      maskFailed("ผลลัพธ์ไม่ผ่านการตรวจความปลอดภัย");
      return;
    }
    SITE.writeComposer(composer, resp.data.sanitized_text);
    // EXT-2: writeComposer's return value is not evidence — the host editor
    // may have swallowed the write (React re-render, replaced node). Success
    // is only what fresh reads of the composer actually contain.
    if (!(await waitForComposerText(resp.data.sanitized_text))) {
      sessionAvailable = false;
      setBackendReady(backendReady);
      maskFailed("เขียนข้อความที่ปกปิดแล้วลงช่องพิมพ์ไม่สำเร็จ");
      return;
    }
    sessionAvailable = true;
    setBackendReady(backendReady);
    setStatus("ปกปิด " + resp.data.replacement_count + " รายการ", "ok");
  }

  // ---- Restore ----------------------------------------------------------
  async function restoreText(text, sourceLabel) {
    if (!backendReady) {
      setStatus("backend ยังไม่พร้อมใช้งาน", "err");
      return;
    }
    if (!sessionAvailable) {
      setStatus("เซสชันหมดอายุ ปกปิดใหม่อีกครั้ง", "err");
      return;
    }
    if (!text || !text.trim()) {
      setStatus("ไม่มีข้อความให้คืนค่า", "err");
      return;
    }
    setStatus("กำลังคืนค่า...");
    const resp = await send({ type: "reidentify", text });
    if (!resp || !resp.ok) {
      sessionAvailable = false;
      setBackendReady(backendReady);
      setStatus(backendError(resp), "err");
      return;
    }
    let d;
    try {
      d = CONTRACT.validateReidentify(resp.data);
    } catch {
      sessionAvailable = false;
      setBackendReady(false);
      setStatus("ผลลัพธ์ไม่ผ่านการตรวจความปลอดภัย", "err");
      return;
    }
    if (!CONTRACT.restorationIsComplete(d)) {
      const warningCount = d.warnings.reduce(
        (sum, warning) => sum + warning.count,
        0
      );
      setStatus(
        "คืนค่าไม่ครบ เหลือ " +
          d.leftover_count +
          " รายการ" +
          (warningCount ? " และมีคำเตือน " + warningCount + " รายการ" : ""),
        "err"
      );
      return;
    }
    const meta = "คืนค่า " + d.replaced_count + " รายการ";
    showOverlay("คืนค่าแล้ว (" + sourceLabel + ")", d.restored_text, meta);
    setStatus("คืนค่าแล้ว", "ok");
  }

  // Read an assistant message's text, minus the Restore button we injected
  // into it (otherwise the button's "Restore PII" label leaks into the text
  // we send for re-identification).
  function messageText(node) {
    let t = node.innerText || node.textContent || "";
    const btn = node.querySelector(":scope > ." + PREFIX + "msg-btn");
    if (btn) {
      const bt = (btn.innerText || btn.textContent || "").trim();
      if (bt && t.trimEnd().endsWith(bt)) {
        t = t.trimEnd().slice(0, -bt.length);
      }
    }
    return t;
  }

  // Floating Restore: prefer a text selection, else the last AI reply.
  async function doRestoreFloating() {
    const sel = (window.getSelection && window.getSelection().toString()) || "";
    if (sel.trim()) return restoreText(sel, "ข้อความที่เลือก");
    const msgs = SITE.assistantMessages();
    if (msgs.length) {
      return restoreText(messageText(msgs[msgs.length - 1]), "คำตอบล่าสุด");
    }
    setStatus("เลือกข้อความคำตอบ AI ก่อน", "err");
  }

  maskBtn.addEventListener("click", doMask);
  restoreBtn.addEventListener("click", doRestoreFloating);

  // ---- per-message Restore buttons (best-effort) ------------------------
  // Re-checked on every mutation; if the host re-renders and drops our
  // button we add it back. If the assistant selector ever stops matching,
  // the floating Restore button above is the reliable fallback.
  function decorate() {
    const msgs = SITE.assistantMessages();
    for (const m of msgs) {
      if (m.querySelector(":scope > ." + PREFIX + "msg-btn")) continue;
      const b = el("button", "msg-btn", "คืนค่า");
      b.disabled = !backendReady || !sessionAvailable;
      b.addEventListener("click", (e) => {
        e.stopPropagation();
        restoreText(messageText(m), "คำตอบ");
      });
      m.appendChild(b);
    }
  }

  const obs = new MutationObserver(() => decorate());
  obs.observe(document.documentElement, { childList: true, subtree: true });
  decorate();
  if (chrome.runtime.onMessage && chrome.runtime.onMessage.addListener) {
    chrome.runtime.onMessage.addListener((message) => {
      if (
        message &&
        message.type === "aiguard-native-state" &&
        message.state === "session-expired" &&
        Object.keys(message).length === 2
      ) {
        sessionAvailable = false;
        setBackendReady(false);
        document
          .querySelectorAll("." + PREFIX + "overlay-host")
          .forEach((host) => host.remove());
        setStatus("เซสชันหมดอายุ ปกปิดใหม่อีกครั้ง", "err");
        resetHealthRetry();
        scheduleHealthRetry();
      }
    });
  }
  checkHealth();
})();
