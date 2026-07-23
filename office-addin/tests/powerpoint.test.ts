import { describe, expect, it, vi } from "vitest";
import {
  PowerPointHostAdapter,
  type PowerPointGateway,
  type PowerPointSelectionRecord,
} from "../src/adapters/powerpoint";

function safeRecord(overrides: Partial<PowerPointSelectionRecord> = {}): PowerPointSelectionRecord {
  return {
    text: "selected",
    apiSupported: true,
    formattingUniform: true,
    formatting: ["Aptos", 18, false, false, "#000000", "None"],
    identity: {
      presentationId: "presentation-1",
      slideIds: ["slide-1"],
      shapeIds: ["shape-1"],
      rangeStart: 4,
      rangeLength: 8,
    },
    ...overrides,
  };
}

describe("PowerPointHostAdapter hardening", () => {
  it("uses the atomic validate-and-replace gateway and never the unchecked writer", async () => {
    const gateway: PowerPointGateway = {
      read: vi.fn().mockResolvedValue(safeRecord()),
      replace: vi.fn(),
      replaceIfUnchanged: vi.fn().mockResolvedValue(undefined),
    };
    const adapter = new PowerPointHostAdapter(gateway);
    const snapshot = await adapter.readSelection();

    await adapter.applyReplacement(snapshot, "[NAME_1]");

    expect(gateway.replaceIfUnchanged).toHaveBeenCalledWith(snapshot.fingerprint, "[NAME_1]");
    expect(gateway.replace).not.toHaveBeenCalled();
  });

  it("propagates a stale-selection rejection without falling back to an unchecked write", async () => {
    const gateway: PowerPointGateway = {
      read: vi.fn().mockResolvedValue(safeRecord()),
      replace: vi.fn(),
      replaceIfUnchanged: vi.fn().mockRejectedValue(new Error("Selection เปลี่ยนแล้ว กรุณาวิเคราะห์ใหม่")),
    };
    const adapter = new PowerPointHostAdapter(gateway);
    const snapshot = await adapter.readSelection();

    await expect(adapter.applyReplacement(snapshot, "[NAME_1]")).rejects.toThrow("เปลี่ยนแล้ว");
    expect(gateway.replace).not.toHaveBeenCalled();
  });

  it("distinguishes identical text at the same offset in different shapes", async () => {
    const first = safeRecord();
    const second = safeRecord({ identity: { ...first.identity!, shapeIds: ["shape-2"] } });
    const gateway: PowerPointGateway = {
      read: vi.fn().mockResolvedValueOnce(first).mockResolvedValueOnce(second),
      replace: vi.fn(),
    };
    const adapter = new PowerPointHostAdapter(gateway);
    const snapshot = await adapter.readSelection();

    await expect(adapter.applyReplacement(snapshot, "[NAME_1]")).rejects.toThrow("เปลี่ยนแล้ว");
    expect(gateway.replace).not.toHaveBeenCalled();
  });

  it.each([
    ["unsupported API", safeRecord({ apiSupported: false })],
    ["mixed formatting", safeRecord({ formattingUniform: false, formatting: ["Aptos", null] })],
    ["multiple shapes", safeRecord({ identity: { ...safeRecord().identity!, shapeIds: ["shape-1", "shape-2"] } })],
    ["multiple slides", safeRecord({ identity: { ...safeRecord().identity!, slideIds: ["slide-1", "slide-2"] } })],
    ["no text selection", safeRecord({ text: "   " })],
    ["selection read failure", safeRecord({ readFailure: true })],
  ])("fails closed for %s", async (_label, record) => {
    const gateway: PowerPointGateway = { read: vi.fn().mockResolvedValue(record), replace: vi.fn() };
    const adapter = new PowerPointHostAdapter(gateway);
    const snapshot = await adapter.readSelection();

    expect(snapshot.writeback.allowed).toBe(false);
    await expect(adapter.applyReplacement(snapshot, "[NAME_1]")).rejects.toThrow();
    expect(gateway.replace).not.toHaveBeenCalled();
  });

  it("turns Office selection exceptions into a copy-only failure without exposing exception text", async () => {
    const gateway: PowerPointGateway = {
      read: vi.fn().mockRejectedValue(new Error("document-content-from-host")),
      replace: vi.fn(),
    };
    const snapshot = await new PowerPointHostAdapter(gateway).readSelection();

    expect(snapshot.writeback.allowed).toBe(false);
    expect(snapshot.writeback.reasons.join(" ")).toContain("ไม่สามารถยืนยัน");
    expect(snapshot.writeback.reasons.join(" ")).not.toContain("document-content-from-host");
  });

  it("keeps AI answers Copy-only and rejects non-text replacement payloads", async () => {
    const gateway: PowerPointGateway = { read: vi.fn().mockResolvedValue(safeRecord()), replace: vi.fn() };
    const adapter = new PowerPointHostAdapter(gateway);
    const snapshot = await adapter.readSelection();

    expect(adapter.canInsertResponse).toBe(false);
    await expect(adapter.insertResponse(snapshot, "answer")).rejects.toThrow("Copy");
    await expect(
      adapter.applyReplacement(snapshot, { kind: "excel-cells", values: [], changedCells: [], skipped: [] }),
    ).rejects.toThrow("เฉพาะข้อความ");
    expect(gateway.replace).not.toHaveBeenCalled();
  });
});
