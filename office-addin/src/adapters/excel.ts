import type {
  ExcelReplacement,
  ExcelSelectionData,
  HostAdapter,
  MaskPreviewProvider,
  RestorePreviewProvider,
  ReplacementPayload,
  SelectionSnapshot,
  WritebackAssessment,
} from "../types";
import { fingerprint, matrixEquals } from "../types";
import { UserVisibleError } from "../errors";

export interface ExcelGateway {
  read(): Promise<ExcelSelectionData>;
  writeCells(changes: Array<{ row: number; column: number; value: string }>): Promise<void>;
  writeCellsIfUnchanged?(
    expected: ExcelSelectionData,
    changes: Array<{ row: number; column: number; value: string }>,
  ): Promise<void>;
}

class OfficeExcelGateway implements ExcelGateway {
  async read(): Promise<ExcelSelectionData> {
    return Excel.run(async (context) => {
      const range = context.workbook.getSelectedRange();
      range.load("address,values,formulas,text");
      await context.sync();
      return {
        address: range.address,
        values: range.values as unknown[][],
        formulas: range.formulas as unknown[][],
        displayText: range.text,
      };
    });
  }

  async writeCells(changes: Array<{ row: number; column: number; value: string }>): Promise<void> {
    await Excel.run(async (context) => {
      const range = context.workbook.getSelectedRange();
      for (const change of changes) {
        range.getCell(change.row, change.column).values = [[change.value]];
      }
      await context.sync();
    });
  }

  async writeCellsIfUnchanged(
    expected: ExcelSelectionData,
    changes: Array<{ row: number; column: number; value: string }>,
  ): Promise<void> {
    await Excel.run(async (context) => {
      const range = context.workbook.getSelectedRange();
      range.load("address,values,formulas");
      await context.sync();
      const values = range.values as unknown[][];
      const formulas = range.formulas as unknown[][];
      if (range.address !== expected.address || !matrixEquals(values, expected.values) || !matrixEquals(formulas, expected.formulas)) {
        throw new UserVisibleError("ช่วงเซลล์ ค่าหรือสูตรเปลี่ยนแล้ว กรุณาวิเคราะห์ใหม่");
      }
      for (const change of changes) {
        range.getCell(change.row, change.column).values = [[change.value]];
      }
      await context.sync();
    });
  }
}

function isFormula(value: unknown): boolean {
  return typeof value === "string" && value.startsWith("=");
}

function isWritableTextCell(excel: ExcelSelectionData, row: number, column: number): boolean {
  const valuesRow = excel.values[row];
  const formulasRow = excel.formulas[row];
  if (!valuesRow || !formulasRow || column >= valuesRow.length || column >= formulasRow.length) return false;
  const value = valuesRow[column];
  return typeof value === "string" && value.trim().length > 0 && !isFormula(formulasRow[column]);
}

export class ExcelHostAdapter implements HostAdapter, MaskPreviewProvider, RestorePreviewProvider {
  readonly host = "Excel" as const;
  readonly canInsertResponse = false;

  constructor(private readonly gateway: ExcelGateway = new OfficeExcelGateway()) {}

  async readSelection(): Promise<SelectionSnapshot> {
    const excel = await this.gateway.read();
    const text = excel.displayText.map((row) => row.join("\t")).join("\n");
    const snapshot: SelectionSnapshot = {
      host: this.host,
      text,
      fingerprint: fingerprint([excel.address, excel.values, excel.formulas]),
      writeback: { allowed: false, reasons: [] },
      excel,
    };
    snapshot.writeback = this.assessWriteback(snapshot);
    return snapshot;
  }

  assessWriteback(snapshot: SelectionSnapshot): WritebackAssessment {
    const reasons: string[] = [];
    if (!snapshot.excel || !snapshot.text.trim()) reasons.push("กรุณาเลือกช่วงเซลล์ที่มีข้อความ");
    const hasText = snapshot.excel?.values.some((row, rowIndex) =>
      row.some((_value, columnIndex) => isWritableTextCell(snapshot.excel!, rowIndex, columnIndex)),
    );
    if (!hasText) reasons.push("ไม่พบ text cell ที่เขียนกลับได้");
    return { allowed: reasons.length === 0, reasons };
  }

