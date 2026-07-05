export function renderSettings(root) {
  const mode = localStorage.getItem("aiguard.mode") || "token";
  root.innerHTML = `
    <h2>Settings</h2>
    <div class="card">
      <b>โหมดการปกปิด</b>
      <div class="row">
        <label><input type="radio" name="mode" value="token" ${mode === "token" ? "checked" : ""}/> Token <span class="mono">[ชื่อ_1]</span> (เห็นชัดว่าปกปิดแล้ว)</label>
      </div>
      <div class="row">
        <label><input type="radio" name="mode" value="surrogate" ${mode === "surrogate" ? "checked" : ""}/> Surrogate ข้อมูลปลอมสมจริง (AI อ่านลื่น)</label>
      </div>
    </div>
    <div class="card">
      <b>ส่วนขยายเบราว์เซอร์</b>
      <p>สำหรับปกปิดในหน้าแชต ChatGPT / Claude โดยตรง ติดตั้งจาก Chrome Web Store (เร็ว ๆ นี้) หรือโหลดโฟลเดอร์ <span class="mono">extension/</span> แบบ unpacked</p>
    </div>
    <div class="card">
      <b>บริการในเครื่อง</b>
      <p>API: <span class="mono">http://127.0.0.1:8000</span> · เอกสาร: <span class="mono">/docs</span></p>
      <div class="row"><button class="primary" id="s-quit">ออกจากโปรแกรม (ปิด backend)</button></div>
    </div>
    <div class="card">
      <b>อัปเดตโปรแกรม</b>
      <p>ตรวจเวอร์ชันใหม่จาก GitHub Releases</p>
      <div class="row"><button class="primary" id="s-check-update">ตรวจหาอัปเดต</button></div>
      <p id="s-update-status" class="muted"></p>
    </div>
  `;

  root.querySelectorAll('input[name="mode"]').forEach((el) => {
    el.addEventListener("change", () => {
      localStorage.setItem("aiguard.mode", el.value);
    });
  });

  root.querySelector("#s-quit").addEventListener("click", () => {
    window.__TAURI__.core.invoke("quit_app");
  });

  const checkBtn = root.querySelector("#s-check-update");
  const status = root.querySelector("#s-update-status");
  if (checkBtn) {
    checkBtn.addEventListener("click", async () => {
      if (!window.__TAURI__) {
        status.textContent = "ใช้ได้เฉพาะในแอปเดสก์ท็อป";
        return;
      }
      status.textContent = "กำลังตรวจ...";
      try {
        const info = await window.__TAURI__.core.invoke("update_check");
        if (!info.available) {
          status.textContent = "เป็นเวอร์ชันล่าสุดแล้ว";
          return;
        }
        status.textContent = `มีอัปเดต ${info.version} `;
        const doBtn = document.createElement("button");
        doBtn.className = "primary";
        doBtn.textContent = "อัปเดตเลย";
        status.appendChild(doBtn);
        if (info.notes) {
          const notes = document.createElement("div");
          notes.className = "mono";
          notes.textContent = info.notes;
          status.appendChild(notes);
        }
        doBtn.addEventListener("click", async () => {
          status.textContent = "กำลังดาวน์โหลดและติดตั้ง...";
          try {
            await window.__TAURI__.core.invoke("update_install");
          } catch (e) {
            status.textContent = "อัปเดตไม่สำเร็จ " + e;
          }
        });
      } catch (e) {
        status.textContent = "ตรวจอัปเดตไม่สำเร็จ " + e;
      }
    });
  }
}
