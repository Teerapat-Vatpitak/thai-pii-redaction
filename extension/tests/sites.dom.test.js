import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { beforeEach, describe, expect, test } from "vitest";
import sites from "../sites.js";

const FIXTURES = join(dirname(fileURLToPath(import.meta.url)), "fixtures");

function load(name) {
  document.body.innerHTML = readFileSync(join(FIXTURES, `${name}.html`), "utf8");
}

const SITES = ["chatgpt", "claude", "gemini", "grok", "perplexity", "zai"];

describe.each(SITES)("%s fixture", (name) => {
  beforeEach(() => load(name));

  test("composer() finds the input", () => {
    const el = sites[name].composer();
    expect(el).not.toBeNull();
    const editable =
      el.tagName === "TEXTAREA" ||
      el.tagName === "INPUT" ||
      el.getAttribute("contenteditable") === "true";
    expect(editable).toBe(true);
  });

  test("assistantMessages() returns at least one reply node", () => {
    const nodes = sites[name].assistantMessages();
    expect(Array.isArray(nodes)).toBe(true);
    expect(nodes.length).toBeGreaterThan(0);
    expect(nodes[0].textContent).toContain("คำตอบ");
  });

  test("writeComposer/readComposer round-trip", () => {
    const el = sites[name].composer();
    const ok = sites[name].writeComposer(el, "ข้อความทดสอบ [ชื่อ_1]");
    expect(ok).toBe(true);
    expect(sites[name].readComposer(el)).toBe("ข้อความทดสอบ [ชื่อ_1]");
  });
});

describe("cross-fixture safety", () => {
  test("chatgpt selectors do not fire on the claude fixture", () => {
    load("claude");
    expect(sites.chatgpt.assistantMessages()).toEqual([]);
  });
  test("generic composer works on every fixture (drift safety net)", () => {
    for (const name of SITES) {
      load(name);
      expect(sites.generic.composer()).not.toBeNull();
    }
  });
  test("grok prefers the rich editor over its helper textarea", () => {
    load("grok");
    const composer = sites.grok.composer();
    expect(composer.tagName).toBe("DIV");
    expect(composer.getAttribute("contenteditable")).toBe("true");
  });
  test("perplexity writes through Lexical beforeinput", () => {
    load("perplexity");
    const composer = sites.perplexity.composer();
    composer.addEventListener("beforeinput", (event) => {
      event.preventDefault();
      composer.textContent = event.data;
    });

    expect(sites.perplexity.writeComposer(composer, "ข้อความ [ชื่อ_1]")).toBe(true);
    expect(sites.perplexity.readComposer(composer)).toBe("ข้อความ [ชื่อ_1]");
  });
});
