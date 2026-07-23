import { ApiError, type AIGuardApi } from "./api";
import { UserVisibleError } from "./errors";
import type { HostAdapter, GuardMode, ReplacementPayload, SelectionSnapshot, TaskPhase } from "./types";
import { isMaskPreviewProvider, isRestorePreviewProvider } from "./types";

export interface TaskViewState {
  phase: TaskPhase;
  summary: string;
  output: string;
  warnings: string[];
  canApply: boolean;
  canCopy: boolean;
  canInsert: boolean;
}

interface PendingWrite {
  selection: SelectionSnapshot;
  replacement: ReplacementPayload;
  kind: "mask" | "restore";
}

interface PendingInsert {
  selection: SelectionSnapshot;
  response: string;
}

function splitBoundaryWhitespace(text: string): { leading: string; core: string; trailing: string } {
  const leading = text.match(/^\s*/u)?.[0] ?? "";
  const withoutLeading = text.slice(leading.length);
  const trailing = withoutLeading.match(/\s*$/u)?.[0] ?? "";
  return {
    leading,
    core: withoutLeading.slice(0, withoutLeading.length - trailing.length),
    trailing,
  };
}

export class StaleSelectionError extends UserVisibleError {
  constructor() {
    super("Selection เปลี่ยนระหว่างทำงาน ผลลัพธ์ถูกยกเลิก กรุณาวิเคราะห์ใหม่");
    this.name = "StaleSelectionError";
  }
}

const INITIAL_STATE: TaskViewState = {
  phase: "idle",
  summary: "เลือกข้อความในเอกสารเพื่อเริ่มใช้งาน",
  output: "",
  warnings: [],
  canApply: false,
  canCopy: false,
  canInsert: false,
};

export class TaskController {
  private state: TaskViewState = { ...INITIAL_STATE };
  private mode: GuardMode = "token";
  private sessionId?: string;
  private pendingWrite?: PendingWrite;
  private pendingInsert?: PendingInsert;
  private operation = 0;

  constructor(
    private readonly api: AIGuardApi,
    private readonly adapter: HostAdapter,
    private readonly update: (state: TaskViewState) => void,
  ) {}

  get viewState(): TaskViewState {
    return this.state;
  }

  setMode(mode: GuardMode): void {
    if (this.mode === mode) return;
    this.mode = mode;
    this.sessionId = undefined;
    this.invalidate("เปลี่ยนรูปแบบแล้ว กรุณา Preview ใหม่");
  }

  async detect(): Promise<void> {
    await this.runPreview("กำลังตรวจ PII…", async (selection) => {
      const result = await this.api.detect(selection.text);
      const rows = Object.entries(result.entity_type_counts).map(([type, count]) => `${type}: ${count}`);
      return {
        summary: `พบ ${result.entities.length} รายการ`,
        output: rows.join("\n") || "ไม่พบ PII",
        warnings: selection.writeback.reasons,
      };
    });
  }

  async analyze(): Promise<void> {
    await this.runPreview("กำลังวิเคราะห์ PDPA…", async (selection) => {
      const result = await this.api.analyze(selection.text);
      return {
        summary: `ความเสี่ยง ${result.risk_label} · ${result.overall_score}/100 (${result.overall_grade})`,
        output: [`PII โดยตรง: ${result.direct_pii_count}`, ...result.recommendations].join("\n"),
        warnings: selection.writeback.reasons,
      };
    });
  }

