import { health } from "./api.js";
import { renderText } from "./screen-text.js";
import { renderRedact } from "./screen-redact.js";
import { renderReport } from "./screen-report.js";
import { renderSettings } from "./screen-settings.js";

const SCREENS = {
  text: renderText,
  redact: renderRedact,
  report: renderReport,
  settings: renderSettings,
};

async function waitForBackend() {
  const msg = document.getElementById("boot-msg");
  for (let attempt = 1; attempt <= 40; attempt++) {
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

async function main() {
  const ok = await waitForBackend();
  if (!ok) return;
  document.getElementById("boot").classList.add("hidden");
  document.getElementById("app").classList.remove("hidden");
  document.querySelectorAll(".nav-item").forEach((b) => {
    b.addEventListener("click", () => selectTab(b.dataset.tab));
  });
  selectTab("text");
}

main();
