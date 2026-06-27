// AI Guard popup: backend status + manual paste-mode fallback.
// Fetches go through the service worker so they share its host permissions.

const $ = (id) => document.getElementById(id);
let sessionId = null;

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

function currentMode() {
  const r = document.querySelector('input[name="mode"]:checked');
  return r && r.value === "surrogate" ? "surrogate" : "token";
}

// restore the saved mode and persist changes (shared with the in-page bar)
chrome.storage.local.get("mode", (o) => {
  const el = document.querySelector(`input[name="mode"][value="${o.mode || "token"}"]`);
  if (el) el.checked = true;
});
document.querySelectorAll('input[name="mode"]').forEach((r) =>
  r.addEventListener("change", () => chrome.storage.local.set({ mode: currentMode() }))
);

async function checkHealth() {
  const r = await send({ type: "health" });
  const up = r && r.ok;
  $("dot").className = "dot " + (up ? "up" : "down");
  $("conn").textContent = up
    ? "backend ready (v" + ((r.data && r.data.version) || "?") + ")"
    : "backend offline - run run.ps1 / run.sh";
}

async function doMask() {
  const text = $("input").value.trim();
  if (!text) {
    setMsg("Enter text first", "err");
    return;
  }
  setMsg("Masking...");
  const r = await send({ type: "sanitize", text, mode: currentMode() });
  if (!r || !r.ok) {
    setMsg(r && r.status === 0 ? "Backend offline" : "Error masking", "err");
    return;
  }
  sessionId = r.data.session_id;
  $("input").value = r.data.sanitized_text;
  $("copyBtn").disabled = false;
  $("restoreBtn").disabled = false;
  const n = (r.data.entities || []).length;
  setMsg(n + (n === 1 ? " item masked" : " items masked"), "ok");
}

async function doRestore() {
  const text = $("reply").value.trim();
  if (!text) {
    setMsg("Paste the AI reply first", "err");
    return;
  }
  if (!sessionId) {
    setMsg("Mask something first", "err");
    return;
  }
  const r = await send({ type: "reidentify", session_id: sessionId, text });
  if (!r || !r.ok) {
    setMsg("Restore failed", "err");
    return;
  }
  $("out").hidden = false;
  $("out").textContent = r.data.restored_text;
  const leftover = (r.data.leftover_tokens || []).length;
  setMsg(
    r.data.replaced_count + " token(s) restored" + (leftover ? " - " + leftover + " left" : ""),
    "ok"
  );
}

$("maskBtn").addEventListener("click", doMask);
$("restoreBtn").addEventListener("click", doRestore);
$("copyBtn").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText($("input").value);
    setMsg("Copied", "ok");
  } catch (e) {
    setMsg("Copy failed", "err");
  }
});

checkHealth();
