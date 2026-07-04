import { sanitize, reidentify } from "./api.js";

export function renderText(root) {
  const mode = localStorage.getItem("aiguard.mode") || "token";
  root.innerHTML = `
    <h2>Mask / Restore</h2>
    <p>วางข้อความที่มีข้อมูลส่วนบุคคล กด Mask เพื่อแทนด้วยโทเคน แล้วคัดลอกไปใช้กับ AI ภายนอก</p>
    <textarea id="t-input" placeholder="พิมพ์หรือวางข้อความที่นี่..."></textarea>
    <div class="row">
      <button class="primary" id="t-mask">Mask PII</button>
      <span>โหมด: <b id="t-mode">${mode}</b> (เปลี่ยนได้ที่ Settings)</span>
    </div>
    <div class="card hidden" id="t-out">
      <div class="row"><b>ผลลัพธ์ที่ปกปิดแล้ว</b> <button class="primary" id="t-copy">Copy</button></div>
      <div class="mono" id="t-masked"></div>
      <p id="t-count"></p>
      <hr />
      <p>วางคำตอบจาก AI (ที่ยังมีโทเคน) เพื่อคืนค่าจริง:</p>
      <textarea id="t-reply" placeholder="วางคำตอบจาก AI ที่นี่..."></textarea>
      <div class="row"><button class="primary" id="t-restore">Restore PII</button></div>
      <div class="mono hidden" id="t-restored"></div>
      <p class="err hidden" id="t-leftover"></p>
    </div>
    <p class="err hidden" id="t-err"></p>
  `;

  let sessionId = null;
  const $ = (id) => root.querySelector(id);

  $("#t-mask").addEventListener("click", async () => {
    $("#t-mask").disabled = true;
    const text = $("#t-input").value.trim();
    if (!text) {
      $("#t-mask").disabled = false;
      return;
    }
    $("#t-err").classList.add("hidden");
    try {
      const res = await sanitize(text, mode);
      sessionId = res.session_id;
      $("#t-masked").textContent = res.sanitized_text;
      $("#t-count").textContent = `ปกปิด ${res.entities.length} รายการ`;
      $("#t-out").classList.remove("hidden");
    } catch (e) {
      $("#t-err").textContent = "ปกปิดไม่สำเร็จ: " + e.message;
      $("#t-err").classList.remove("hidden");
    } finally {
      $("#t-mask").disabled = false;
    }
  });

  $("#t-copy").addEventListener("click", () => {
    navigator.clipboard.writeText($("#t-masked").textContent);
  });

  $("#t-restore").addEventListener("click", async () => {
    if (!sessionId) return;
    const reply = $("#t-reply").value;
    try {
      const res = await reidentify(sessionId, reply);
      $("#t-restored").textContent = res.restored_text;
      $("#t-restored").classList.remove("hidden");
      if (res.leftover_tokens && res.leftover_tokens.length) {
        $("#t-leftover").textContent =
          "โทเคนที่ยังคืนค่าไม่ได้: " + res.leftover_tokens.join(", ");
        $("#t-leftover").classList.remove("hidden");
      } else {
        $("#t-leftover").classList.add("hidden");
      }
    } catch (e) {
      $("#t-err").textContent = "คืนค่าไม่สำเร็จ: " + e.message;
      $("#t-err").classList.remove("hidden");
    }
  });
}
