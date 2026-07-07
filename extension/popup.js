// AI Guard popup: backend status + manual paste-mode fallback.
// Fetches go through the service worker so they share its host permissions.

const $ = (id) => document.getElementById(id);
let sessionId = null;
let maskedText = "";

function escapeHtml(s) {
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

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

// wrap each detected pseudonym in a chip so the user sees what was masked
function highlightTokens(text, entities, mode) {
  let html = escapeHtml(text);
  const cls = mode === "surrogate" ? "chip chip--surrogate" : "chip chip--token";
  const tokens = [...new Set((entities || []).map((e) => e.token).filter(Boolean))].sort(
    (a, b) => b.length - a.length
  );
  for (const t of tokens) {
    const et = escapeHtml(t);
    html = html.split(et).join(`<span class="${cls}">${et}</span>`);
  }
  return html;
}

async function checkHealth() {
  const r = await send({ type: "health" });
  const up = r && r.ok;
  $("dot").className = "dot " + (up ? "up" : "down");
  $("conn").textContent = up
    ? "พร้อมใช้งาน v" + ((r.data && r.data.version) || "?")
    : "backend ยังไม่ทำงาน เปิดแอป AI Guard";
}

async function doMask() {
  const text = $("input").value.trim();
  if (!text) {
    setMsg("ใส่ข้อความก่อน", "err");
    return;
  }
  setMsg("กำลังปกปิด...");
  $("maskBtn").disabled = true;
  const mode = currentMode();
  const r = await send({ type: "sanitize", text, mode });
  $("maskBtn").disabled = false;
  if (!r || !r.ok) {
    setMsg(r && r.status === 0 ? "backend ยังไม่ทำงาน" : "ปกปิดไม่สำเร็จ", "err");
    return;
  }
  sessionId = r.data.session_id;
  maskedText = r.data.sanitized_text;
  $("masked").innerHTML = highlightTokens(maskedText, r.data.entities, mode);
  $("count").textContent = "ปกปิด " + (r.data.entities || []).length + " รายการ";
  $("maskedWrap").hidden = false;
  $("copyBtn").hidden = false;
  $("restoreBtn").disabled = false;
  setMsg("");
}

async function doRestore() {
  const text = $("reply").value.trim();
  if (!text) {
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
  $("out").hidden = false;
  $("out").textContent = r.data.restored_text;
  const leftover = (r.data.leftover_tokens || []).length;
  setMsg(
    "คืนค่า " + r.data.replaced_count + " รายการ" + (leftover ? " เหลือ " + leftover : ""),
    leftover ? "err" : "ok"
  );
}

$("maskBtn").addEventListener("click", doMask);
$("restoreBtn").addEventListener("click", doRestore);
$("copyBtn").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(maskedText);
    const btn = $("copyBtn");
    btn.textContent = "คัดลอกแล้ว";
    setTimeout(() => { btn.textContent = "คัดลอก"; }, 1200);
  } catch (e) {
    setMsg("คัดลอกไม่สำเร็จ", "err");
  }
});

checkHealth();