  async previewMask(): Promise<void> {
    const token = ++this.operation;
    const mode = this.mode;
    let nextSessionId = this.sessionId;
    this.pendingWrite = undefined;
    this.pendingInsert = undefined;
    this.emit({ phase: "preview", summary: "กำลังสร้าง Mask Preview…", output: "", warnings: [], canApply: false, canCopy: false, canInsert: false });
    try {
      const selection = await this.readNonEmptySelection();
      const warnings = [...selection.writeback.reasons];
      const sanitizePreservingBoundary = async (text: string): Promise<string> => {
        const { leading, core, trailing } = splitBoundaryWhitespace(text);
        const result = await this.api.sanitize(core, mode, nextSessionId);
        nextSessionId = result.session_id;
        warnings.push(...result.warnings);
        return `${leading}${result.sanitized_text}${trailing}`;
      };
      let replacement: ReplacementPayload;
      if (isMaskPreviewProvider(this.adapter)) {
        replacement = await this.adapter.buildMaskPreview(selection, sanitizePreservingBoundary);
        warnings.push(...replacement.skipped);
      } else {
        replacement = await sanitizePreservingBoundary(selection.text);
      }
      await this.assertStillCurrent(token, selection);
      this.sessionId = nextSessionId;
      this.pendingWrite = { selection, replacement, kind: "mask" };
      const output = typeof replacement === "string"
        ? replacement
        : replacement.values.map((row) => row.join("\t")).join("\n");
      this.emit({
        phase: "preview",
        summary: selection.writeback.allowed ? "ตรวจ Preview แล้ว กด Apply เพื่อเขียนกลับ" : "Preview/Copy เท่านั้น",
        output,
        warnings,
        canApply: selection.writeback.allowed,
        canCopy: true,
        canInsert: false,
      });
    } catch (error) {
      this.fail(error, token);
    }
  }

  async previewRestore(): Promise<void> {
    const sessionId = this.sessionId;
    if (!sessionId) {
      this.fail(new ApiError(404, "ไม่มี session สำหรับ Restore กรุณา Mask ใน task pane นี้ก่อน", "expired"), ++this.operation);
      return;
    }
    const token = ++this.operation;
    this.pendingWrite = undefined;
    this.pendingInsert = undefined;
    this.emit({ phase: "preview", summary: "กำลังตรวจ Restore Preview…", output: "", warnings: [], canApply: false, canCopy: false, canInsert: false });
    try {
      const selection = await this.readNonEmptySelection();
      let replacement: ReplacementPayload;
      let replacedCount = 0;
      const warnings = [...selection.writeback.reasons];
      if (isRestorePreviewProvider(this.adapter)) {
        replacement = await this.adapter.buildRestorePreview(selection, async (text) => {
          const result = await this.api.reidentify(sessionId, text);
          replacedCount += result.replaced_count;
          warnings.push(...result.warnings);
          if (result.leftover_tokens.length > 0) warnings.push(`ยังมี token ที่คืนค่าไม่ได้ ${result.leftover_tokens.length} รายการ`);
          return result.restored_text;
        });
        warnings.push(...replacement.skipped);
      } else {
        const result = await this.api.reidentify(sessionId, selection.text);
        replacement = result.restored_text;
        replacedCount = result.replaced_count;
        warnings.push(...result.warnings);
        if (result.leftover_tokens.length > 0) warnings.push(`ยังมี token ที่คืนค่าไม่ได้ ${result.leftover_tokens.length} รายการ`);
      }
      await this.assertStillCurrent(token, selection);
      this.pendingWrite = { selection, replacement, kind: "restore" };
      const output = typeof replacement === "string"
        ? replacement
        : replacement.values.map((row) => row.join("\t")).join("\n");
      this.emit({
        phase: "preview",
        summary: selection.writeback.allowed ? `พร้อม Restore ${replacedCount} รายการ` : "Restore Preview/Copy เท่านั้น",
        output,
        warnings,
        canApply: selection.writeback.allowed,
        canCopy: true,
        canInsert: false,
      });
    } catch (error) {
      if (error instanceof ApiError && error.code === "expired") this.sessionId = undefined;
      this.fail(error, token);
    }
  }

  async apply(): Promise<void> {
    const pending = this.pendingWrite;
    if (!pending) return;
    const token = ++this.operation;
    this.emit({ ...this.state, phase: "applying", summary: "กำลังตรวจ selection และเขียนกลับ…", canApply: false, canInsert: false });
    try {
      await this.adapter.applyReplacement(pending.selection, pending.replacement);
      if (token !== this.operation) return;
      this.pendingWrite = undefined;
      this.emit({ ...this.state, phase: "result", summary: pending.kind === "mask" ? "Mask สำเร็จ" : "Restore สำเร็จ", canApply: false });
    } catch (error) {
      this.fail(error, token);
    }
  }

