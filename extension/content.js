// AI Guard content script.
//
// Injects a floating control bar (Mask PII / Restore PII) on ChatGPT and
// Claude, plus a best-effort "Restore PII" button on each AI message. All
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
    if (resp && resp.status === 404) return "Session expired - Mask again";
    return "Backend offline - run run.ps1 / run.sh";
  }

  // ---- floating control bar ---------------------------------------------
  const bar = el("div", "bar");
  const logo = el("img", "logo");
  logo.src = chrome.runtime.getURL("icons/icon32.png");
  logo.alt = "AI Guard";
  const maskBtn = el("button", "btn", "Mask PII");
  const restoreBtn = el("button", "btn ghost", "Restore PII");
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

  // ---- overlay for restored text ----------------------------------------
  function showOverlay(title, bodyText, meta) {
    const back = el("div", "overlay-back");
    const card = el("div", "overlay");
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
  async function doMask() {
    const composer = SITE.composer();
    if (!composer) {
      setStatus("Composer not found", "err");
      return;
    }
    const text = SITE.readComposer(composer);
    if (!text) {
      setStatus("Type something first", "err");
      return;
    }
    setStatus("Masking...");
    maskBtn.disabled = true;
    const resp = await send({ type: "sanitize", text });
    maskBtn.disabled = false;
    if (!resp || !resp.ok) {
      setStatus(backendError(resp), "err");
      return;
    }
    SITE.writeComposer(composer, resp.data.sanitized_text);
    const n = (resp.data.entities || []).length;
    setStatus(n + (n === 1 ? " item masked" : " items masked"), "ok");
  }

  // ---- Restore ----------------------------------------------------------
  async function restoreText(text, sourceLabel) {
    if (!text || !text.trim()) {
      setStatus("Nothing to restore", "err");
      return;
    }
    setStatus("Restoring...");
    const resp = await send({ type: "reidentify", text });
    if (!resp || !resp.ok) {
      setStatus(resp && resp.error === "no-session" ? "Mask something first" : backendError(resp), "err");
      return;
    }
    const d = resp.data;
    const leftover = (d.leftover_tokens || []).length;
    const meta =
      d.replaced_count + " token(s) restored" +
      (leftover ? " - " + leftover + " not matched" : "");
    showOverlay("Restored (" + sourceLabel + ")", d.restored_text, meta);
    setStatus("Restored", "ok");
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
    if (sel.trim()) return restoreText(sel, "selection");
    const msgs = SITE.assistantMessages();
    if (msgs.length) {
      return restoreText(messageText(msgs[msgs.length - 1]), "last reply");
    }
    setStatus("Select the AI reply text first", "err");
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
      const b = el("button", "msg-btn", "Restore PII");
      b.addEventListener("click", (e) => {
        e.stopPropagation();
        restoreText(messageText(m), "reply");
      });
      m.appendChild(b);
    }
  }

  const obs = new MutationObserver(() => decorate());
  obs.observe(document.documentElement, { childList: true, subtree: true });
  decorate();
})();
