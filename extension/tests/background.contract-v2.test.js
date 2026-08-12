import fs from "node:fs";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const EXTENSION = path.resolve("extension");

function nativeSanitize(overrides = {}) {
  return {
    detected_entity_count: 1,
    entity_type_counts: { NAME: 1 },
    guard_findings: [],
    highlights: [{ data_type: "NAME", end: 8, redact_type: "TB", start: 0 }],
    replacement_count: 1,
    safety: { residual_count: 0, status: "pass" },
    sanitized_text: "[NAME_1]",
    section26_categories: [],
    warnings: [],
    ...overrides,
  };
}

beforeEach(async () => {
  vi.resetModules();
  await import("../contract-v2.js");
});

afterEach(() => {
  delete global.AIGUARD_CONTRACT_V2;
});

describe("installed Extension native-only boundary", () => {
  it("retains no loopback permission and adds only nativeMessaging", () => {
    const manifest = JSON.parse(fs.readFileSync(path.join(EXTENSION, "manifest.json"), "utf8"));
    expect(manifest.permissions).toEqual([
      "storage",
      "clipboardWrite",
      "sidePanel",
      "nativeMessaging",
    ]);
    expect(manifest).not.toHaveProperty("host_permissions");
  });

  it("has no production HTTP, loopback, credential, backend ID, or provider command", () => {
    const sources = ["background.js", "content.js", "sidepanel.js", "contract-v2.js"]
      .map((name) => fs.readFileSync(path.join(EXTENSION, name), "utf8"))
      .join("\n");
    for (const forbidden of [
      "fetch(",
      "localhost",
      "127.0.0.1",
      "AIGUARD_API_KEY",
      "AIFORTHAI_API_KEY",
      "backend_url",
      "backend_port",
      "session_id",
      "provider_selection",
      "remote_tner",
    ]) {
      expect(sources).not.toContain(forbidden);
    }
  });

  it("allows connectNative only in the service worker", () => {
    const background = fs.readFileSync(path.join(EXTENSION, "background.js"), "utf8");
    const content = fs.readFileSync(path.join(EXTENSION, "content.js"), "utf8");
    const panel = fs.readFileSync(path.join(EXTENSION, "sidepanel.js"), "utf8");
    expect(background.match(/connectNative\(/g)).toHaveLength(1);
    expect(content).not.toContain("connectNative");
    expect(panel).not.toContain("connectNative");
  });

  it("uses no inline script that MV3 CSP would reject", () => {
    const panel = fs.readFileSync(path.join(EXTENSION, "sidepanel.html"), "utf8");
    expect(panel).not.toMatch(/<script(?![^>]*\bsrc=)[^>]*>/i);
    expect(panel).toContain('<script src="theme-bootstrap.js"></script>');
  });

  it("strictly projects native sanitize without a session or unknown field", () => {
    const projected = global.AIGUARD_CONTRACT_V2.validateNativeSanitize(nativeSanitize());
    expect(projected).toEqual(nativeSanitize());
    expect(() =>
      global.AIGUARD_CONTRACT_V2.validateNativeSanitize(
        nativeSanitize({ original_text: "synthetic" })
      )
    ).toThrow(/native sanitize/i);
  });

  it("rejects unsafe, empty, and inconsistent sanitize DTOs", () => {
    for (const payload of [
      nativeSanitize({ safety: { residual_count: 1, status: "pass" } }),
      nativeSanitize({
        detected_entity_count: 0,
        entity_type_counts: {},
        highlights: [],
        replacement_count: 0,
        sanitized_text: "",
      }),
      nativeSanitize({ replacement_count: 2 }),
    ]) {
      expect(() => global.AIGUARD_CONTRACT_V2.validateNativeSanitize(payload)).toThrow();
    }
  });

  it("strictly projects only fixed native health metadata", () => {
    expect(
      global.AIGUARD_CONTRACT_V2.validateNativeHealth({
        product_version: "2.5.0",
        status: "ok",
      })
    ).toEqual({
      status: "ok",
      version: "2.5.0",
      contract_version: 2,
      capabilities: { control_token_required: true, api_key_required: false },
    });
    expect(() =>
      global.AIGUARD_CONTRACT_V2.validateNativeHealth({
        endpoint: "synthetic",
        product_version: "2.5.0",
        status: "ok",
      })
    ).toThrow(/native health/i);
  });
});