  async buildMaskPreview(
    snapshot: SelectionSnapshot,
    sanitize: (text: string) => Promise<string>,
  ): Promise<ExcelReplacement> {
    return this.buildTextCellPreview(snapshot, sanitize);
  }

  async buildRestorePreview(
    snapshot: SelectionSnapshot,
    restore: (text: string) => Promise<string>,
  ): Promise<ExcelReplacement> {
    return this.buildTextCellPreview(snapshot, restore);
  }

  private async buildTextCellPreview(
    snapshot: SelectionSnapshot,
    transform: (text: string) => Promise<string>,
  ): Promise<ExcelReplacement> {
    if (!snapshot.excel) throw new UserVisibleError("ไม่พบข้อมูลช่วงเซลล์");
    const values = snapshot.excel.values.map((row) => [...row]);
    const changedCells: Array<{ row: number; column: number }> = [];
    const skipped: string[] = [];

    for (let row = 0; row < values.length; row += 1) {
      const sourceRow = snapshot.excel.values[row] ?? [];
      for (let column = 0; column < sourceRow.length; column += 1) {
        const value = sourceRow[column];
        if (isFormula(snapshot.excel.formulas[row]?.[column])) {
          skipped.push(`${snapshot.excel.address} r${row + 1}c${column + 1}: formula`);
          continue;
        }
        if (typeof value !== "string" || !isWritableTextCell(snapshot.excel, row, column)) {
          skipped.push(`${snapshot.excel.address} r${row + 1}c${column + 1}: number/date/blank`);
          continue;
        }
        const transformed = await transform(value);
        if (typeof transformed !== "string") throw new UserVisibleError("ผลลัพธ์รายเซลล์ต้องเป็นข้อความ");
        values[row]![column] = transformed;
        if (transformed !== value) changedCells.push({ row, column });
      }
    }
    return { kind: "excel-cells", values, changedCells, skipped };
  }

  async applyReplacement(expected: SelectionSnapshot, replacement: ReplacementPayload): Promise<void> {
    if (typeof replacement === "string") throw new UserVisibleError("Excel ต้องใช้ผลลัพธ์แบบรายเซลล์");
    if (!expected.excel) throw new UserVisibleError("ไม่พบข้อมูลช่วงเซลล์เดิม");
    if (!expected.writeback.allowed) throw new UserVisibleError("ช่วงเซลล์นี้เป็น Preview/Copy เท่านั้น");
    const current = await this.readSelection();
    if (!current.excel || current.fingerprint !== expected.fingerprint || current.excel.address !== expected.excel.address) {
      throw new UserVisibleError("ช่วงเซลล์หรือค่าถูกเปลี่ยนแล้ว กรุณาวิเคราะห์ใหม่");
    }
    if (!matrixEquals(current.excel.formulas, expected.excel.formulas) || !matrixEquals(current.excel.values, expected.excel.values)) {
      throw new UserVisibleError("ค่าหรือสูตรเปลี่ยนแล้ว กรุณาวิเคราะห์ใหม่");
    }
    const seen = new Set<string>();
    const changes = replacement.changedCells.map(({ row, column }) => {
      const key = `${row}:${column}`;
      if (!Number.isInteger(row) || !Number.isInteger(column) || row < 0 || column < 0 || seen.has(key)) {
        throw new UserVisibleError("รายการเซลล์สำหรับ Apply ไม่ถูกต้อง กรุณาวิเคราะห์ใหม่");
      }
      seen.add(key);
      if (!isWritableTextCell(expected.excel!, row, column)) {
        throw new UserVisibleError("Apply ทำได้เฉพาะ text cell เดิมที่ไม่ใช่สูตร");
      }
      const value = replacement.values[row]?.[column];
      if (typeof value !== "string" || value === expected.excel!.values[row]?.[column]) {
        throw new UserVisibleError("ค่าที่จะ Apply ไม่ถูกต้อง กรุณาวิเคราะห์ใหม่");
      }
      return { row, column, value };
    });
    if (changes.length === 0) return;
    if (this.gateway.writeCellsIfUnchanged) {
      await this.gateway.writeCellsIfUnchanged(expected.excel, changes);
    } else {
      await this.gateway.writeCells(changes);
    }
  }

  async insertResponse(_expected: SelectionSnapshot, _response: string): Promise<void> {
    throw new UserVisibleError("Excel รุ่นแรกให้ Copy คำตอบเท่านั้น");
  }
}
