import Ajv from "ajv-draft-04";
import { createHash } from "node:crypto";

export const UNIFIED_MANIFEST_SCHEMA_URL =
  "https://developer.microsoft.com/json-schemas/teams/v1.25/MicrosoftTeams.schema.json";
export const UNIFIED_MANIFEST_SCHEMA_SHA256 = "24c1bbb38fc24ba19d536016fdfb6e8aced645ce9b3d0e19b4c0308ff47f5d96";

export function assertSchemaIntegrity(source) {
  const checksum = createHash("sha256").update(source).digest("hex");
  if (checksum !== UNIFIED_MANIFEST_SCHEMA_SHA256) {
    throw new Error(`schema checksum changed (expected ${UNIFIED_MANIFEST_SCHEMA_SHA256}, received ${checksum})`);
  }
}

export function validateUnifiedManifest(manifest, schema) {
  const ajv = new Ajv({ allErrors: true, strict: false, validateFormats: false });
  const validate = ajv.compile(schema);
  const valid = validate(manifest);
  return {
    valid,
    errors: valid ? [] : (validate.errors ?? []).map((error) => `${error.instancePath || "/"} ${error.message ?? "is invalid"}`),
  };
}

export function requiredPackageEntries(manifest) {
  return ["manifest.json", manifest.icons?.outline, manifest.icons?.color].filter(
    (entry) => typeof entry === "string" && entry.length > 0,
  );
}

export function verifyPackageEntries(entries, manifest) {
  const required = requiredPackageEntries(manifest);
  const missing = required.filter((entry) => !entries.has(entry));
  return missing.map((entry) => `package is missing required entry: ${entry}`);
}
