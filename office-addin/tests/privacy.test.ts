import { readFileSync, readdirSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

function sourceFiles(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = resolve(directory, entry.name);
    if (entry.isDirectory()) return sourceFiles(path);
    return entry.isFile() && path.endsWith(".ts") ? [path] : [];
  });
}

describe("privacy invariants", () => {
  it("does not persist task state or log provider/selection content", () => {
    const root = resolve(import.meta.dirname, "../src");
    const source = sourceFiles(root)
      .map((file) => readFileSync(file, "utf8"))
      .join("\n");
    expect(source).not.toMatch(/localStorage|sessionStorage/);
    expect(source).not.toMatch(/console\.(log|debug|info|warn|error)/);
  });
});
