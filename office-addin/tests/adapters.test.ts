import { describe, expect, it, vi } from "vitest";
import { ExcelHostAdapter, type ExcelGateway } from "../src/adapters/excel";
import { PowerPointHostAdapter, type PowerPointGateway } from "../src/adapters/powerpoint";
import { OfficeWordGateway, WordHostAdapter, type WordGateway } from "../src/adapters/word";

describe("WordHostAdapter", () => {
  const uniformDirectFont = (overrides: Record<string, string | number | boolean | null> = {}) => ({
    bold: false,
    italic: false,
    underline: "None",
    size: 11,
    color: "#000000",
    highlightColor: null,
    strikeThrough: false,
    doubleStrikeThrough: false,
    subscript: false,
    superscript: false,
    load: vi.fn(),
    ...overrides,
  });

  it("validates and replaces the same captured Word range in one write transaction", async () => {
    const range = {
      text: "selected",
      load: vi.fn(),
      paragraphs: { items: [{}], load: vi.fn() },
      tables: { items: [], load: vi.fn() },
      font: uniformDirectFont(),
      insertText: vi.fn(),
    };
    const context = {
      document: { getSelection: vi.fn(() => range) },
      sync: vi.fn().mockResolvedValue(undefined),
    };
    const run = vi.fn(async (callback: (value: typeof context) => Promise<unknown>) => callback(context));
    vi.stubGlobal("Word", { run, InsertLocation: { replace: "Replace", after: "After" } });
    try {
      const adapter = new WordHostAdapter(new OfficeWordGateway());
      const snapshot = await adapter.readSelection();
      await adapter.applyReplacement(snapshot, "[NAME_1]");

      expect(run).toHaveBeenCalledTimes(2);
      expect(context.document.getSelection).toHaveBeenCalledTimes(2);
      expect(range.insertText).toHaveBeenCalledWith("[NAME_1]", "Replace");
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("replaces only an unchanged, single-paragraph, uniform selection", async () => {
    const gateway: WordGateway = {
      read: vi.fn().mockResolvedValue({ text: "selected", paragraphCount: 1, tableCount: 0, formatting: ["Aptos", 11, false, false, "#000", "None"] }),
      replaceIfCurrent: vi.fn().mockResolvedValue(undefined),
      insertAfterIfCurrent: vi.fn().mockResolvedValue(undefined),
    };
    const adapter = new WordHostAdapter(gateway);
    const snapshot = await adapter.readSelection();
    expect(snapshot.writeback.allowed).toBe(true);
    await adapter.applyReplacement(snapshot, "[NAME_1]");
    expect(gateway.read).toHaveBeenCalledTimes(1);
    expect(gateway.replaceIfCurrent).toHaveBeenCalledWith(snapshot.fingerprint, "[NAME_1]");
    await adapter.insertResponse(snapshot, "answer");
    expect(gateway.read).toHaveBeenCalledTimes(1);
    expect(gateway.insertAfterIfCurrent).toHaveBeenCalledWith(snapshot.fingerprint, "answer");
  });

  it("does not treat a Thai/Latin script-font fallback as mixed direct formatting", async () => {
    const directFonts = [
      uniformDirectFont(),
      uniformDirectFont(),
    ];
    const range = {
      text: "นาย A",
      load: vi.fn(),
      paragraphs: { items: [{}], load: vi.fn() },
      tables: { items: [], load: vi.fn() },
      font: { name: null, size: null, color: null, bold: null, italic: null, underline: null, load: vi.fn() },
      getTextRanges: vi.fn(() => ({
        items: directFonts.map((font) => ({ font })),
        load: vi.fn(),
      })),
    };
    const context = { document: { getSelection: vi.fn(() => range) }, sync: vi.fn().mockResolvedValue(undefined) };
    vi.stubGlobal("Word", { run: vi.fn(async (callback: (value: typeof context) => Promise<unknown>) => callback(context)) });

    try {
      const snapshot = await new WordHostAdapter(new OfficeWordGateway()).readSelection();
      expect(snapshot.writeback.allowed).toBe(true);
      expect(range.getTextRanges).toHaveBeenCalled();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("keeps a real bold/non-bold run mix copy-only", async () => {
    const directFonts = [
      uniformDirectFont(),
      uniformDirectFont({ bold: true }),
    ];
    const range = {
      text: "0812",
      load: vi.fn(),
      paragraphs: { items: [{}], load: vi.fn() },
      tables: { items: [], load: vi.fn() },
      font: { load: vi.fn() },
      getTextRanges: vi.fn(() => ({
        items: directFonts.map((font) => ({ font })),
        load: vi.fn(),
      })),
    };
    const context = { document: { getSelection: vi.fn(() => range) }, sync: vi.fn().mockResolvedValue(undefined) };
    vi.stubGlobal("Word", { run: vi.fn(async (callback: (value: typeof context) => Promise<unknown>) => callback(context)) });

    try {
      const snapshot = await new WordHostAdapter(new OfficeWordGateway()).readSelection();
      expect(snapshot.writeback.allowed).toBe(false);
      expect(snapshot.writeback.reasons.join(" ")).toContain("รูปแบบตัวอักษรหลายแบบ");
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it.each([
    ["font size", { size: 14 }],
    ["font color", { color: "#FF0000" }],
    ["highlight", { highlightColor: "Yellow" }],
  ])("keeps a real mixed %s selection copy-only", async (_label, changedFormatting) => {
    const directFonts = [uniformDirectFont(), uniformDirectFont(changedFormatting)];
    const range = {
      text: "AB",
      load: vi.fn(),
      paragraphs: { items: [{}], load: vi.fn() },
      tables: { items: [], load: vi.fn() },
      font: { load: vi.fn() },
      getTextRanges: vi.fn(() => ({
        items: directFonts.map((font) => ({ font })),
        load: vi.fn(),
      })),
    };
    const context = { document: { getSelection: vi.fn(() => range) }, sync: vi.fn().mockResolvedValue(undefined) };
    vi.stubGlobal("Word", { run: vi.fn(async (callback: (value: typeof context) => Promise<unknown>) => callback(context)) });

    try {
      const snapshot = await new WordHostAdapter(new OfficeWordGateway()).readSelection();
      expect(snapshot.writeback.allowed).toBe(false);
      expect(snapshot.writeback.reasons.join(" ")).toContain("รูปแบบตัวอักษรหลายแบบ");
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("fails closed when the aggregate-format fallback cannot prove uniform formatting", async () => {
    const range = {
      text: "นาย A",
      load: vi.fn(),
      paragraphs: { items: [{}], load: vi.fn() },
      tables: { items: [], load: vi.fn() },
      font: { bold: null, italic: null, underline: null, load: vi.fn() },
    };
    const context = { document: { getSelection: vi.fn(() => range) }, sync: vi.fn().mockResolvedValue(undefined) };
    vi.stubGlobal("Word", { run: vi.fn(async (callback: (value: typeof context) => Promise<unknown>) => callback(context)) });

    try {
      const snapshot = await new WordHostAdapter(new OfficeWordGateway()).readSelection();
      expect(snapshot.writeback.allowed).toBe(false);
      expect(snapshot.writeback.reasons.join(" ")).toContain("ยืนยันรูปแบบไม่ได้");
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("keeps selections over the bounded formatting check copy-only with an explicit reason", async () => {
    const range = {
      text: "ก".repeat(501),
      load: vi.fn(),
      paragraphs: { items: [{}], load: vi.fn() },
      tables: { items: [], load: vi.fn() },
      font: { load: vi.fn() },
      getTextRanges: vi.fn(),
    };
    const context = { document: { getSelection: vi.fn(() => range) }, sync: vi.fn().mockResolvedValue(undefined) };
    vi.stubGlobal("Word", { run: vi.fn(async (callback: (value: typeof context) => Promise<unknown>) => callback(context)) });

    try {
      const snapshot = await new WordHostAdapter(new OfficeWordGateway()).readSelection();
      expect(snapshot.writeback.allowed).toBe(false);
      expect(snapshot.writeback.reasons.join(" ")).toContain("ไม่เกิน 500 ตัวอักษร");
      expect(range.getTextRanges).not.toHaveBeenCalled();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("delegates stale-selection validation to the atomic Word write transaction", async () => {
    const gateway: WordGateway = {
      read: vi.fn().mockResolvedValue({ text: "selected", paragraphCount: 1, tableCount: 0, formatting: ["Aptos", 11, false, false, "#000", "None"] }),
      replaceIfCurrent: vi.fn().mockRejectedValue(new Error("Selection เปลี่ยนแล้ว")),
      insertAfterIfCurrent: vi.fn(),
    };
    const adapter = new WordHostAdapter(gateway);
    const snapshot = await adapter.readSelection();

    await expect(adapter.applyReplacement(snapshot, "[NAME_1]")).rejects.toThrow("Selection เปลี่ยนแล้ว");
    expect(gateway.read).toHaveBeenCalledTimes(1);
  });

  it("keeps mixed formatting and tables copy-only", async () => {
    const gateway: WordGateway = {
      read: vi.fn().mockResolvedValue({ text: "selected", paragraphCount: 1, tableCount: 1, formatting: [null, 11] }),
      replaceIfCurrent: vi.fn(),
      insertAfterIfCurrent: vi.fn(),
    };
    const snapshot = await new WordHostAdapter(gateway).readSelection();
    expect(snapshot.writeback.allowed).toBe(false);
    expect(snapshot.writeback.reasons.join(" ")).toContain("ตาราง");
  });
});

describe("ExcelHostAdapter", () => {
  it("sanitizes only text cells and never writes formulas, numbers, or dates", async () => {
    const gateway: ExcelGateway = {
      read: vi.fn().mockResolvedValue({
        address: "Sheet1!A1:C2",
        values: [["person", 42, "formula-result"], [45123, "", "other"]],
        formulas: [["person", 42, "=A1"], [45123, "", "other"]],
        displayText: [["person", "42", "formula-result"], ["1/1/2023", "", "other"]],
      }),
      writeCells: vi.fn().mockResolvedValue(undefined),
    };
    const adapter = new ExcelHostAdapter(gateway);
    const snapshot = await adapter.readSelection();
    const replacement = await adapter.buildMaskPreview(snapshot, async (text) => `[${text}]`);
    expect(replacement.changedCells).toEqual([{ row: 0, column: 0 }, { row: 1, column: 2 }]);
    const restored = await adapter.buildRestorePreview(snapshot, async (text) => `restored-${text}`);
    expect(restored.changedCells).toEqual([{ row: 0, column: 0 }, { row: 1, column: 2 }]);
    await adapter.applyReplacement(snapshot, replacement);
    expect(gateway.writeCells).toHaveBeenCalledWith([
      { row: 0, column: 0, value: "[person]" },
      { row: 1, column: 2, value: "[other]" },
    ]);
  });

  it("cancels apply when formulas changed after preview", async () => {
    const original = { address: "Sheet1!A1", values: [["person"]], formulas: [["person"]], displayText: [["person"]] };
    const changed = { ...original, formulas: [["=NOW()"]] };
    const gateway: ExcelGateway = { read: vi.fn().mockResolvedValueOnce(original).mockResolvedValueOnce(changed), writeCells: vi.fn() };
    const adapter = new ExcelHostAdapter(gateway);
    const snapshot = await adapter.readSelection();
    const replacement = await adapter.buildMaskPreview(snapshot, async () => "[NAME_1]");
    await expect(adapter.applyReplacement(snapshot, replacement)).rejects.toThrow("เปลี่ยนแล้ว");
    expect(gateway.writeCells).not.toHaveBeenCalled();
  });
});

describe("PowerPointHostAdapter", () => {
  it("fails closed when PowerPoint API 1.5 is unavailable", async () => {
    const gateway: PowerPointGateway = {
      read: vi.fn().mockResolvedValue({ text: "", apiSupported: false, formattingUniform: false, formatting: [] }),
      replace: vi.fn(),
    };
    const snapshot = await new PowerPointHostAdapter(gateway).readSelection();
    expect(snapshot.writeback.allowed).toBe(false);
    expect(snapshot.writeback.reasons.join(" ")).toContain("1.5");
    expect(gateway.replace).not.toHaveBeenCalled();
  });

  it("changes only the selected text range after a fresh capability/format check", async () => {
    const record = { text: "selected", apiSupported: true, formattingUniform: true, formatting: ["Aptos", 18, false] };
    const gateway: PowerPointGateway = { read: vi.fn().mockResolvedValue(record), replace: vi.fn().mockResolvedValue(undefined) };
    const adapter = new PowerPointHostAdapter(gateway);
    const snapshot = await adapter.readSelection();
    await adapter.applyReplacement(snapshot, "[NAME_1]");
    expect(gateway.replace).toHaveBeenCalledTimes(1);
    expect(gateway.replace).toHaveBeenCalledWith("[NAME_1]");
  });
});