  async askPathumma(instruction: string): Promise<void> {
    const token = ++this.operation;
    const mode = this.mode;
    this.pendingWrite = undefined;
    this.pendingInsert = undefined;
    this.emit({ phase: "asking", summary: "กำลังส่งข้อความที่ปกปิดแล้วไป Pathumma…", output: "", warnings: [], canApply: false, canCopy: false, canInsert: false });
    try {
      const selection = await this.readNonEmptySelection();
      const requestText = instruction.trim() ? `${instruction.trim()}\n\n${selection.text}` : selection.text;
      const result = await this.api.roundtrip(requestText, mode);
      await this.assertStillCurrent(token, selection);
      this.pendingInsert = { selection, response: result.restored_text };
      const warnings = [...selection.writeback.reasons, ...result.warnings];
      this.emit({
        phase: "result",
        summary: `Pathumma ตอบสำเร็จ · outbound ถูกปกปิดแล้ว`,
        output: `ข้อความที่ส่งออก (masked)\n${result.sanitized_text}\n\nคำตอบที่คืนค่าแล้ว\n${result.restored_text}`,
        warnings,
        canApply: false,
        canCopy: true,
        canInsert: this.adapter.canInsertResponse,
      });
    } catch (error) {
      this.fail(error, token);
    }
  }

  async insertResponse(): Promise<void> {
    const pending = this.pendingInsert;
    if (!pending || !this.adapter.canInsertResponse) return;
    const token = ++this.operation;
    this.emit({ ...this.state, phase: "applying", summary: "กำลังแทรกคำตอบหลัง selection…", canInsert: false });
    try {
      await this.adapter.insertResponse(pending.selection, pending.response);
      if (token !== this.operation) return;
      this.pendingInsert = undefined;
      this.emit({ ...this.state, phase: "result", summary: "แทรกคำตอบแล้ว", canInsert: false });
    } catch (error) {
      this.fail(error, token);
    }
  }

  private async runPreview(
    loading: string,
    action: (selection: SelectionSnapshot) => Promise<{ summary: string; output: string; warnings: string[] }>,
  ): Promise<void> {
    const token = ++this.operation;
    this.pendingWrite = undefined;
    this.pendingInsert = undefined;
    this.emit({ phase: "preview", summary: loading, output: "", warnings: [], canApply: false, canCopy: false, canInsert: false });
    try {
      const selection = await this.readNonEmptySelection();
      const result = await action(selection);
      await this.assertStillCurrent(token, selection);
      this.emit({ phase: "result", ...result, canApply: false, canCopy: Boolean(result.output), canInsert: false });
    } catch (error) {
      this.fail(error, token);
    }
  }

  private async readNonEmptySelection(): Promise<SelectionSnapshot> {
    const selection = await this.adapter.readSelection();
    if (!selection.text.trim()) throw new UserVisibleError("กรุณาเลือกข้อความก่อนใช้งาน");
    return selection;
  }

  private async assertStillCurrent(token: number, expected: SelectionSnapshot): Promise<void> {
    if (token !== this.operation) throw new StaleSelectionError();
    const current = await this.adapter.readSelection();
    if (token !== this.operation || current.fingerprint !== expected.fingerprint) throw new StaleSelectionError();
  }

  private invalidate(summary: string): void {
    this.operation += 1;
    this.pendingWrite = undefined;
    this.pendingInsert = undefined;
    this.emit({ ...INITIAL_STATE, summary });
  }

  private fail(error: unknown, token: number): void {
    if (token !== this.operation) return;
    const message = error instanceof ApiError || error instanceof UserVisibleError
      ? error.message
      : "การทำงานล้มเหลวโดยไม่เปลี่ยนเอกสาร กรุณาตรวจ selection และลองใหม่";
    this.pendingWrite = undefined;
    this.pendingInsert = undefined;
    this.emit({ phase: "error", summary: message, output: "", warnings: [], canApply: false, canCopy: false, canInsert: false });
  }

  private emit(next: TaskViewState): void {
    this.state = next;
    this.update(next);
  }
}
