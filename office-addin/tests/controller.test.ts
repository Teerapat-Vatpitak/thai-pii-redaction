import { describe, expect, it, vi } from "vitest";
import { ApiError, type AIGuardApi } from "../src/api";
import { ExcelHostAdapter, type ExcelGateway } from "../src/adapters/excel";
import { TaskController, type TaskViewState } from "../src/controller";
import type { HostAdapter, ReplacementPayload, SelectionSnapshot } from "../src/types";
import { fingerprint } from "../src/types";

class FakeAdapter implements HostAdapter {
  readonly host = "Word" as const;
  readonly canInsertResponse = true;
  text = "fixture selection";
  applied?: ReplacementPayload;
  inserted?: string;

  async readSelection(): Promise<SelectionSnapshot> {
    return {
      host: this.host,
      text: this.text,
      fingerprint: fingerprint([this.text]),
      writeback: { allowed: true, reasons: [] },
    };
  }
  assessWriteback(snapshot: SelectionSnapshot) { return snapshot.writeback; }
  async applyReplacement(expected: SelectionSnapshot, replacement: ReplacementPayload) {
    if ((await this.readSelection()).fingerprint !== expected.fingerprint) throw new Error("Selection เปลี่ยนแล้ว");
    this.applied = replacement;
    this.text = String(replacement);
  }
  async insertResponse(expected: SelectionSnapshot, response: string) {
    if ((await this.readSelection()).fingerprint !== expected.fingerprint) throw new Error("Selection เปลี่ยนแล้ว");
    this.inserted = response;
  }
}

function api(overrides: Partial<AIGuardApi> = {}): AIGuardApi {
  return {
    health: vi.fn().mockResolvedValue({
      status: "ok",
      version: "2.5.0",
      contract_version: 2,
      capabilities: { control_token_required: false, api_key_required: false },
    }),
    detect: vi.fn().mockResolvedValue({
      detected_entity_count: 0,
      entity_type_counts: {},
      highlights: [],
    }),
    analyze: vi.fn().mockResolvedValue({
      overall_score: 0,
      overall_grade: "A",
      risk_label: "Very Low Risk",
      direct_pii_count: 0,
      fp_count: 0,
      tb_count: 0,
      section26_categories: [],
      reidentification: {
        score: 0,
        grade: "A",
        quasi_identifier_categories: [],
        high_risk_combination: false,
      },
      breakdown: [],
      recommendations: [{
        level: "info",
        title: "No significant PDPA risk detected",
        desc: "ไม่พบข้อมูลส่วนบุคคลที่มีความเสี่ยงสูงในข้อความนี้",
      }],
    }),
    sanitize: vi.fn().mockResolvedValue({
      session_id: "memory-only",
      sanitized_text: "[NAME_1]",
      detected_entity_count: 1,
      replacement_count: 1,
      entity_type_counts: { NAME: 1 },
      highlights: [{ start: 0, end: 8, data_type: "NAME", redact_type: "FP" }],
      section26_categories: [],
      guard_findings: [],
      warnings: [],
      safety: { status: "pass", residual_count: 0 },
    }),
    reidentify: vi.fn().mockResolvedValue({
      restored_text: "fixture selection",
      replaced_count: 1,
      leftover_count: 0,
      warnings: [],
    }),
    roundtrip: vi.fn().mockResolvedValue({
      sanitized_text: "[NAME_1]",
      ai_response_masked: "reply [NAME_1]",
      restored_text: "reply fixture",
      detected_entity_count: 1,
      entity_type_counts: { NAME: 1 },
      provider_used: "pathumma",
      section26_categories: [],
      guard_findings: [],
      warnings: [],
      safety: { status: "pass", residual_count: 0 },
      restoration: { status: "complete", replaced_count: 1, leftover_count: 0 },
    }),
    ...overrides,
  };
}

