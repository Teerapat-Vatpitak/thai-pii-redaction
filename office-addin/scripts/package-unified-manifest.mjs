import { createRequire } from "node:module";
import { existsSync, mkdirSync, readFileSync, rmSync } from "node:fs";
import { resolve } from "node:path";
import AdmZip from "adm-zip";
import { verifyPackageEntries } from "./unified-manifest-tools.mjs";

const require = createRequire(import.meta.url);
const { exportManifest } = require("office-addin-manifest/lib/commands");
const root = resolve(import.meta.dirname, "..");
const manifestPath = resolve(root, "manifest.json");
const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
// Vite empties dist/ during npm run build, so keep the independently generated
// app package in the repository's ignored runtime-output directory.
const outputDirectory = resolve(root, "..", "out", "office-addin");
const outputPath = resolve(outputDirectory, `aiguard-office-addin-${manifest.version}.zip`);

mkdirSync(outputDirectory, { recursive: true });
rmSync(outputPath, { force: true });
await exportManifest({ manifest: manifestPath, output: outputPath });

if (!existsSync(outputPath)) {
  console.error("manifest package was not created");
  process.exit(1);
}

const zip = new AdmZip(outputPath);
const entries = new Map(zip.getEntries().map((entry) => [entry.entryName, entry.getData()]));
const errors = verifyPackageEntries(entries, manifest);
for (const entry of ["manifest.json", manifest.icons?.outline, manifest.icons?.color]) {
  if (typeof entry !== "string" || !entries.has(entry)) continue;
  const source = readFileSync(resolve(root, entry));
  if (!entries.get(entry)?.equals(source)) errors.push(`package entry does not match source: ${entry}`);
}

if (errors.length) {
  for (const error of errors) console.error(`manifest package: ${error}`);
  process.exit(1);
}

console.log(`unified manifest package verified: ${outputPath}`);
