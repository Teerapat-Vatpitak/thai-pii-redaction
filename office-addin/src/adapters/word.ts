import type { HostAdapter, ReplacementPayload, SelectionSnapshot, WritebackAssessment } from "../types";
import { fingerprint } from "../types";
import { UserVisibleError } from "../errors";

export interface WordSelectionRecord {
  text: string;
  paragraphCount: number;
  tableCount: number;
  /**
   * Direct formatting properties that Word can report reliably for a range.
   * `font.name` is deliberately excluded because Word resolves Thai and Latin
   * script fallback fonts independently. Size, color, emphasis, highlight,
   * strike-through, and baseline properties remain part of the signature so a
   * replacement cannot silently flatten those user-visible differences.
   */
  formatting: Array<string | number | boolean | null>;
  /** Production reads set this; injected gateways may omit it for compatibility. */
  formattingStatus?: "uniform" | "mixed" | "too-large";
}

export interface WordGateway {
  read(): Promise<WordSelectionRecord>;
  replaceIfCurrent(expectedFingerprint: string, text: string): Promise<void>;
  insertAfterIfCurrent(expectedFingerprint: string, text: string): Promise<void>;
}

const MAX_FORMAT_CHECK_CHARACTERS = 500;
const DIRECT_FORMAT_PROPERTIES =
  "bold,italic,underline,size,color,highlightColor,strikeThrough,doubleStrikeThrough,subscript,superscript";

interface FormattingResult {
  formatting: Array<string | number | boolean | null>;
  status: NonNullable<WordSelectionRecord["formattingStatus"]>;
}

type FontRecord = Record<string, string | number | boolean | null | undefined>;

function directFormattingSignature(font: FontRecord): string | null {
  const requiredValues = [
    font.bold,
    font.italic,
    font.underline,
    font.size,
    font.strikeThrough,
    font.doubleStrikeThrough,
    font.subscript,
    font.superscript,
  ];
  if (requiredValues.some((value) => value === null || value === undefined)) return null;

  // Word reports automatic font/highlight colors as null on some hosts. That
  // is a stable value when every checked run is automatic; an empty string is
  // the documented mixed-highlight sentinel and therefore cannot be written.
  const color = font.color ?? null;
  const highlightColor = font.highlightColor ?? null;
  if (color === "" || highlightColor === "") return null;

  return JSON.stringify([...requiredValues, color, highlightColor]);
}

/**
 * Checks direct formatting run-by-run instead of asking Word for one aggregate
 * font. The aggregate reports `null` for normal Thai + Latin text because the
 * host resolves different script fallback fonts, which is not user-applied
 * mixed formatting. Splitting on every selected character lets Word report
 * each run's actual user-visible formatting without retaining its text.
 */
async function readDirectFormatting(context: Word.RequestContext, range: Word.Range): Promise<FormattingResult> {
  const textCharacters = Array.from(range.text);
  const characters = Array.from(new Set(textCharacters));
  if (characters.length === 0) return { formatting: [null], status: "mixed" };
  if (textCharacters.length > MAX_FORMAT_CHECK_CHARACTERS) {
    return { formatting: [null], status: "too-large" };
  }

  // The fallback keeps older/mocked Office.js gateways fail-closed. Current
  // supported Word Desktop supplies `getTextRanges` (WordApi 1.3+).
  if (typeof range.getTextRanges !== "function") {
    range.font.load(DIRECT_FORMAT_PROPERTIES);
    await context.sync();
    const signature = directFormattingSignature(range.font as unknown as FontRecord);
    return signature === null
      ? { formatting: [null], status: "mixed" }
      : { formatting: [signature], status: "uniform" };
  }

  const ranges = range.getTextRanges(characters, false);
  ranges.load("items");
  await context.sync();
  for (const textRange of ranges.items) textRange.font.load(DIRECT_FORMAT_PROPERTIES);
  await context.sync();

  const signatures = new Set(ranges.items.map((textRange) => directFormattingSignature(textRange.font as unknown as FontRecord)));
  const onlySignature = signatures.values().next().value;
  return signatures.size === 1 && onlySignature !== null && onlySignature !== undefined
    ? { formatting: [onlySignature], status: "uniform" }
    : { formatting: [null], status: "mixed" };
}

function recordFingerprint(record: WordSelectionRecord): string {
  return fingerprint([record.text, record.paragraphCount, record.tableCount, record.formatting, record.formattingStatus ?? null]);
}