describe("TaskController", () => {
  it("does not change the document during preview and applies only on explicit action", async () => {
    const adapter = new FakeAdapter();
    const controller = new TaskController(api(), adapter, vi.fn());
    await controller.previewMask();
    expect(adapter.applied).toBeUndefined();
    expect(controller.viewState.canApply).toBe(true);
    await controller.apply();
    expect(adapter.applied).toBe("[NAME_1]");
  });

  it("keeps Apply and Copy disabled for an empty sanitize success payload", async () => {
    const adapter = new FakeAdapter();
    const sanitize = vi.fn().mockResolvedValue({
      session_id: "memory-only",
      sanitized_text: "",
      detected_entity_count: 0,
      replacement_count: 0,
      entity_type_counts: {},
      highlights: [],
      section26_categories: [],
      guard_findings: [],
      warnings: [],
      safety: { status: "pass", residual_count: 0 },
    });
    const controller = new TaskController(api({ sanitize }), adapter, vi.fn());

    await controller.previewMask();
    expect(controller.viewState.phase).toBe("error");
    expect(controller.viewState.canApply).toBe(false);
    expect(controller.viewState.canCopy).toBe(false);
    await controller.apply();
    expect(adapter.applied).toBeUndefined();
  });

  it("preserves selection boundary whitespace across mask writeback", async () => {
    const adapter = new FakeAdapter();
    adapter.text = "  นายสมชาย  ";
    const sanitize = vi.fn().mockResolvedValue({
      session_id: "memory-only",
      sanitized_text: "[NAME_1]",
      detected_entity_count: 1,
      replacement_count: 1,
      entity_type_counts: { NAME: 1 },
      highlights: [{ start: 0, end: 8, data_type: "NAME", redact_type: "FP" }],
      section26_categories: [],
      guard_findings: [],
      warnings: [],
      safety: { status: "pass", residual_count: 0 },
    });
    const controller = new TaskController(api({ sanitize }), adapter, vi.fn());

    await controller.previewMask();
    expect(sanitize).toHaveBeenCalledWith("นายสมชาย", "token", undefined);
    expect(controller.viewState.output).toBe("  [NAME_1]  ");
    await controller.apply();
    expect(adapter.applied).toBe("  [NAME_1]  ");
  });

  it("keeps skipped Excel values out of Preview and disables Copy", async () => {
    const selection = {
      address: "Sheet1!A1:E1",
      values: [["synthetic name", 424242, "formula result", 45123, ""]],
      formulas: [["synthetic name", 424242, "=\"synthetic secret\"", 45123, ""]],
      displayText: [["synthetic name", "424242", "formula result", "1/1/2023", ""]],
    };
    const gateway: ExcelGateway = {
      read: vi.fn().mockResolvedValue(selection),
      writeCells: vi.fn(),
    };
    const controller = new TaskController(
      api(),
      new ExcelHostAdapter(gateway),
      vi.fn(),
    );

    await controller.previewMask();

    expect(controller.viewState.canCopy).toBe(false);
    expect(controller.viewState.output).toContain("[NAME_1]");
    expect(controller.viewState.output).not.toContain("424242");
    expect(controller.viewState.output).not.toContain("formula result");
    expect(controller.viewState.output).not.toContain("45123");
    expect(controller.viewState.output).not.toContain("1/1/2023");
  });

  it("discards a completed API action if selection changed", async () => {
    let resolve!: (value: Awaited<ReturnType<AIGuardApi["sanitize"]>>) => void;
    const pending = new Promise<Awaited<ReturnType<AIGuardApi["sanitize"]>>>((done) => { resolve = done; });
    const adapter = new FakeAdapter();
    const controller = new TaskController(api({ sanitize: vi.fn().mockReturnValue(pending) }), adapter, vi.fn());
    const action = controller.previewMask();
    adapter.text = "changed selection";
    resolve({
      session_id: "memory-only",
      sanitized_text: "[NAME_1]",
      detected_entity_count: 1,
      replacement_count: 1,
      entity_type_counts: { NAME: 1 },
      highlights: [{ start: 0, end: 8, data_type: "NAME", redact_type: "FP" }],
      section26_categories: [],
      guard_findings: [],
      warnings: [],
      safety: { status: "pass", residual_count: 0 },
    });
    await action;
    expect(controller.viewState.phase).toBe("error");
    expect(controller.viewState.summary).toContain("Selection เปลี่ยน");
    expect(adapter.applied).toBeUndefined();
    await controller.previewRestore();
    expect(controller.viewState.summary).toContain("ไม่มี session");
  });

  it("does not resurrect a session when mode changes during an in-flight preview", async () => {
    let resolve!: (value: Awaited<ReturnType<AIGuardApi["sanitize"]>>) => void;
    const pending = new Promise<Awaited<ReturnType<AIGuardApi["sanitize"]>>>((done) => { resolve = done; });
    const sanitize = vi.fn().mockReturnValue(pending);
    const adapter = new FakeAdapter();
    const controller = new TaskController(api({ sanitize }), adapter, vi.fn());

    const action = controller.previewMask();
    controller.setMode("surrogate");
    resolve({
      session_id: "stale-session",
      sanitized_text: "[NAME_1]",
      detected_entity_count: 1,
      replacement_count: 1,
      entity_type_counts: { NAME: 1 },
      highlights: [{ start: 0, end: 8, data_type: "NAME", redact_type: "FP" }],
      section26_categories: [],
      guard_findings: [],
      warnings: [],
      safety: { status: "pass", residual_count: 0 },
    });
    await action;

    expect(sanitize).toHaveBeenCalledWith("fixture selection", "token", undefined);
    await controller.previewRestore();
    expect(controller.viewState.summary).toContain("ไม่มี session");
  });

  it("fails clearly when a restore session expires and never applies a guess", async () => {
    const adapter = new FakeAdapter();
    const service = api({ reidentify: vi.fn().mockRejectedValue(new ApiError(404, "Session หมดอายุ", "expired")) });
    const controller = new TaskController(service, adapter, vi.fn());
    await controller.previewMask();
    await controller.apply();
    await controller.previewRestore();
    expect(controller.viewState.phase).toBe("error");
    expect(controller.viewState.summary).toContain("หมดอายุ");
    expect(adapter.applied).toBe("[NAME_1]");
  });

  it("previews count-only leftovers but disables Apply and Copy", async () => {
    const adapter = new FakeAdapter();
    const service = api({
      reidentify: vi.fn().mockResolvedValue({
        restored_text: "partial",
        replaced_count: 0,
        leftover_count: 1,
        warnings: [],
      }),
    });
    const controller = new TaskController(service, adapter, vi.fn());
    await controller.previewMask();
    await controller.apply();
    await controller.previewRestore();
    expect(controller.viewState.warnings.join(" ")).toContain("คืนค่าไม่ได้");
    expect(controller.viewState.canApply).toBe(false);
    expect(controller.viewState.canCopy).toBe(false);
    await controller.apply();
    expect(adapter.applied).toBe("[NAME_1]");
  });

  it("defensively blocks an unsafe sanitize result from Apply and Copy", async () => {
    const adapter = new FakeAdapter();
    const unsafe = {
      ...(await api().sanitize("fixture", "token")),
      safety: { status: "pass" as const, residual_count: 1 as 0 },
    };
    const controller = new TaskController(
      api({ sanitize: vi.fn().mockResolvedValue(unsafe) }),
      adapter,
      vi.fn(),
    );
    await controller.previewMask();
    expect(controller.viewState.phase).toBe("error");
    expect(controller.viewState.canApply).toBe(false);
    expect(controller.viewState.canCopy).toBe(false);
    expect(adapter.applied).toBeUndefined();
  });

  it("blocks Apply and Copy when restore reports a structured safety warning", async () => {
    const adapter = new FakeAdapter();
    const service = api({
      reidentify: vi.fn().mockResolvedValue({
        restored_text: "unsafe preview",
        replaced_count: 1,
        leftover_count: 0,
        warnings: [{ code: "generated_pii", count: 2 }],
      }),
    });
    const controller = new TaskController(service, adapter, vi.fn());
    await controller.previewMask();
    await controller.apply();
    await controller.previewRestore();
    expect(controller.viewState.warnings.join(" ")).toContain("2");
    expect(controller.viewState.canApply).toBe(false);
    expect(controller.viewState.canCopy).toBe(false);
  });

  it("keeps Pathumma response preview-only until explicit insert", async () => {
    const adapter = new FakeAdapter();
    const states: TaskViewState[] = [];
    const controller = new TaskController(api(), adapter, (state) => states.push(state));
    await controller.askPathumma("summarize");
    expect(adapter.inserted).toBeUndefined();
    expect(controller.viewState.canInsert).toBe(true);
    await controller.insertResponse();
    expect(adapter.inserted).toBe("reply fixture");
    expect(states.some((state) => state.phase === "asking")).toBe(true);
  });

  it.each([
    {
      warnings: [],
      restoration: { status: "incomplete" as const, replaced_count: 0, leftover_count: 1 },
    },
    {
      warnings: [{ code: "foreign_replacement" as const, count: 1 }],
      restoration: { status: "unsafe" as const, replaced_count: 1, leftover_count: 0 },
    },
  ])("blocks Copy and Insert for an incomplete or unsafe roundtrip", async (unsafe) => {
    const adapter = new FakeAdapter();
    const service = api({
      roundtrip: vi.fn().mockResolvedValue({
        sanitized_text: "[NAME_1]",
        ai_response_masked: "reply [NAME_1]",
        restored_text: "preview only",
        detected_entity_count: 1,
        entity_type_counts: { NAME: 1 },
        provider_used: "pathumma",
        section26_categories: [],
        guard_findings: [],
        safety: { status: "pass", residual_count: 0 },
        ...unsafe,
      }),
    });
    const controller = new TaskController(service, adapter, vi.fn());
    await controller.askPathumma("");
    expect(controller.viewState.output).toContain("preview only");
    expect(controller.viewState.canCopy).toBe(false);
    expect(controller.viewState.canInsert).toBe(false);
    await controller.insertResponse();
    expect(adapter.inserted).toBeUndefined();
  });

  it("renders the current structured analyze recommendation shape", async () => {
    const adapter = new FakeAdapter();
    const controller = new TaskController(api(), adapter, vi.fn());
    await controller.analyze();
    expect(controller.viewState.output).toContain("No significant PDPA risk detected");
    expect(controller.viewState.output).toContain("ไม่พบข้อมูลส่วนบุคคล");
  });

  it("shows missing-key and provider failures without writeback", async () => {
    const adapter = new FakeAdapter();
    const controller = new TaskController(api({ roundtrip: vi.fn().mockRejectedValue(new ApiError(503, "backend ไม่มี API key", "missing-key")) }), adapter, vi.fn());
    await controller.askPathumma("");
    expect(controller.viewState.phase).toBe("error");
    expect(controller.viewState.summary).toContain("API key");
    expect(adapter.inserted).toBeUndefined();
  });

  it("does not expose arbitrary Office exception messages", async () => {
    const adapter = new FakeAdapter();
    adapter.readSelection = vi.fn().mockRejectedValue(new Error("raw document title and selection details"));
    const controller = new TaskController(api(), adapter, vi.fn());
    await controller.detect();
    expect(controller.viewState.phase).toBe("error");
    expect(controller.viewState.summary).toContain("โดยไม่เปลี่ยนเอกสาร");
    expect(controller.viewState.summary).not.toContain("raw document");
  });
});
