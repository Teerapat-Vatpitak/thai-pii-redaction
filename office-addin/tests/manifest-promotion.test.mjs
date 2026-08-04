import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const root = resolve(import.meta.dirname, "..");
const manifest = JSON.parse(readFileSync(resolve(root, "manifest.json"), "utf8"));
const packageJson = JSON.parse(readFileSync(resolve(root, "package.json"), "utf8"));
const promotedScopes = ["document"];

describe("promoted unified Office manifest", () => {
  it("exposes Word only until Excel and PowerPoint real-host gates pass", () => {
    expect(manifest.extensions).toHaveLength(1);
    const extension = manifest.extensions[0];
    expect(extension.requirements.scopes).toEqual(promotedScopes);
    expect(extension.ribbons[0].requirements.scopes).toEqual(promotedScopes);
    expect(manifest.authorization.permissions.resourceSpecific).toEqual([
      { name: "Document.ReadWrite.User", type: "Delegated" },
    ]);
  });

  it("does not expose unverified hosts through unified sideload commands", () => {
    expect(packageJson.scripts["start:word"]).toContain("manifest.json desktop --app word");
    expect(packageJson.scripts["start:excel"]).toBeUndefined();
    expect(packageJson.scripts["start:powerpoint"]).toBeUndefined();
    expect(packageJson.scripts["start:excel:local"]).toContain("manifest.dev.excel.xml desktop --app excel");
    expect(packageJson.scripts["start:powerpoint:local"]).toContain("manifest.dev.powerpoint.xml desktop --app powerpoint");
  });
});
