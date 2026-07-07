import { health } from "./api.js";
import { initTheme } from "./theme.js";
import { renderText } from "./screen-text.js";
import { renderRedact } from "./screen-redact.js";
import { renderReport } from "./screen-report.js";
import { renderSettings } from "./screen-settings.js";
import { renderAudit } from "./screen-audit.js";

const SCREENS = {
  text: renderText,
  redact: renderRedact,
  report: renderReport,
  settings: renderSettings,
  audit: renderAudit,
};

async function waitForBackend() {
  const msg = document.getElementById("boot-msg");
  for (let attempt = 1; attempt <= 60; attempt++) {
    try {
      await health();
      return true;
    } catch {
      msg.textContent = `กำลังเริ่มบริการในเครื่อง... (${attempt})`;
      await new Promise((r) => setTimeout(r, 500));
    }
  }
  msg.textContent = "เริ่มบริการไม่สำเร็จ ปิดแล้วเปิดแอปใหม่";
  return false;
}

function selectTab(name) {
  document.querySelectorAll(".nav-item").forEach((b) => {
    b.classList.toggle("active", b.dataset.tab === name);
  });
  const root = document.getElementById("screen");
  root.innerHTML = "";
  SCREENS[name](root);
}

async function checkForUpdateBanner() {
  if (!window.__TAURI__) return;
  try {
    const info = await window.__TAURI__.core.invoke("update_check");
    if (!info.available) return;
    const toast = document.createElement("div");
    toast.className = "toast";
    const label = document.createElement("span");
    label.textContent = `มีอัปเดตใหม่ ${info.version} ไปที่หน้า Settings เพื่ออัปเดต`;
    const close = document.createElement("button");
    close.className = "toast__close";
    close.setAttribute("aria-label", "ปิด");
    close.textContent = "×";
    close.addEventListener("click", () => toast.remove());
    toast.append(label, close);
    document.body.appendChild(toast);
  } catch {
    // offline, or no published release yet: stay silent
  }
}

async function main() {
  initTheme();
  const ok = await waitForBackend();
  if (!ok) return;
  document.getElementById("boot").classList.add("hidden");
  document.getElementById("app").classList.remove("hidden");
  document.querySelectorAll(".nav-item").forEach((b) => {
    b.addEventListener("click", () => selectTab(b.dataset.tab));
  });
  selectTab("text");
  checkForUpdateBanner();
}

main();
