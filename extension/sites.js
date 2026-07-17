// Per-host DOM configuration.
//
// ALL host-page fragility lives in this file. Each supported AI chat site gets
// a config object with composer() (the prompt input) and assistantMessages()
// (reply nodes, for the per-message Restore button). If a site changes its UI,
// update the selectors here only -- the rest of the extension is host-agnostic.
//
// Sites differ in composer type: ChatGPT/Claude/Gemini use a contenteditable
// rich editor; Grok/Perplexity/GLM(Z.ai) use a plain <textarea>. read/write
// below handle both. Every site also falls back to genericComposer() -- a
// visible-input picker -- so Mask keeps working even if a site-specific
// selector drifts. assistantMessages() is best-effort; the floating Restore
// button works on any selected text, so it is the universal fallback.
//
// Loaded before content.js in the same content-script context, so the global
// it sets (window.AIGUARD_SITES) is visible to content.js.

window.AIGUARD_SITES = (function () {
  function visible(el) {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  }

  function isTextField(el) {
    return el && (el.tagName === "TEXTAREA" || el.tagName === "INPUT");
  }

  // Last visible node wins -- composers sit at the bottom of the page; if none
  // is visible fall back to the first match so Mask can still try.
  function pickVisible(nodes) {
    const list = Array.prototype.slice.call(nodes);
    const vis = list.filter(visible);
    return vis.length ? vis[vis.length - 1] : list[0] || null;
  }

  // Host-agnostic composer finder: prefer a visible rich-text editor, else a
  // visible textarea. The safety net behind every site config.
  function genericComposer() {
    return (
      pickVisible(document.querySelectorAll("div[contenteditable='true'], [role='textbox'][contenteditable='true']")) ||
      pickVisible(document.querySelectorAll("textarea")) ||
      document.querySelector("textarea") ||
      null
    );
  }

  function readComposer(el) {
    if (isTextField(el)) return (el.value || "").trim();
    return (el.innerText || el.textContent || "").trim();
  }

  // Write text into the composer so React / ProseMirror / Quill register it.
  // For <textarea>/<input>: execCommand insertText first, else the native
  // value setter + input event (bypasses React's cached value). For
  // contenteditable: execCommand insertText, else textContent + input event.
  function writeComposer(el, text) {
    el.focus();
    if (isTextField(el)) {
      try {
        if (el.select) el.select();
        if (document.execCommand("insertText", false, text)) return true;
      } catch (e) {
        /* fall through */
      }
      try {
        const proto =
          el.tagName === "TEXTAREA"
            ? window.HTMLTextAreaElement.prototype
            : window.HTMLInputElement.prototype;
        const setter = Object.getOwnPropertyDescriptor(proto, "value").set;
        setter.call(el, text);
      } catch (e) {
        el.value = text;
      }
      el.dispatchEvent(new Event("input", { bubbles: true }));
      return true;
    }
    try {
      document.execCommand("selectAll", false, null);
      if (document.execCommand("insertText", false, text)) return true;
    } catch (e) {
      /* fall through to fallback */
    }
    el.textContent = text;
    el.dispatchEvent(
      new InputEvent("input", { bubbles: true, data: text, inputType: "insertText" })
    );
    return true;
  }

  const chatgpt = {
    name: "chatgpt",
    composer: function () {
      return (
        document.querySelector("#prompt-textarea") ||
        document.querySelector("div.ProseMirror[contenteditable='true']") ||
        document.querySelector("textarea") ||
        genericComposer()
      );
    },
    assistantMessages: function () {
      return Array.from(
        document.querySelectorAll("[data-message-author-role='assistant']")
      );
    },
    readComposer: readComposer,
    writeComposer: writeComposer,
  };

  const claude = {
    name: "claude",
    composer: function () {
      const list = Array.from(
        document.querySelectorAll(
          "div.ProseMirror[contenteditable='true'], div[contenteditable='true']"
        )
      );
      const vis = list.filter(visible);
      return vis.length ? vis[vis.length - 1] : list[0] || genericComposer();
    },
    // Verified live (2026-06-27): Claude renders each reply in
    // div.font-claude-response. Older builds used .font-claude-message;
    // both are kept, and [data-is-streaming] (the assistant turn wrapper)
    // is a stable last-resort fallback.
    assistantMessages: function () {
      let nodes = Array.from(
        document.querySelectorAll("div.font-claude-response, div.font-claude-message")
      );
      if (!nodes.length) {
        nodes = Array.from(document.querySelectorAll("[data-is-streaming]"));
      }
      return nodes;
    },
    readComposer: readComposer,
    writeComposer: writeComposer,
  };

  // Gemini (gemini.google.com): Quill contenteditable inside <rich-textarea>;
  // replies live in <message-content class="model-response-text">.
  const gemini = {
    name: "gemini",
    composer: function () {
      return (
        document.querySelector("rich-textarea div.ql-editor[contenteditable='true']") ||
        document.querySelector("div.ql-editor[contenteditable='true']") ||
        genericComposer()
      );
    },
    assistantMessages: function () {
      return Array.from(
        document.querySelectorAll("message-content.model-response-text, message-content")
      );
    },
    readComposer: readComposer,
    writeComposer: writeComposer,
  };

  // Grok (grok.com): a plain <textarea> composer. Reply markup is less stable,
  // so per-message buttons are best-effort; selection Restore covers the rest.
  const grok = {
    name: "grok",
    composer: function () {
      return (
        pickVisible(document.querySelectorAll("textarea")) ||
        document.querySelector("textarea") ||
        genericComposer()
      );
    },
    assistantMessages: function () {
      return Array.from(
        document.querySelectorAll(
          ".message-bubble, [class*='response-content'], [class*='message-bubble']"
        )
      );
    },
    readComposer: readComposer,
    writeComposer: writeComposer,
  };

  // Perplexity (perplexity.ai): the ask box is a <textarea> (older) or a
  // contenteditable #ask-input (newer); answers render as .prose blocks.
  const perplexity = {
    name: "perplexity",
    composer: function () {
      return (
        document.querySelector("textarea[placeholder]") ||
        document.querySelector("#ask-input[contenteditable='true']") ||
        pickVisible(document.querySelectorAll("textarea, div[contenteditable='true']")) ||
        genericComposer()
      );
    },
    assistantMessages: function () {
      return Array.from(document.querySelectorAll("div.prose, [class*='prose']"));
    },
    readComposer: readComposer,
    writeComposer: writeComposer,
  };

  // GLM / Z.ai (chat.z.ai, chatglm.cn, bigmodel.cn): <textarea> composer;
  // reply containers vary, so lean on generic reply selectors + selection.
  const zai = {
    name: "zai",
    composer: function () {
      return (
        pickVisible(document.querySelectorAll("textarea, div[contenteditable='true']")) ||
        document.querySelector("textarea") ||
        genericComposer()
      );
    },
    assistantMessages: function () {
      return Array.from(
        document.querySelectorAll(
          "[class*='assistant'], [class*='response'], .markdown-body, .markdown"
        )
      );
    },
    readComposer: readComposer,
    writeComposer: writeComposer,
  };

  // Any other matched host: the in-page bar still works via the generic
  // composer finder; per-message buttons are skipped (selection Restore works).
  const generic = {
    name: "generic",
    composer: genericComposer,
    assistantMessages: function () {
      return [];
    },
    readComposer: readComposer,
    writeComposer: writeComposer,
  };

  function selectFor(hostname) {
    function has(s) {
      return hostname.indexOf(s) !== -1;
    }
    if (has("claude.ai")) return claude;
    if (has("gemini.google.com")) return gemini;
    if (has("grok.com")) return grok;
    if (has("perplexity.ai")) return perplexity;
    if (has("z.ai") || has("chatglm.cn") || has("bigmodel.cn")) return zai;
    if (has("chatgpt.com") || has("openai.com")) return chatgpt;
    return generic;
  }

  // Test-only export shim (Node/vitest). Dead branch in the browser -- Chrome
  // content scripts have no `module`, so this changes nothing at runtime.
  if (typeof module !== "undefined" && module.exports) {
    module.exports = {
      chatgpt: chatgpt,
      claude: claude,
      gemini: gemini,
      grok: grok,
      perplexity: perplexity,
      zai: zai,
      generic: generic,
      selectFor: selectFor,
      helpers: {
        visible: visible,
        isTextField: isTextField,
        pickVisible: pickVisible,
        genericComposer: genericComposer,
        readComposer: readComposer,
        writeComposer: writeComposer,
      },
    };
  }

  return selectFor(location.hostname);
})();
