// AI Guard side panel. The MV3 service worker owns the only native port.

const $ = (id) => document.getElementById(id);
const CONTRACT = globalThis.AIGUARD_CONTRACT_V2;
if (!CONTRACT) throw new Error("contract-unavailable");
let sessionAvailable = false;
let maskedText = "";
let backendReady = false;
let panelRequestCounter = 0;
const pending = new Map();
const HEALTH_RETRY_BASE_MS = 250;
const HEALTH_RETRY_MAX_MS = 30000;
let healthRetryAttempt = 0;
let healthRetryTimer = null;
let panelPort = null;
let panelPortGeneration = 0;

function unavailable() {
  return { ok: false, status: 0, error: "native-unavailable" };
}

function scheduleHealthRetry() {
  if (healthRetryTimer !== null) return;
  const exponent = Math.min(healthRetryAttempt, 7);
  const delay = Math.min(HEALTH_RETRY_MAX_MS, HEALTH_RETRY_BASE_MS * 2 ** exponent);
  healthRetryAttempt += 1;
  healthRetryTimer = setTimeout(() => {
    healthRetryTimer = null;
    void checkHealth();
  }, delay);
}

function clearHealthRetry() {
  healthRetryAttempt = 0;
  if (healthRetryTimer !== null) {
    clearTimeout(healthRetryTimer);
    healthRetryTimer = null;
  }
}

function settlePendingUnavailable() {
  for (const resolve of pending.values()) resolve(unavailable());
  pending.clear();
}

function disconnectGeneration(port, generation) {
  if (panelPort !== port || panelPortGeneration !== generation) return;
  void chrome.runtime.lastError;
  panelPort = null;
  backendReady = false;
  invalidateSession();
  settlePendingUnavailable();
  scheduleHealthRetry();
}

function connectPanelPort() {
  if (panelPort) return panelPort;
  let port;
  try {
    port = chrome.runtime.connect({ name: "aiguard-side-panel-v1" });
  } catch {
    scheduleHealthRetry();
    return null;
  }
  panelPortGeneration += 1;
  const generation = panelPortGeneration;
  panelPort = port;
  port.onMessage.addListener((message) => {
    if (panelPort !== port || panelPortGeneration !== generation) return;
    if (message && message.type === "lifecycle") {
      invalidateSession();
      if (message.state === "session-expired") {
        backendReady = false;
        $("maskBtn").disabled = true;
        setMsg("เซสชันหมดอายุ ปกปิดใหม่อีกครั้ง", "err");
        scheduleHealthRetry();
      }
      return;
    }
    if (!message || message.type !== "response") return;
    const resolve = pending.get(message.panel_request_id);
    if (!resolve) return;
    pending.delete(message.panel_request_id);
    resolve(message.response);
  });
  port.onDisconnect.addListener(() => disconnectGeneration(port, generation));
  return port;
}

function send(message) {
  const port = panelPort || (message.type === "health" ? connectPanelPort() : null);
  if (!port) return Promise.resolve(unavailable());
  const generation = panelPortGeneration;
  return new Promise((resolve) => {
    panelRequestCounter += 1;
    const panelRequestId = `panel-${panelRequestCounter}`;
    pending.set(panelRequestId, resolve);
    try {
      port.postMessage({ message, panel_request_id: panelRequestId });
    } catch {
      pending.delete(panelRequestId);
      resolve(unavailable());
      disconnectGeneration(port, generation);
    }
  });
}

function invalidateSession() {
  sessionAvailable = false;
  maskedText = "";
  $("copyBtn").hidden = true;
  $("restoreBtn").disabled = true;
  $("out").textContent = "";
  $("out").hidden = true;
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
  let r = await send({ type: "health" });
  try {
    if (r && r.ok) r = { ...r, data: CONTRACT.validateHealth(r.data) };
  } catch {
    r = { ok: false, status: 0, error: "contract-invalid" };
  }
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
  if (backendReady) clearHealthRetry();
  else {
    invalidateSession();
    scheduleHealthRetry();
  }
  $("dot").className = "dot " + (up ? "up" : "down");
  $("conn").textContent = up
    ? "พร้อมใช้งาน v" + ((r.data && r.data.version) || "?")
    : "ติดตั้งหรือซ่อมแซม AI Guard Desktop companion";
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
  let r = await send({ type: "sanitize", text, mode });
  $("maskBtn").disabled = !backendReady;
  if (!r || !r.ok) {
    invalidateSession();
    setMsg(r && r.status === 0 ? "backend ยังไม่ทำงาน" : "ปกปิดไม่สำเร็จ", "err");
    return;
  }
  try {
    r = { ...r, data: CONTRACT.validateNativeSanitize(r.data) };
  } catch {
    invalidateSession();
    setMsg("ผลลัพธ์ไม่ผ่านการตรวจความปลอดภัย", "err");
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
  sessionAvailable = true;
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
  if (!sessionAvailable) {
    setMsg("ปกปิดข้อความก่อน", "err");
    return;
  }
  let r = await send({ type: "reidentify", text });
  if (!r || !r.ok) {
    invalidateSession();
    setMsg("คืนค่าไม่สำเร็จ", "err");
    return;
  }
  try {
    r = { ...r, data: CONTRACT.validateReidentify(r.data) };
  } catch {
    invalidateSession();
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
