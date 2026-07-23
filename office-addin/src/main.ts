import { ApiClient, ApiError, type HealthResponse } from "./api";
import { ExcelHostAdapter } from "./adapters/excel";
import { PowerPointHostAdapter } from "./adapters/powerpoint";
import { WordHostAdapter } from "./adapters/word";
import { TaskController, type TaskViewState } from "./controller";
import { evaluateBackendHealth } from "./health";
import type { GuardMode, HostAdapter } from "./types";

const actionButtons = Array.from(document.querySelectorAll<HTMLButtonElement>("button[data-action]"));
const banner = document.querySelector<HTMLElement>("#backend-banner")!;
const hostNote = document.querySelector<HTMLElement>("#host-note")!;
const summary = document.querySelector<HTMLElement>("#summary")!;
const output = document.querySelector<HTMLElement>("#output")!;
const warnings = document.querySelector<HTMLUListElement>("#warnings")!;
const statePill = document.querySelector<HTMLElement>("#state-pill")!;
const modeSelect = document.querySelector<HTMLSelectElement>("#mode")!;
const prompt = document.querySelector<HTMLTextAreaElement>("#prompt")!;

let controller: TaskController | undefined;
let backendReady = false;

function button(action: string): HTMLButtonElement {
  return document.querySelector<HTMLButtonElement>(`button[data-action="${action}"]`)!;
}

function render(state: TaskViewState): void {
  summary.textContent = state.summary;
  output.textContent = state.output;
  statePill.textContent = state.phase;
  warnings.replaceChildren(...state.warnings.map((warning) => {
    const item = document.createElement("li");
    item.textContent = warning;
    return item;
  }));
  button("apply").hidden = !state.canApply;
  button("copy").disabled = !state.canCopy;
  button("insert").hidden = !state.canInsert;
  const busy = state.phase === "applying" || state.phase === "asking";
  modeSelect.disabled = !backendReady || busy;
  for (const candidate of actionButtons) {
    if (!["copy", "apply", "insert"].includes(candidate.dataset.action ?? "")) candidate.disabled = !backendReady || busy;
  }
}

function adapterFor(host: Office.HostType): HostAdapter | undefined {
  if (host === Office.HostType.Word) return new WordHostAdapter();
  if (host === Office.HostType.Excel) return new ExcelHostAdapter();
  if (host === Office.HostType.PowerPoint) return new PowerPointHostAdapter();
  return undefined;
}

function bindActions(instance: TaskController): void {
  button("detect").addEventListener("click", () => void instance.detect());
  button("analyze").addEventListener("click", () => void instance.analyze());
  button("mask").addEventListener("click", () => void instance.previewMask());
  button("restore").addEventListener("click", () => void instance.previewRestore());
  button("apply").addEventListener("click", () => void instance.apply());
  button("ask").addEventListener("click", () => void instance.askPathumma(prompt.value));
  button("insert").addEventListener("click", () => void instance.insertResponse());
  button("copy").addEventListener("click", () => void navigator.clipboard.writeText(output.textContent ?? ""));
  modeSelect.addEventListener("change", () => instance.setMode(modeSelect.value as GuardMode));
}

Office.onReady(async (info) => {
  const adapter = adapterFor(info.host);
  if (!adapter) {
    banner.className = "banner error";
    banner.textContent = "Host นี้ยังไม่รองรับ AI Guard";
    return;
  }

  hostNote.textContent = adapter.host === "Word"
    ? "เขียนกลับได้เมื่อเลือกหนึ่งย่อหน้า รูปแบบเดียว และไม่อยู่ในตาราง"
    : adapter.host === "Excel"
      ? "แก้เฉพาะ text cells; สูตร ตัวเลข และวันที่จะถูกข้าม"
      : "ต้องเลือก text range และใช้ PowerPoint API 1.5; Ask AI เป็น Copy-only";

  const api = new ApiClient();
  controller = new TaskController(api, adapter, render);
  bindActions(controller);
  let health: HealthResponse;
  try {
    health = await api.health();
  } catch (error) {
    backendReady = false;
    banner.className = "banner error";
    banner.textContent = error instanceof ApiError
      ? error.message
      : "เกิดข้อผิดพลาดในการเริ่มต้น AI Guard กรุณาเปิด task pane ใหม่";
    render(controller.viewState);
    return;
  }

  const availability = evaluateBackendHealth(health);
  backendReady = availability.ready;
  banner.className = availability.ready ? "banner ok" : "banner error";
  banner.textContent = availability.message;
  render(controller.viewState);
});
