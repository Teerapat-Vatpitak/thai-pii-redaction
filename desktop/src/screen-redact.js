import { redactPdf } from "./api.js";

function b64ToBlob(b64, type) {
  const bytes = atob(b64);
  const arr = new Uint8Array(bytes.length);
  for (let i = 0; i < bytes.length; i++) arr[i] = bytes.charCodeAt(i);
  return new Blob([arr], { type });
}

export function renderRedact(root) {
  root.innerHTML = `
    <h2>Redact PDF</h2>
    <p>อัปโหลด PDF เพื่อดำกล่องทับข้อมูลส่วนบุคคล (ประมวลผลในเครื่องทั้งหมด)</p>
    <div class="row">
      <input type="file" id="r-file" accept="application/pdf" />
      <button class="primary" id="r-go" disabled>Redact</button>
    </div>
    <p id="r-status"></p>
    <div class="card hidden" id="r-out">
      <p id="r-summary"></p>
      <div class="previews">
        <div><b>ก่อน</b><img id="r-before" alt="before" /></div>
        <div><b>หลัง</b><img id="r-after" alt="after" /></div>
      </div>
      <div class="row"><button class="primary" id="r-download">Download Redacted PDF</button></div>
    </div>
    <p class="err hidden" id="r-err"></p>
  `;

  const $ = (id) => root.querySelector(id);
  let redactedB64 = null;
  let outName = "redacted.pdf";

  $("#r-file").addEventListener("change", () => {
    $("#r-go").disabled = !$("#r-file").files.length;
  });

  $("#r-go").addEventListener("click", async () => {
    $("#r-go").disabled = true;
    const file = $("#r-file").files[0];
    if (!file) {
      $("#r-go").disabled = false;
      return;
    }
    $("#r-err").classList.add("hidden");
    $("#r-status").textContent = "กำลังประมวลผล...";
    try {
      const res = await redactPdf(file);
      redactedB64 = res.redacted_pdf_b64;
      outName = "redacted-" + (res.filename || file.name);
      $("#r-summary").textContent =
        `ชนิดไฟล์: ${res.source_type} · พบ PII ${res.entity_count} รายการ` +
        (res.human_review ? " · ต้องตรวจซ้ำ (OCR ความมั่นใจต่ำ)" : "");
      $("#r-before").src = "data:image/png;base64," + res.before_png_b64;
      $("#r-after").src = "data:image/png;base64," + res.after_png_b64;
      $("#r-out").classList.remove("hidden");
      $("#r-status").textContent = "";
    } catch (e) {
      $("#r-status").textContent = "";
      $("#r-err").textContent = "ปกปิด PDF ไม่สำเร็จ: " + e.message;
      $("#r-err").classList.remove("hidden");
    } finally {
      $("#r-go").disabled = false;
    }
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
