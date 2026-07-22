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

  const PREFIX = "aiguard-";

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
            resolve({ ok: false, status: 0, error: chrome.runtime.lastError.message });
          } else {
            resolve(resp);
          }
        });
      } catch (e) {
        resolve({ ok: false, status: 0, error: String(e) });
      }
    });
  }

  function backendError(resp) {
    if (resp && resp.status === 404) return "เซสชันหมดอายุ ปกปิดใหม่อีกครั้ง";
    return "backend ยังไม่ทำงาน เปิดแอป AI Guard";
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

  // ---- overlay for restored text / prominent warnings --------------------
  function showOverlay(title, bodyText, meta, kind) {
    const back = el("div", "overlay-back");
    const card = el("div", "overlay" + (kind ? " " + PREFIX + "overlay-" + kind : ""));
    const close = el("button", "overlay-close", "×"); // multiplication sign
    close.setAttribute("aria-label", "Close");
    card.appendChild(close);
    card.appendChild(el("div", "overlay-title", title));
    card.appendChild(el("pre", "overlay-body", bodyText));
    if (meta) card.appendChild(el("div", "overlay-meta", meta));
    back.appendChild(card);
    document.documentElement.appendChild(back);

    function dismiss() {
      back.remove();
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

  // Whitespace-insensitive comparison: contenteditable editors re-render text
  // through their own document model (innerText adds/collapses newlines), so
  // an exact string match would fail on a perfectly good write.
  function sameText(a, b) {
    return (a || "").replace(/\s+/g, " ").trim() === (b || "").replace(/\s+/g, " ").trim();
  }

  async function doMask() {
    const composer = SITE.composer();
    if (!composer) {
      setStatus("ไม่พบช่องพิมพ์", "err");
      return;
    }
    const text = SITE.readComposer(composer);
    if (!text) {
      setStatus("พิมพ์ข้อความก่อน", "err");
      return;
    }
    setStatus("กำลังปกปิด...");
    maskBtn.disabled = true;
    const resp = await send({ type: "sanitize", text });
    maskBtn.disabled = false;
    if (!resp || !resp.ok) {
      maskFailed(backendError(resp));
      return;
    }
    SITE.writeComposer(composer, resp.data.sanitized_text);
    // EXT-2: writeComposer's return value is not evidence — the host editor
    // may have swallowed the write (React re-render, replaced node). Success
    // is only what a fresh read of the composer actually contains.
    const check = SITE.composer() || composer;
    const now = check ? SITE.readComposer(check) : "";
    if (!sameText(now, resp.data.sanitized_text)) {
      maskFailed("เขียนข้อความที่ปกปิดแล้วลงช่องพิมพ์ไม่สำเร็จ");
      return;
    }
    const n = (resp.data.entities || []).length;
    setStatus("ปกปิด " + n + " รายการ", "ok");
  }

  // ---- Restore ----------------------------------------------------------
  async function restoreText(text, sourceLabel) {
    if (!text || !text.trim()) {
      setStatus("ไม่มีข้อความให้คืนค่า", "err");
      return;
    }
    setStatus("กำลังคืนค่า...");
    const resp = await send({ type: "reidentify", text });
    if (!resp || !resp.ok) {
      setStatus(resp && resp.error === "no-session" ? "ปกปิดข้อความก่อน" : backendError(resp), "err");
      return;
    }
    const d = resp.data;
    const leftover = (d.leftover_tokens || []).length;
    const meta =
      "คืนค่า " + d.replaced_count + " รายการ" +
      (leftover ? " เหลือ " + leftover + " รายการ" : "");
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
})();
