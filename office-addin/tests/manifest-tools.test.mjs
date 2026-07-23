import { describe, expect, it } from "vitest";
import {
  UNIFIED_MANIFEST_SCHEMA_URL,
  UNIFIED_MANIFEST_SCHEMA_SHA256,
  assertSchemaIntegrity,
  requiredPackageEntries,
  validateUnifiedManifest,
  verifyPackageEntries,
} from "../scripts/unified-manifest-tools.mjs";

describe("unified manifest tooling", () => {
  it("uses the pinned official Microsoft schema endpoint and reports schema failures deterministically", () => {
    expect(UNIFIED_MANIFEST_SCHEMA_URL).toBe(
      "https://developer.microsoft.com/json-schemas/teams/v1.25/MicrosoftTeams.schema.json",
    );
    expect(UNIFIED_MANIFEST_SCHEMA_SHA256).toBe("24c1bbb38fc24ba19d536016fdfb6e8aced645ce9b3d0e19b4c0308ff47f5d96");
    const schema = {
      type: "object",
      required: ["validDomains"],
      properties: { validDomains: { type: "array", minItems: 1 } },
    };

    expect(validateUnifiedManifest({ validDomains: ["localhost:3000"] }, schema)).toEqual({ valid: true, errors: [] });
    expect(validateUnifiedManifest({}, schema)).toMatchObject({ valid: false, errors: [expect.stringContaining("required")] });
  });

  it("rejects a schema body that does not match the reviewed official checksum", () => {
    expect(() => assertSchemaIntegrity("unreviewed schema")).toThrow("schema checksum changed");
  });

  it("requires the manifest and both declared icon files in the app package", () => {
    const manifest = { icons: { outline: "assets/outline.png", color: "assets/color.png" } };
    expect(requiredPackageEntries(manifest)).toEqual(["manifest.json", "assets/outline.png", "assets/color.png"]);
    expect(verifyPackageEntries(new Map([["manifest.json", Buffer.from("{}")] ]), manifest)).toEqual([
      "package is missing required entry: assets/outline.png",
      "package is missing required entry: assets/color.png",
    ]);
    expect(
      verifyPackageEntries(
        new Map([
          ["manifest.json", Buffer.from("{}")],
          ["assets/outline.png", Buffer.from("outline")],
          ["assets/color.png", Buffer.from("color")],
        ]),
        manifest,
      ),
    ).toEqual([]);
  });
});
