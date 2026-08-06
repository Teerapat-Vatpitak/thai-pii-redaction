// AI Guard side panel: backend status + manual paste-mode workspace.
// Fetches go through the service worker so they share its host permissions.

const $ = (id) => document.getElementById(id);
const CONTRACT = globalThis.AIGUARD_CONTRACT_V2;
if (!CONTRACT) throw new Error("HTTP v2 contract helpers are unavailable");
let sessionId = null;
let maskedText = "";
let backendReady = false;

function send(message) {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage(message, (resp) => {
      if (chrome.runtime.lastError) {
        resolve({ ok: false, status: 0, error: chrome.runtime.lastError.message });
      } else {
        resolve(resp);
      }
    });
  });
}

function setMsg(text, kind) {
  const m = $("msg");
  m.textContent = text || "";
  m.className = "msg" + (kind ? " " + kind : "");
}

// ---- mode segmented control (shared with the in-page bar via chrome.storage) ----
function currentMode() {
  const sel = document.querySelector('.seg__opt[aria-selected="true"]');
  return sel && sel.dataset.mode === "surrogate" ? "surrogate" : "token";
}

function selectMode(mode) {
  document.querySelectorAll(".seg__opt").forEach((b) => {
    b.setAttribute("aria-selected", String(b.dataset.mode === mode));
  });
}

chrome.storage.local.get("mode", (o) => selectMode(o.mode || "token"));
document.querySelectorAll(".seg__opt").forEach((b) =>
  b.addEventListener("click", () => {
    selectMode(b.dataset.mode);
    chrome.storage.local.set({ mode: currentMode() });
  })
);

async function checkHealth() {
  const r = await send({ type: "health" });
  const up =
    r &&
    r.ok &&
    r.data &&
    r.data.status === "ok" &&
    r.data.contract_version === 2 &&
    r.data.capabilities &&
    r.data.capabilities.api_key_required === false;
  backendReady = Boolean(up);
  $("maskBtn").disabled = !backendReady;
  if (!backendReady) {
    sessionId = null;
    maskedText = "";
    $("copyBtn").hidden = true;
    $("restoreBtn").disabled = true;
  }
  $("dot").className = "dot " + (up ? "up" : "down");
  $("conn").textContent = up
    ? "พร้อมใช้งาน v" + ((r.data && r.data.version) || "?")
    : "backend ยังไม่ทำงาน เปิดแอป AI Guard";
}

async function doMask() {
  if (!backendReady) {
    setMsg("backend ยังไม่พร้อมใช้งาน", "err");
    return;
  }
  const text = $("input").value;
  if (!text.trim()) {
    setMsg("ใส่ข้อความก่อน", "err");
    return;
  }
  setMsg("กำลังปกปิด...");
  $("maskBtn").disabled = true;
  maskedText = "";
  $("copyBtn").hidden = true;
  $("maskedWrap").hidden = true;
  $("restoreBtn").disabled = true;
  const mode = currentMode();
  // Reuse the panel's own session so multi-turn token numbering stays consistent
  // (the panel's message has no tab, so background.js can't key reuse on tabId;
  // we must pass session_id explicitly). EXT-1.
  const r = await send({ type: "sanitize", text, mode, session_id: sessionId });
  $("maskBtn").disabled = !backendReady;
  if (!r || !r.ok) {
    setMsg(r && r.status === 0 ? "backend ยังไม่ทำงาน" : "ปกปิดไม่สำเร็จ", "err");
    return;
  }
  if (
    !r.data ||
    typeof r.data.sanitized_text !== "string" ||
    r.data.sanitized_text.length === 0 ||
    !r.data.safety ||
    r.data.safety.status !== "pass" ||
    r.data.safety.residual_count !== 0
  ) {
    setMsg("ผลลัพธ์ไม่ผ่านการตรวจความปลอดภัย", "err");
    return;
  }
  sessionId = r.data.session_id;
  maskedText = r.data.sanitized_text;
  $("masked").innerHTML = CONTRACT.renderHighlightedText(
    maskedText,
    r.data.highlights,
    mode
  );
  $("count").textContent = "ปกปิด " + r.data.replacement_count + " รายการ";
  $("maskedWrap").hidden = false;
  $("copyBtn").hidden = false;
  $("restoreBtn").disabled = false;
  setMsg("");
}

