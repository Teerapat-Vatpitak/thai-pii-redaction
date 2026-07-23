export type HostName = "Word" | "Excel" | "PowerPoint";
export type GuardMode = "token" | "surrogate";
export type TaskPhase = "idle" | "preview" | "applying" | "asking" | "result" | "error";

export interface WritebackAssessment {
  allowed: boolean;
  reasons: string[];
}

export interface ExcelSelectionData {
  address: string;
  values: unknown[][];
  formulas: unknown[][];
  displayText: string[][];
}

export interface SelectionSnapshot {
  host: HostName;
  text: string;
  fingerprint: string;
  writeback: WritebackAssessment;
  excel?: ExcelSelectionData;
}

export interface ExcelReplacement {
  kind: "excel-cells";
  values: unknown[][];
  changedCells: Array<{ row: number; column: number }>;
  skipped: string[];
}

export type ReplacementPayload = string | ExcelReplacement;

export interface HostAdapter {
  readonly host: HostName;
  readonly canInsertResponse: boolean;
  readSelection(): Promise<SelectionSnapshot>;
  assessWriteback(snapshot: SelectionSnapshot): WritebackAssessment;
  applyReplacement(expected: SelectionSnapshot, replacement: ReplacementPayload): Promise<void>;
  insertResponse(expected: SelectionSnapshot, response: string): Promise<void>;
}

export interface MaskPreviewProvider {
  buildMaskPreview(
    snapshot: SelectionSnapshot,
    sanitize: (text: string) => Promise<string>,
  ): Promise<ExcelReplacement>;
}

export interface RestorePreviewProvider {
  buildRestorePreview(
    snapshot: SelectionSnapshot,
    restore: (text: string) => Promise<string>,
  ): Promise<ExcelReplacement>;
}

export function isMaskPreviewProvider(adapter: HostAdapter): adapter is HostAdapter & MaskPreviewProvider {
  return "buildMaskPreview" in adapter && typeof adapter.buildMaskPreview === "function";
}

export function isRestorePreviewProvider(adapter: HostAdapter): adapter is HostAdapter & RestorePreviewProvider {
  return "buildRestorePreview" in adapter && typeof adapter.buildRestorePreview === "function";
}

export function matrixEquals(left: unknown[][], right: unknown[][]): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

export function fingerprint(parts: unknown[]): string {
  const value = JSON.stringify(parts);
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0).toString(16).padStart(8, "0");
}
