import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const root = resolve(import.meta.dirname, "..");
const manifest = JSON.parse(readFileSync(resolve(root, "manifest.json"), "utf8"));
const packageJson = JSON.parse(readFileSync(resolve(root, "package.json"), "utf8"));
const promotedScopes = ["document", "workbook", "presentation"];

describe("promoted unified Office manifest", () => {
  it("exposes exactly Word, Excel, and PowerPoint with the document write permission", () => {
    expect(manifest.extensions).toHaveLength(1);
    const extension = manifest.extensions[0];
    expect(extension.requirements.scopes).toEqual(promotedScopes);
    expect(extension.ribbons[0].requirements.scopes).toEqual(promotedScopes);
    expect(manifest.authorization.permissions.resourceSpecific).toEqual([
      { name: "Document.ReadWrite.User", type: "Delegated" },
    ]);
  });

  it("provides repeatable unified sideload commands for every promoted host", () => {
    expect(packageJson.scripts["start:word"]).toContain("manifest.json desktop --app word");
    expect(packageJson.scripts["start:excel"]).toContain("manifest.json desktop --app excel");
    expect(packageJson.scripts["start:powerpoint"]).toContain("manifest.json desktop --app powerpoint");
  });
});
