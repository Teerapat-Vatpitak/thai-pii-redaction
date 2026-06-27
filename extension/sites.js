// Per-host DOM configuration.
//
// ALL host-page fragility lives in this file. ChatGPT and Claude both use a
// ProseMirror contenteditable composer. If either site changes its UI, update
// the selectors here only -- the rest of the extension is host-agnostic.
//
// Loaded before content.js in the same content-script context, so the global
// it sets (window.AIGUARD_SITES) is visible to content.js.

window.AIGUARD_SITES = (function () {
  function visible(el) {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  }

  function readComposer(el) {
    return (el.innerText || el.textContent || "").trim();
  }

  // Write text into a contenteditable composer in a way ProseMirror/React
  // will register. execCommand insertText is the most reliable path; fall
  // back to setting textContent and firing an input event.
  function writeComposer(el, text) {
    el.focus();
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
        document.querySelector("textarea")
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
      return vis.length ? vis[vis.length - 1] : list[0] || null;
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

  return location.hostname.indexOf("claude.ai") !== -1 ? claude : chatgpt;
})();
