import type { HostAdapter, ReplacementPayload, SelectionSnapshot, WritebackAssessment } from "../types";
import { fingerprint } from "../types";
import { UserVisibleError } from "../errors";

export interface PowerPointSelectionIdentity {
  presentationId: string;
  slideIds: string[];
  shapeIds: string[];
  rangeStart: number;
  rangeLength: number;
}

export interface PowerPointSelectionRecord {
  text: string;
  apiSupported: boolean;
  formattingUniform: boolean;
  formatting: Array<string | number | boolean | null>;
  identity?: PowerPointSelectionIdentity;
  readFailure?: boolean;
}

export interface PowerPointGateway {
  read(): Promise<PowerPointSelectionRecord>;
  replace(text: string): Promise<void>;
  /**
   * Production gateways validate the selected slide, shape, character range, text,
   * and formatting in the same PowerPoint.run batch that queues the write. This
   * closes the read-then-write selection race. `replace` remains for small injected
   * test gateways; OfficePowerPointGateway never uses it for an adapter write.
   */
  replaceIfUnchanged?(expectedFingerprint: string, text: string): Promise<void>;
}

const FONT_PROPERTIES = "name,size,bold,italic,color,underline";

function recordFingerprint(record: PowerPointSelectionRecord): string {
  return fingerprint([record.text, record.formatting, record.identity ?? null]);
}

function assessRecord(record: PowerPointSelectionRecord): WritebackAssessment {
  const reasons: string[] = [];
  if (!record.apiSupported) reasons.push("ต้องใช้ PowerPoint API 1.5 ขึ้นไป");
  if (record.readFailure) reasons.push("ไม่สามารถยืนยัน selected text range ได้ จึงไม่เขียนกลับ");
  if (!record.text.trim()) reasons.push("กรุณาเลือก text range ใน shape เดียว");
  if (!record.formattingUniform || record.formatting.some((value) => value === null || value === undefined)) {
    reasons.push("รูปแบบตัวอักษรไม่สม่ำเสมอ จึงรองรับ Preview/Copy เท่านั้น");
  }
  if (record.identity && (record.identity.slideIds.length !== 1 || record.identity.shapeIds.length !== 1)) {
    reasons.push("เลือกข้อความได้ครั้งละหนึ่ง shape บนหนึ่ง slide เท่านั้น");
  }
  return { allowed: reasons.length === 0, reasons };
}

async function readRecordInContext(context: PowerPoint.RequestContext): Promise<{
  range: PowerPoint.TextRange;
  record: PowerPointSelectionRecord;
}> {
  // getSelectedTextRange deliberately excludes notes, images, and unselected shapes.
  // It throws when the current selection is not an editable text range; callers fail closed.
  const presentation = context.presentation;
  const range = presentation.getSelectedTextRange();
  const slides = presentation.getSelectedSlides();
  const shapes = presentation.getSelectedShapes();
  presentation.load("id");
  range.load("text,start,length");
  range.font.load(FONT_PROPERTIES);
  slides.load("items/id");
  shapes.load("items/id");
  await context.sync();

  const formatting = [
    range.font.name,
    range.font.size,
    range.font.bold,
    range.font.italic,
    range.font.color,
    range.font.underline,
  ] as Array<string | number | boolean | null>;
  return {
    range,
    record: {
      text: range.text,
      apiSupported: true,
      formattingUniform: formatting.every((value) => value !== null && value !== undefined),
      formatting,
      identity: {
        presentationId: presentation.id,
        slideIds: slides.items.map((slide) => slide.id).sort(),
        shapeIds: shapes.items.map((shape) => shape.id).sort(),
        rangeStart: range.start,
        rangeLength: range.length,
      },
    },
  };
}

class OfficePowerPointGateway implements PowerPointGateway {
  async read(): Promise<PowerPointSelectionRecord> {
    const apiSupported = Office.context.requirements.isSetSupported("PowerPointApi", "1.5");
    if (!apiSupported) return { text: "", apiSupported, formattingUniform: false, formatting: [] };
    return PowerPoint.run(async (context) => (await readRecordInContext(context)).record);
  }

  async replace(_text: string): Promise<void> {
    // A write without a same-batch selection check is unsafe in the real Office gateway.
    throw new UserVisibleError("ต้องยืนยัน selected text range ก่อนเขียนกลับ");
  }

  async replaceIfUnchanged(expectedFingerprint: string, text: string): Promise<void> {
    if (!Office.context.requirements.isSetSupported("PowerPointApi", "1.5")) {
      throw new UserVisibleError("ต้องใช้ PowerPoint API 1.5 ขึ้นไป");
    }
    await PowerPoint.run(async (context) => {
      const { range, record } = await readRecordInContext(context);
      if (recordFingerprint(record) !== expectedFingerprint) {
        throw new UserVisibleError("Selection เปลี่ยนแล้ว กรุณาวิเคราะห์ใหม่");
      }
      const assessment = assessRecord(record);
      if (!assessment.allowed) throw new UserVisibleError(assessment.reasons.join("; "));
      range.text = text;
      await context.sync();
    });
  }
}

export class PowerPointHostAdapter implements HostAdapter {
  readonly host = "PowerPoint" as const;
  readonly canInsertResponse = false;

  constructor(private readonly gateway: PowerPointGateway = new OfficePowerPointGateway()) {}

  async readSelection(): Promise<SelectionSnapshot> {
    let record: PowerPointSelectionRecord;
    try {
      record = await this.gateway.read();
    } catch {
      // Do not surface or log the Office exception because it may contain document data.
      record = { text: "", apiSupported: true, formattingUniform: false, formatting: [], readFailure: true };
    }
    return {
      host: this.host,
      text: record.text,
      fingerprint: recordFingerprint(record),
      writeback: assessRecord(record),
    };
  }

  assessWriteback(snapshot: SelectionSnapshot): WritebackAssessment {
    return snapshot.writeback;
  }

  async applyReplacement(expected: SelectionSnapshot, replacement: ReplacementPayload): Promise<void> {
    if (typeof replacement !== "string") throw new UserVisibleError("PowerPoint รับเฉพาะข้อความสำหรับเขียนกลับ");
    if (!expected.writeback.allowed) throw new UserVisibleError(expected.writeback.reasons.join("; "));

    if (this.gateway.replaceIfUnchanged) {
      await this.gateway.replaceIfUnchanged(expected.fingerprint, replacement);
      return;
    }

    // Compatibility path for injected gateways. The production gateway always uses
    // replaceIfUnchanged, which validates and writes inside one PowerPoint.run call.
    const current = await this.readSelection();
    if (current.fingerprint !== expected.fingerprint) throw new UserVisibleError("Selection เปลี่ยนแล้ว กรุณาวิเคราะห์ใหม่");
    if (!current.writeback.allowed) throw new UserVisibleError(current.writeback.reasons.join("; "));
    await this.gateway.replace(replacement);
  }

  async insertResponse(_expected: SelectionSnapshot, _response: string): Promise<void> {
    throw new UserVisibleError("PowerPoint รุ่นแรกให้ Copy คำตอบเท่านั้น");
  }
}