function assessRecord(record: WordSelectionRecord): WritebackAssessment {
  const reasons: string[] = [];
  const formattingStatus =
    record.formattingStatus ?? (record.formatting.some((value) => value === null) ? "mixed" : "uniform");
  if (!record.text.trim()) reasons.push("กรุณาเลือกข้อความที่ไม่ว่าง");
  if (record.paragraphCount !== 1) reasons.push(`เลือกได้ครั้งละหนึ่งย่อหน้าเท่านั้น (พบ ${record.paragraphCount})`);
  if (/[\r\n]/u.test(record.text)) reasons.push("selection มีอักขระขึ้นย่อหน้า จึงไม่เขียนทับ");
  if (record.tableCount > 0) reasons.push("ข้อความในตารางรองรับ Preview/Copy เท่านั้น");
  if (formattingStatus === "too-large") {
    reasons.push(`selection สำหรับเขียนกลับต้องไม่เกิน ${MAX_FORMAT_CHECK_CHARACTERS} ตัวอักษร`);
  } else if (formattingStatus === "mixed") {
    reasons.push("selection มีรูปแบบตัวอักษรหลายแบบหรือยืนยันรูปแบบไม่ได้ จึงไม่เขียนทับ");
  }
  return { allowed: reasons.length === 0, reasons };
}

export class OfficeWordGateway implements WordGateway {
  async read(): Promise<WordSelectionRecord> {
    return Word.run(async (context) => {
      const range = context.document.getSelection();
      const parentTable = range.parentTableOrNullObject;
      range.load("text");
      range.paragraphs.load("items");
      range.tables.load("items");
      parentTable.load("isNullObject");
      await context.sync();
      const formatting = await readDirectFormatting(context, range);
      return {
        text: range.text,
        paragraphCount: range.paragraphs.items.length,
        tableCount: parentTable.isNullObject ? range.tables.items.length : Math.max(1, range.tables.items.length),
        formatting: formatting.formatting,
        formattingStatus: formatting.status,
      };
    });
  }

  async replaceIfCurrent(expectedFingerprint: string, text: string): Promise<void> {
    await Word.run(async (context) => {
      const range = context.document.getSelection();
      const record = await this.loadRecord(context, range);
      this.assertCurrent(expectedFingerprint, record);
      range.insertText(text, Word.InsertLocation.replace);
      await context.sync();
    });
  }

  async insertAfterIfCurrent(expectedFingerprint: string, text: string): Promise<void> {
    await Word.run(async (context) => {
      const range = context.document.getSelection();
      const record = await this.loadRecord(context, range);
      this.assertCurrent(expectedFingerprint, record);
      range.insertText(`\n${text}`, Word.InsertLocation.after);
      await context.sync();
    });
  }

  private async loadRecord(context: Word.RequestContext, range: Word.Range): Promise<WordSelectionRecord> {
    const parentTable = range.parentTableOrNullObject;
    range.load("text");
    range.paragraphs.load("items");
    range.tables.load("items");
    parentTable.load("isNullObject");
    await context.sync();
    const formatting = await readDirectFormatting(context, range);
    return {
      text: range.text,
      paragraphCount: range.paragraphs.items.length,
      tableCount: parentTable.isNullObject ? range.tables.items.length : Math.max(1, range.tables.items.length),
      formatting: formatting.formatting,
      formattingStatus: formatting.status,
    };
  }

  private assertCurrent(expectedFingerprint: string, record: WordSelectionRecord): void {
    if (recordFingerprint(record) !== expectedFingerprint) {
      throw new UserVisibleError("Selection เปลี่ยนแล้ว กรุณาวิเคราะห์ใหม่ก่อน Apply");
    }
    const assessment = assessRecord(record);
    if (!assessment.allowed) throw new UserVisibleError(assessment.reasons.join("; "));
  }
}

export class WordHostAdapter implements HostAdapter {
  readonly host = "Word" as const;
  readonly canInsertResponse = true;

  constructor(private readonly gateway: WordGateway = new OfficeWordGateway()) {}

  async readSelection(): Promise<SelectionSnapshot> {
    const record = await this.gateway.read();
    const snapshot: SelectionSnapshot = {
      host: this.host,
      text: record.text,
      fingerprint: recordFingerprint(record),
      writeback: { allowed: false, reasons: [] },
    };
    snapshot.writeback = this.assessRecord(record);
    return snapshot;
  }

  assessWriteback(snapshot: SelectionSnapshot): WritebackAssessment {
    return snapshot.writeback;
  }

  async applyReplacement(expected: SelectionSnapshot, replacement: ReplacementPayload): Promise<void> {
    if (typeof replacement !== "string") {
      throw new UserVisibleError("Word รับเฉพาะข้อความสำหรับเขียนกลับ");
    }
    await this.gateway.replaceIfCurrent(expected.fingerprint, replacement);
  }

  async insertResponse(expected: SelectionSnapshot, response: string): Promise<void> {
    await this.gateway.insertAfterIfCurrent(expected.fingerprint, response);
  }

  private assessRecord(record: WordSelectionRecord): WritebackAssessment {
    return assessRecord(record);
  }
}
