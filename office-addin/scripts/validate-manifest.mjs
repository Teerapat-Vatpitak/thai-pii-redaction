import { readFileSync, existsSync } from "node:fs";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const manifest = JSON.parse(readFileSync(resolve(root, "manifest.json"), "utf8"));
const packageJson = JSON.parse(readFileSync(resolve(root, "package.json"), "utf8"));
const localManifestSpecs = [
  { file: "manifest.dev.xml", label: "Word", host: "Document" },
  { file: "manifest.dev.excel.xml", label: "Excel", host: "Workbook" },
  { file: "manifest.dev.powerpoint.xml", label: "PowerPoint", host: "Presentation" },
];
const localManifests = localManifestSpecs.map((spec) => ({
  ...spec,
  source: readFileSync(resolve(root, spec.file), "utf8"),
}));
const errors = [];
const promotedScopes = ["document", "workbook", "presentation"];

if (manifest.version !== packageJson.version) errors.push("manifest version must match package version");
if (manifest.manifestVersion !== "1.25") errors.push("unified manifestVersion must be 1.25");
if (manifest.$schema !== "https://developer.microsoft.com/json-schemas/teams/v1.25/MicrosoftTeams.schema.json") {
  errors.push("unified manifest schema must match manifestVersion 1.25");
}
if (
  !Array.isArray(manifest.validDomains) ||
  manifest.validDomains.length !== 1 ||
  manifest.validDomains[0] !== "localhost:3000"
) {
  errors.push("validDomains must contain the localhost host and port without a URL scheme");
}
if (!Array.isArray(manifest.extensions) || manifest.extensions.length !== 1) errors.push("unified manifest must contain one extension");

const extension = manifest.extensions?.[0];
const scopes = new Set(extension?.requirements?.scopes ?? []);
if (scopes.size !== promotedScopes.length || !promotedScopes.every((scope) => scopes.has(scope))) {
  errors.push("release manifest must expose exactly Word/document, Excel/workbook, and PowerPoint/presentation");
}
const ribbonScopes = new Set(extension?.ribbons?.[0]?.requirements?.scopes ?? []);
if (ribbonScopes.size !== promotedScopes.length || !promotedScopes.every((scope) => ribbonScopes.has(scope))) {
  errors.push("release ribbon must expose exactly Word/document, Excel/workbook, and PowerPoint/presentation");
}
const permissions = manifest.authorization?.permissions?.resourceSpecific;
if (
  !Array.isArray(permissions) ||
  permissions.length !== 1 ||
  permissions[0]?.name !== "Document.ReadWrite.User" ||
  permissions[0]?.type !== "Delegated"
) {
  errors.push("release manifest must retain delegated Document.ReadWrite.User permission for all Office hosts");
}
const page = extension?.runtimes?.[0]?.code?.page;
if (page !== "https://localhost:3000/taskpane.html") errors.push("runtime page must use the trusted localhost HTTPS origin");
if (!existsSync(resolve(root, manifest.icons?.outline ?? ""))) errors.push("outline icon file is missing");
if (!existsSync(resolve(root, manifest.icons?.color ?? ""))) errors.push("color icon file is missing");

const manifestIds = new Set([manifest.id]);
for (const local of localManifests) {
  const xmlVersion = local.source.match(/<Version>([^<]+)<\/Version>/)?.[1];
  if (xmlVersion !== `${packageJson.version}.0`) {
    errors.push(`${local.file} version must match package version plus .0`);
  }

  const baseHosts = [...local.source.matchAll(/<Host Name="([^"]+)"\s*\/>/g)].map((match) => match[1]);
  const overrideHosts = [...local.source.matchAll(/<Host xsi:type="([^"]+)">/g)].map((match) => match[1]);
  if (baseHosts.length !== 1 || baseHosts[0] !== local.host) {
    errors.push(`${local.file} must target only the ${local.host} base host`);
  }
  if (overrideHosts.length !== 1 || overrideHosts[0] !== local.host) {
    errors.push(`${local.file} must target only the ${local.host} command host`);
  }

  const taskpaneUrls = local.source.match(/https:\/\/localhost:3000\/taskpane\.html/g) ?? [];
  if (taskpaneUrls.length < 2) {
    errors.push(`${local.file} must use the trusted task pane URL for fallback and command`);
  }
  if (!local.source.includes(`Local ${local.label} acceptance transport only`)) {
    errors.push(`${local.file} must remain visibly marked as acceptance-only`);
  }

  const id = local.source.match(/<Id>([^<]+)<\/Id>/)?.[1];
  if (!id) {
    errors.push(`${local.file} must contain an add-in ID`);
  } else if (manifestIds.has(id)) {
    errors.push(`${local.file} add-in ID must be unique`);
  } else {
    manifestIds.add(id);
  }
}

if (errors.length) {
  for (const error of errors) process.stderr.write(`manifest: ${error}\n`);
  process.exit(1);
}
process.stdout.write("unified release manifest and all local acceptance manifests are structurally valid\n");
