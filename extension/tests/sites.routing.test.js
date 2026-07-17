// sites.js selects a per-host config at load time; selectFor(hostname) is the
// extracted, testable form of that routing. jsdom quirks this suite relies on:
// getBoundingClientRect() is all-zero (visible() -> false, pickVisible falls
// back to list[0]) and document.execCommand is undefined (writeComposer takes
// its fallback paths). Both fallbacks are real code paths worth pinning.
import { describe, expect, test } from "vitest";
import sites from "../sites.js";

describe("hostname routing (selectFor)", () => {
  const cases = [
    ["claude.ai", "claude"],
    ["gemini.google.com", "gemini"],
    ["grok.com", "grok"],
    ["www.perplexity.ai", "perplexity"],
    ["chat.z.ai", "zai"],
    ["chatglm.cn", "zai"],
    ["www.bigmodel.cn", "zai"],
    ["chatgpt.com", "chatgpt"],
    ["chat.openai.com", "chatgpt"],
    ["example.com", "generic"],
    ["localhost", "generic"],
  ];
  for (const [hostname, expected] of cases) {
    test(`${hostname} -> ${expected}`, () => {
      expect(sites.selectFor(hostname).name).toBe(expected);
    });
  }
});

describe("empty-DOM behavior (never throws)", () => {
  test("site composer on an empty page returns null", () => {
    document.body.innerHTML = "";
    expect(sites.chatgpt.composer()).toBeNull();
  });
  test("generic assistantMessages is always an empty array", () => {
    document.body.innerHTML = "";
    expect(sites.generic.assistantMessages()).toEqual([]);
  });
});
