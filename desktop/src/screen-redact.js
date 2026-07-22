import { redactPdf } from "./api.js";
import { screenHeader, escapeHtml } from "./ui.js";

// Only display the detector's declared type.  The response objects may also
// grow fields that contain source values, spans, or other sensitive metadata;
// those must never be copied into the desktop DOM.
const DISPLAYABLE_FIELD_TYPES = new Set([
  "ADDRESS",
  "BANK_ACCOUNT",
  "CREDIT_CARD",
  "DATE",
  "DATE_OF_BIRTH",
  "EMAIL",
  "IBAN",
  "ID_NUMBER",
  "LOCATION",
  "MEDICAL_ID",
  "NAME",
  "ORGANIZATION",
  "PASSPORT",
  "PHONE",
  "POSTAL_CODE",
  "STUDENT_ID",
  "SURNAME",
  "THAI_ID",
  "VEHICLE_PLATE",
]);

function renderFieldChips(container, fields) {
  container.replaceChildren();
  if (!Array.isArray(fields)) return;

  const seen = new Set();
  for (const field of fields) {
    if (!field || typeof field !== "object" || Array.isArray(field)) continue;
    const dataType = field.data_type;
    if (typeof dataType !== "string" || !DISPLAYABLE_FIELD_TYPES.has(dataType)) continue;
    if (seen.has(dataType)) continue;
    seen.add(dataType);

    const chip = document.createElement("span");
    chip.className = "chip chip--redact";
    chip.textContent = dataType;
    container.appendChild(chip);
  }
}

function b64ToBlob(b64, type) {
  const bytes = atob(b64);
  const arr = new Uint8Array(bytes.length);
  for (let i = 0; i < bytes.length; i++) arr[i] = bytes.charCodeAt(i);
  return new Blob([arr], { type });
}

export function renderRedact(root) {
  root.innerHTML = `
    ${screenHeader("Redact PDF", "อัปโหลด PDF เพื่อดำกล่องทับข้อมูลส่วนบุคคล (ประมวลผลในเครื่องทั้งหมด)")}
    <div class="dropzone" id="r-drop" tabindex="0" role="button">
      <svg class="dropzone__icon" width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
        <path d="M6 2h9l3 3v17a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1z" />
        <path d="M15 2v3h3" />
      </svg>
      <span>วางไฟล์ PDF ที่นี่ หรือคลิกเลือกไฟล์</span>
      <input type="file" id="r-file" accept="application/pdf" class="hidden" />
    </div>
    <div class="row hidden" id="r-processing">
      <div class="spinner" style="width:18px;height:18px;border-width:2px;"></div>
      <span id="r-filename"></span>
      <span class="muted">กำลังตรวจและปกปิด...</span>
    </div>
    <div class="banner banner--err hidden" id="r-err"></div>
    <div class="card hidden" id="r-out">
      <div class="previews">
        <div class="preview">
          <div class="preview__label before"><span class="tick"></span>ก่อน</div>
          <img id="r-before" alt="before" />
        </div>
        <div class="preview">
          <div class="preview__label after"><span class="tick"></span>หลัง</div>
          <img id="r-after" alt="after" />
        </div>
      </div>
      <div class="row">
        <dl class="dl">
          <dt>ชนิดไฟล์</dt><dd id="r-source-type"></dd>
          <dt>PII ที่พบ</dt><dd id="r-entity-count"></dd>
          <dt>ความมั่นใจ OCR</dt><dd id="r-ocr-confidence"></dd>
        </dl>
      </div>
      <div class="row" id="r-fields"></div>
      <div class="banner banner--warn hidden" id="r-human-review">ควรตรวจซ้ำด้วยตนเอง (ความมั่นใจ OCR ต่ำ)</div>
      <div class="row"><button class="btn btn--primary" id="r-download">ดาวน์โหลด PDF ที่ปกปิดแล้ว</button></div>
    </div>
  `;

  const $ = (id) => root.querySelector(id);
  let redactedB64 = null;
  let outName = "redacted.pdf";

  async function handleFile(file) {
    if (!file) return;
    $("#r-err").classList.add("hidden");
    $("#r-out").classList.add("hidden");
    $("#r-filename").textContent = file.name;
    $("#r-processing").classList.remove("hidden");
    try {
      const res = await redactPdf(file);
      redactedB64 = res.redacted_pdf_b64;
      outName = "redacted-" + (res.filename || file.name);
      $("#r-source-type").textContent = res.source_type;
      $("#r-entity-count").textContent = res.entity_count;
      $("#r-ocr-confidence").textContent =
        res.ocr_confidence != null ? res.ocr_confidence : "-";
      $("#r-before").src = "data:image/png;base64," + res.before_png_b64;
      $("#r-after").src = "data:image/png;base64," + res.after_png_b64;
      renderFieldChips($("#r-fields"), res.fields);
      $("#r-human-review").classList.toggle("hidden", !res.human_review);
      $("#r-out").classList.remove("hidden");
    } catch (e) {
      $("#r-err").textContent = "ปกปิด PDF ไม่สำเร็จ: " + escapeHtml(e.message);
      $("#r-err").classList.remove("hidden");
    } finally {
      $("#r-processing").classList.add("hidden");
    }
  }

  const drop = $("#r-drop");
  const fileInput = $("#r-file");

  drop.addEventListener("click", () => fileInput.click());
  drop.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      fileInput.click();
    }
  });
  fileInput.addEventListener("change", () => {
    const file = fileInput.files[0];
    handleFile(file);
    fileInput.value = "";
  });

  drop.addEventListener("dragover", (e) => {
    e.preventDefault();
    drop.classList.add("is-drag");
  });
  drop.addEventListener("dragleave", () => {
    drop.classList.remove("is-drag");
  });
  drop.addEventListener("drop", (e) => {
    e.preventDefault();
    drop.classList.remove("is-drag");
    const file = e.dataTransfer.files[0];
    handleFile(file);
  });

  $("#r-download").addEventListener("click", () => {
    if (!redactedB64) return;
    const url = URL.createObjectURL(b64ToBlob(redactedB64, "application/pdf"));
    const a = document.createElement("a");
    a.href = url;
    a.download = outName;
    a.click();
    URL.revokeObjectURL(url);
  });
}
