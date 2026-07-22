import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../src/theme.js", () => ({
  getThemePref: vi.fn(() => "system"),
  setThemePref: vi.fn(),
}));

import { renderSettings } from "../src/screen-settings.js";

beforeEach(() => {
  document.body.innerHTML = '<div id="root"></div>';
  localStorage.clear();
});

describe("desktop extension settings copy", () => {
  it("lists the declared sites without claiming store availability", () => {
    const root = document.getElementById("root");
    renderSettings(root);
    const text = root.textContent;

    for (const site of ["ChatGPT", "Codex", "Gemini", "Grok", "Perplexity", "GLM/Z.ai"]) {
      expect(text).toContain(site);
    }
    expect(text).not.toContain("Chrome Web Store");
    expect(text).toContain("unpacked");
  });
});
