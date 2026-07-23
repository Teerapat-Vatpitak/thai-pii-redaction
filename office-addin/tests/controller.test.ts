import { describe, expect, it, vi } from "vitest";
import { ApiError, type AIGuardApi } from "../src/api";
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
    health: vi.fn().mockResolvedValue({ status: "ok", version: "2.4.0" }),
    detect: vi.fn().mockResolvedValue({ entities: [], entity_type_counts: {} }),
    analyze: vi.fn().mockResolvedValue({ overall_score: 0, overall_grade: "A", risk_label: "ต่ำ", direct_pii_count: 0, recommendations: [] }),
    sanitize: vi.fn().mockResolvedValue({ session_id: "memory-only", sanitized_text: "[NAME_1]", entities: [], entity_type_counts: {}, warnings: [] }),
    reidentify: vi.fn().mockResolvedValue({ restored_text: "fixture selection", replaced_count: 1, leftover_tokens: [], warnings: [] }),
    roundtrip: vi.fn().mockResolvedValue({ sanitized_text: "[NAME_1]", ai_response_masked: "reply [NAME_1]", restored_text: "reply fixture", entity_type_counts: {}, provider_used: "pathumma", warnings: [] }),
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

  it("preserves selection boundary whitespace across mask writeback", async () => {
    const adapter = new FakeAdapter();
    adapter.text = "  นายสมชาย  ";
    const sanitize = vi.fn().mockResolvedValue({
      session_id: "memory-only",
      sanitized_text: "[NAME_1]",
      entities: [],
      entity_type_counts: {},
      warnings: [],
    });
    const controller = new TaskController(api({ sanitize }), adapter, vi.fn());

    await controller.previewMask();
    expect(sanitize).toHaveBeenCalledWith("นายสมชาย", "token", undefined);
    expect(controller.viewState.output).toBe("  [NAME_1]  ");
    await controller.apply();
    expect(adapter.applied).toBe("  [NAME_1]  ");
  });

  it("discards a completed API action if selection changed", async () => {
    let resolve!: (value: Awaited<ReturnType<AIGuardApi["sanitize"]>>) => void;
    const pending = new Promise<Awaited<ReturnType<AIGuardApi["sanitize"]>>>((done) => { resolve = done; });
    const adapter = new FakeAdapter();
    const controller = new TaskController(api({ sanitize: vi.fn().mockReturnValue(pending) }), adapter, vi.fn());
    const action = controller.previewMask();
    adapter.text = "changed selection";
    resolve({ session_id: "memory-only", sanitized_text: "[NAME_1]", entities: [], entity_type_counts: {}, warnings: [] });
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
    resolve({ session_id: "stale-session", sanitized_text: "[NAME_1]", entities: [], entity_type_counts: {}, warnings: [] });
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

  it("surfaces leftover-token warnings", async () => {
    const adapter = new FakeAdapter();
    const service = api({ reidentify: vi.fn().mockResolvedValue({ restored_text: "partial", replaced_count: 0, leftover_tokens: ["token"], warnings: [] }) });
    const controller = new TaskController(service, adapter, vi.fn());
    await controller.previewMask();
    await controller.apply();
    await controller.previewRestore();
    expect(controller.viewState.warnings.join(" ")).toContain("คืนค่าไม่ได้");
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
