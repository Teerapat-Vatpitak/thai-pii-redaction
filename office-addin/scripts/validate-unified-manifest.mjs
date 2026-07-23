import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import {
  UNIFIED_MANIFEST_SCHEMA_URL,
  assertSchemaIntegrity,
  validateUnifiedManifest,
} from "./unified-manifest-tools.mjs";

const root = resolve(import.meta.dirname, "..");
const manifest = JSON.parse(readFileSync(resolve(root, "manifest.json"), "utf8"));

let schema;
try {
  const response = await fetch(UNIFIED_MANIFEST_SCHEMA_URL);
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const source = await response.text();
  assertSchemaIntegrity(source);
  schema = JSON.parse(source);
} catch (error) {
  console.error(`Unable to retrieve the official Microsoft 365 unified-manifest schema: ${error instanceof Error ? error.message : "unknown error"}`);
  process.exit(1);
}

const result = validateUnifiedManifest(manifest, schema);
if (!result.valid) {
  for (const error of result.errors) console.error(`manifest: ${error}`);
  process.exit(1);
}

console.log(`unified manifest validates against the checksum-pinned official schema at ${UNIFIED_MANIFEST_SCHEMA_URL}`);
