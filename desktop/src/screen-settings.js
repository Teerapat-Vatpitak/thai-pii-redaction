import { screenHeader } from "./ui.js";

export function renderSettings(root) {
  const mode = localStorage.getItem("aiguard.mode") || "token";

  const cardStyle = (selected) =>
    selected ? ` style="border-color:var(--primary);background:var(--primary-soft)"` : "";

  root.innerHTML = `
    ${screenHeader("Settings", "ตั้งค่าโหมดปกปิดเริ่มต้นและจัดการโปรแกรม")}
    <div class="row" id="s-mode-cards">
      <div class="card" id="s-mode-token" data-mode="token"${cardStyle(mode === "token")}>
        <div class="row" style="margin: 0 0 var(--s2)">
          <span style="font-size:14px;font-weight:500">Token</span>
          <span class="chip chip--token">[ชื่อ_1]</span>
        </div>
        <p class="muted">เห็นชัดว่าปกปิดแล้ว เหมาะกับงานที่ต้องตรวจสอบย้อนหลัง</p>
      </div>
      <div class="card" id="s-mode-surrogate" data-mode="surrogate"${cardStyle(mode === "surrogate")}>
        <div class="row" style="margin: 0 0 var(--s2)">
          <span style="font-size:14px;font-weight:500">Surrogate</span>
          <span style="display:inline-block;width:14px;height:14px;border-radius:var(--r-sm);background:var(--surrogate)"></span>
        </div>
        <p class="muted">ข้อมูลปลอมสมจริง ให้ AI อ่านลื่นเหมือนข้อความจริง</p>
      </div>
    </div>
    <div class="card">
      <b>ส่วนขยายเบราว์เซอร์</b>
      <p class="muted">สำหรับปกปิดในหน้าแชต ChatGPT / Claude โดยตรง ติดตั้งจาก Chrome Web Store (เร็ว ๆ นี้) หรือโหลดโฟลเดอร์ <span class="mono">extension/</span> แบบ unpacked</p>
    </div>
    <div class="card">
      <b>บริการในเครื่อง</b>
      <p class="muted">API: <span class="mono">http://127.0.0.1:8000</span> · เอกสาร: <span class="mono">/docs</span></p>
      <div class="row"><button class="btn btn--danger" id="s-quit">ออกจากโปรแกรม (ปิด backend)</button></div>
    </div>
    <div class="card">
      <b>อัปเดตโปรแกรม</b>
      <p class="muted">ตรวจเวอร์ชันใหม่จาก GitHub Releases</p>
      <div class="row"><button class="btn btn--primary" id="s-check-update">ตรวจหาอัปเดต</button></div>
      <p id="s-update-status" class="muted"></p>
    </div>
  `;

  const modeCards = root.querySelectorAll("#s-mode-cards .card");
  modeCards.forEach((card) => {
    card.addEventListener("click", () => {
      const value = card.dataset.mode;
      localStorage.setItem("aiguard.mode", value);
      modeCards.forEach((c) => {
        if (c.dataset.mode === value) {
          c.style.borderColor = "var(--primary)";
          c.style.background = "var(--primary-soft)";
        } else {
          c.style.borderColor = "";
          c.style.background = "";
        }
      });
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
        status.textContent = "";
        status.append(`มีอัปเดต ${info.version} `);
        const doBtn = document.createElement("button");
        doBtn.className = "btn btn--primary";
        doBtn.textContent = "อัปเดตเลย";
        status.appendChild(doBtn);
        if (info.notes) {
          const notes = document.createElement("div");
          notes.className = "well";
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