async function doRestore() {
  const text = $("reply").value;
  if (!text.trim()) {
    setMsg("วางคำตอบจาก AI ก่อน", "err");
    return;
  }
  if (!sessionId) {
    setMsg("ปกปิดข้อความก่อน", "err");
    return;
  }
  const r = await send({ type: "reidentify", session_id: sessionId, text });
  if (!r || !r.ok) {
    setMsg("คืนค่าไม่สำเร็จ", "err");
    return;
  }
  if (!CONTRACT.restorationIsComplete(r.data)) {
    $("out").textContent = "";
    $("out").hidden = true;
    const warningCount = r.data.warnings.reduce(
      (sum, warning) => sum + warning.count,
      0
    );
    setMsg(
      "คืนค่าไม่ครบ เหลือ " +
        r.data.leftover_count +
        " รายการ" +
        (warningCount ? " และมีคำเตือน " + warningCount + " รายการ" : ""),
      "err"
    );
    return;
  }
  $("out").hidden = false;
  $("out").textContent = r.data.restored_text;
  setMsg("คืนค่า " + r.data.replaced_count + " รายการ", "ok");
}

$("maskBtn").addEventListener("click", doMask);
$("restoreBtn").addEventListener("click", doRestore);
$("copyBtn").addEventListener("click", async () => {
  if (!backendReady || !maskedText) {
    setMsg("ยังไม่มีผลลัพธ์ที่ผ่านการตรวจความปลอดภัย", "err");
    return;
  }
  try {
    await navigator.clipboard.writeText(maskedText);
    const btn = $("copyBtn");
    btn.textContent = "คัดลอกแล้ว";
    setTimeout(() => { btn.textContent = "คัดลอก"; }, 1200);
  } catch (e) {
    setMsg("คัดลอกไม่สำเร็จ", "err");
  }
});

// ---- theme: system / light / dark, persisted in localStorage ----
const THEME_KEY = "aiguard.theme";
const themeMq = window.matchMedia("(prefers-color-scheme: dark)");
const THEME_ORDER = ["system", "light", "dark"];
const THEME_LABEL = { system: "ตามระบบ", light: "สว่าง", dark: "มืด" };
const THEME_ICON = {
  light: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>',
  dark: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3 7 7 0 0 0 21 12.8z"/></svg>',
  system: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/></svg>',
};
function themePref() {
  return localStorage.getItem(THEME_KEY) || "system";
}
function applyTheme() {
  const p = themePref();
  const dark = p === "dark" || (p === "system" && themeMq.matches);
  document.documentElement.setAttribute("data-theme", dark ? "dark" : "light");
}
function renderThemeBtn() {
  const b = $("themeBtn");
  const p = themePref();
  b.innerHTML = THEME_ICON[p]; // constant SVG string, no user input
  b.title = "ธีม: " + THEME_LABEL[p];
  b.setAttribute("aria-label", "ธีม: " + THEME_LABEL[p]);
}
$("themeBtn").addEventListener("click", () => {
  const p = themePref();
  localStorage.setItem(THEME_KEY, THEME_ORDER[(THEME_ORDER.indexOf(p) + 1) % THEME_ORDER.length]);
  applyTheme();
  renderThemeBtn();
});
themeMq.addEventListener("change", () => {
  if (themePref() === "system") applyTheme();
});
applyTheme();
renderThemeBtn();

// The side panel stays open, so unlike the old popup we can't rely on a fresh
// load to re-check the backend. Poll lightly, and re-check whenever the panel
// regains focus/visibility, so the status dot tracks the backend going up/down.
$("maskBtn").disabled = true;
checkHealth();
setInterval(checkHealth, 8000);
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) checkHealth();
});
window.addEventListener("focus", checkHealth);
