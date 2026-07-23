import { describe, expect, it, vi } from "vitest";
import { ExcelHostAdapter, type ExcelGateway } from "../src/adapters/excel";
import type { ExcelReplacement, ExcelSelectionData } from "../src/types";

const selectedRange: ExcelSelectionData = {
  address: "Sheet1!A1:C2",
  values: [["alpha", 42, "calculated"], [45123, "", "beta"]],
  formulas: [["alpha", 42, "=A1"], [45123, "", "beta"]],
  displayText: [["alpha", "42", "calculated"], ["1/1/2023", "", "beta"]],
};

function gatewayWithReads(...reads: ExcelSelectionData[]): ExcelGateway {
  return {
    read: vi.fn().mockResolvedValueOnce(reads[0]).mockResolvedValueOnce(reads[1] ?? reads[0]),
    writeCells: vi.fn().mockResolvedValue(undefined),
  };
}

describe("ExcelHostAdapter cell safety", () => {
  it("masks and restores only non-empty text constants", async () => {
    const gateway = gatewayWithReads(selectedRange);
    const adapter = new ExcelHostAdapter(gateway);
    const snapshot = await adapter.readSelection();
    const mask = vi.fn(async (text: string) => `[${text}]`);
    const restore = vi.fn(async (text: string) => `restored-${text}`);

    const masked = await adapter.buildMaskPreview(snapshot, mask);
    const restored = await adapter.buildRestorePreview(snapshot, restore);

    expect(mask).toHaveBeenCalledTimes(2);
    expect(restore).toHaveBeenCalledTimes(2);
    expect(masked.changedCells).toEqual([{ row: 0, column: 0 }, { row: 1, column: 2 }]);
    expect(restored.changedCells).toEqual([{ row: 0, column: 0 }, { row: 1, column: 2 }]);
    expect(masked.values).toEqual([["[alpha]", 42, "calculated"], [45123, "", "[beta]"]]);
    expect(restored.values).toEqual([["restored-alpha", 42, "calculated"], [45123, "", "restored-beta"]]);
    expect(masked.skipped).toHaveLength(4);
  });

  it.each([
    ["address", { ...selectedRange, address: "Sheet1!B1:D2" }],
    ["values", { ...selectedRange, values: [["changed", 42, "calculated"], [45123, "", "beta"]] }],
    ["formulas", { ...selectedRange, formulas: [["alpha", 42, "=NOW()"], [45123, "", "beta"]] }],
  ])("re-reads and rejects changed %s before Apply", async (_field, current) => {
    const gateway = gatewayWithReads(selectedRange, current);
    const adapter = new ExcelHostAdapter(gateway);
    const snapshot = await adapter.readSelection();
    const replacement = await adapter.buildMaskPreview(snapshot, async (text) => `[${text}]`);

    await expect(adapter.applyReplacement(snapshot, replacement)).rejects.toThrow("เปลี่ยนแล้ว");
    expect(gateway.writeCells).not.toHaveBeenCalled();
  });

  it.each([
    ["formula", { row: 0, column: 2 }],
    ["number", { row: 0, column: 1 }],
    ["date", { row: 1, column: 0 }],
    ["blank", { row: 1, column: 1 }],
    ["outside", { row: 8, column: 8 }],
  ])("rejects a forged %s-cell write", async (_kind, changedCell) => {
    const gateway = gatewayWithReads(selectedRange);
    const adapter = new ExcelHostAdapter(gateway);
    const snapshot = await adapter.readSelection();
    const replacement: ExcelReplacement = {
      kind: "excel-cells",
      values: selectedRange.values.map((row) => [...row]),
      changedCells: [changedCell],
      skipped: [],
    };
    replacement.values[changedCell.row] ??= [];
    replacement.values[changedCell.row]![changedCell.column] = "[TOKEN]";

    await expect(adapter.applyReplacement(snapshot, replacement)).rejects.toThrow();
    expect(gateway.writeCells).not.toHaveBeenCalled();
  });

  it("rejects duplicate cell writes", async () => {
    const gateway = gatewayWithReads(selectedRange);
    const adapter = new ExcelHostAdapter(gateway);
    const snapshot = await adapter.readSelection();
    const replacement = await adapter.buildMaskPreview(snapshot, async (text) => `[${text}]`);
    replacement.changedCells.push({ ...replacement.changedCells[0]! });

    await expect(adapter.applyReplacement(snapshot, replacement)).rejects.toThrow("ไม่ถูกต้อง");
    expect(gateway.writeCells).not.toHaveBeenCalled();
  });

  it("writes only the verified changed text cells", async () => {
    const gateway = gatewayWithReads(selectedRange);
    const adapter = new ExcelHostAdapter(gateway);
    const snapshot = await adapter.readSelection();
    const replacement = await adapter.buildRestorePreview(snapshot, async (text) => `restored-${text}`);

    await adapter.applyReplacement(snapshot, replacement);

    expect(gateway.writeCells).toHaveBeenCalledOnce();
    expect(gateway.writeCells).toHaveBeenCalledWith([
      { row: 0, column: 0, value: "restored-alpha" },
      { row: 1, column: 2, value: "restored-beta" },
    ]);
  });

  it("uses the atomic gateway revalidation when available", async () => {
    const gateway = gatewayWithReads(selectedRange);
    gateway.writeCellsIfUnchanged = vi.fn().mockResolvedValue(undefined);
    const adapter = new ExcelHostAdapter(gateway);
    const snapshot = await adapter.readSelection();
    const replacement = await adapter.buildMaskPreview(snapshot, async (text) => `[${text}]`);

    await adapter.applyReplacement(snapshot, replacement);

    expect(gateway.writeCellsIfUnchanged).toHaveBeenCalledWith(selectedRange, [
      { row: 0, column: 0, value: "[alpha]" },
      { row: 1, column: 2, value: "[beta]" },
    ]);
    expect(gateway.writeCells).not.toHaveBeenCalled();
  });

  it("keeps Ask AI response Copy-only", async () => {
    const adapter = new ExcelHostAdapter(gatewayWithReads(selectedRange));
    expect(adapter.canInsertResponse).toBe(false);
    await expect(adapter.insertResponse(await adapter.readSelection(), "answer")).rejects.toThrow("Copy");
  });
});
