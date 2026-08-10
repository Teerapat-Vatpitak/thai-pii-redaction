const SAFE_MESSAGES = new Map([
  ["broker_busy", "บริการกำลังทำงานอยู่ กรุณาลองใหม่ด้วยตนเอง"],
  ["broker_incompatible", "รุ่นของบริการไม่เข้ากัน กรุณาอัปเดตหรือเปิดแอปใหม่"],
  ["broker_unauthorized", "แอปเชื่อมต่อบริการความปลอดภัยไม่ได้ กรุณาเปิดแอปใหม่"],
  ["broker_unavailable", "บริการความปลอดภัยยังไม่พร้อม กรุณาปิดแล้วเปิดแอปใหม่"],
  ["operation_timeout", "หมดเวลาทำงานอย่างปลอดภัย กรุณาเริ่มขั้นตอนใหม่"],
  ["session_unavailable", "เซสชันนี้ใช้ต่อไม่ได้ กรุณาเริ่มขั้นตอนใหม่"],
  ["payload_too_large", "ข้อมูลมีขนาดใหญ่เกินขีดจำกัด"],
  ["document_invalid", "ไฟล์เอกสารไม่ถูกต้องหรือไม่รองรับ"],
  ["residual_pii", "ผลลัพธ์ไม่ผ่านการตรวจความปลอดภัย"],
  ["provider_configuration", "ยังไม่ได้ตั้งค่าผู้ให้บริการ AI"],
  ["provider_unavailable", "ผู้ให้บริการ AI ไม่พร้อมใช้งาน"],
  ["provider_rejected", "ผู้ให้บริการ AI ปฏิเสธคำขอ"],
  ["provider_response_invalid", "คำตอบจากผู้ให้บริการ AI ไม่ปลอดภัย"],
  ["ner_unavailable", "ตัวตรวจจับที่เลือกไม่พร้อมใช้งาน"],
  ["ner_incomplete", "การตรวจจับไม่สมบูรณ์ จึงยกเลิกอย่างปลอดภัย"],
  ["ocr_unavailable", "ระบบอ่าน PDF ไม่พร้อมใช้งาน"],
  ["dependency_unavailable", "ส่วนประกอบที่จำเป็นไม่พร้อมใช้งาน"],
  ["restore_failed", "คืนค่าไม่สำเร็จอย่างปลอดภัย กรุณาเริ่มขั้นตอนใหม่"],
  ["request_invalid", "ข้อมูลคำขอไม่ถูกต้อง"],
  ["operation_failed", "การทำงานล้มเหลวอย่างปลอดภัย กรุณาเริ่มขั้นตอนใหม่"],
]);

const SAFE_CODES = new Set(SAFE_MESSAGES.keys());

export class ApiError extends Error {
  constructor(
    code,
    { sessionInvalidated = false, restartRequired = false } = {}
  ) {
    const safeCode = SAFE_CODES.has(code) ? code : "operation_failed";
    super(SAFE_MESSAGES.get(safeCode));
    this.name = "ApiError";
    this.code = safeCode;
    this.status = 0;
    this.sessionInvalidated = sessionInvalidated === true;
    this.restartRequired = restartRequired === true;
  }
}

export function safeErrorMessage(error) {
  return error instanceof ApiError
    ? error.message
    : SAFE_MESSAGES.get("operation_failed");
}
