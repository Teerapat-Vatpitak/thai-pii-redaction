import { sanitize, reidentify } from "./api.js";
import { screenHeader, escapeHtml } from "./ui.js";

/** Wrap every occurrence of each entity's pseudonym token in a chip span.
 * Tokens are matched longest-first so a token that is a substring of another
 * (e.g. two surrogate names sharing a prefix) never gets partially wrapped.
 * `sanitizedText` must already be escaped with escapeHtml before calling.
 */
function highlightTokens(escapedSanitized, entities, chipClass) {
  const tokens = [...new Set(entities.map((e) => e.token))]
    .map((t) => escapeHtml(t))
    .filter(Boolean)
    .sort((a, b) => b.length - a.length);
  if (!tokens.length) return escapedSanitized;

  const pattern = new RegExp(
    tokens.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|"),
    "g"
  );
  return escapedSanitized.replace(
    pattern,
    (match) => `<span class="chip ${chipClass}">${match}</span>`
  );
}

export function renderText(root) {
  let mode = localStorage.getItem("aiguard.mode") || "token";

  root.innerHTML = `
    ${screenHeader("Mask / Restore", "วางข้อความที่มีข้อมูลส่วนบุคคล กด ปกปิดข้อมูล เพื่อแทนด้วยโทเคน แล้วคัดลอกไปใช้กับ AI ภายนอก")}
    <div class="seg" id="t-mode-seg" role="tablist">
      <button type="button" class="seg__opt" id="t-mode-token" aria-selected="${mode === "token"}">Token</button>
      <button type="button" class="seg__opt" id="t-mode-surrogate" aria-selected="${mode === "surrogate"}">Surrogate</button>
    </div>
    <div class="banner banner--err hidden" id="t-err">
      <span id="t-err-msg"></span>
      <button class="btn btn--ghost" id="t-err-retry" type="button">ลองอีกครั้ง</button>
    </div>
    <textarea id="t-input" placeholder="พิมพ์หรือวางข้อความที่นี่..."></textarea>
    <div class="row">
      <button class="btn btn--primary" id="t-mask">ปกปิดข้อมูล</button>
    </div>
    <div class="card hidden" id="t-out">
      <div class="row"><b>ผลลัพธ์ที่ปกปิดแล้ว</b> <button class="btn btn--secondary" id="t-copy">คัดลอก</button></div>
      <div class="well" id="t-masked"></div>
      <p class="meta" id="t-count"></p>
      <div style="border-top: 1px solid var(--line); margin: var(--s4) 0;"></div>
      <p class="muted">วางคำตอบจาก AI (ที่ยังมีโทเคน) เพื่อคืนค่าจริง</p>
      <textarea id="t-reply" placeholder="วางคำตอบจาก AI ที่นี่..."></textarea>
      <div class="row"><button class="btn btn--primary" id="t-restore">คืนค่า</button></div>
      <div class="well hidden" id="t-restored"></div>
      <div class="banner banner--warn hidden" id="t-leftover"></div>
    </div>
  `;

  let sessionId = null;
  let lastEntities = [];
  const $ = (id) => root.querySelector(id);

  function showError(message, retryFn) {
    $("#t-err-msg").textContent = message;
    $("#t-err").classList.remove("hidden");
    $("#t-err-retry").onclick = () => {
      $("#t-err").classList.add("hidden");
      retryFn();
    };
  }

  function hideError() {
    $("#t-err").classList.add("hidden");
  }

  function setMode(next) {
    mode = next;
    $("#t-mode-token").setAttribute("aria-selected", String(mode === "token"));
    $("#t-mode-surrogate").setAttribute("aria-selected", String(mode === "surrogate"));
  }

  $("#t-mode-token").addEventListener("click", () => setMode("token"));
  $("#t-mode-surrogate").addEventListener("click", () => setMode("surrogate"));

  async function doMask() {
    $("#t-mask").disabled = true;
    const text = $("#t-input").value.trim();
    if (!text) {
      $("#t-mask").disabled = false;
      return;
    }
    hideError();
    try {
      const res = await sanitize(text, mode);
      sessionId = res.session_id;
      lastEntities = res.entities || [];
      const chipClass = mode === "surrogate" ? "chip--surrogate" : "chip--token";
      $("#t-masked").innerHTML = highlightTokens(
        escapeHtml(res.sanitized_text),
        lastEntities,
        chipClass
      );
      $("#t-count").textContent = `ปกปิด ${lastEntities.length} รายการ`;
      $("#t-out").classList.remove("hidden");
    } catch (e) {
      showError("ปกปิดไม่สำเร็จ: " + e.message, doMask);
    } finally {
      $("#t-mask").disabled = false;
    }
  }

  $("#t-mask").addEventListener("click", doMask);

  $("#t-copy").addEventListener("click", async () => {
    const btn = $("#t-copy");
    try {
      await navigator.clipboard.writeText($("#t-masked").textContent);
      const prev = btn.textContent;
      btn.textContent = "คัดลอกแล้ว";
      setTimeout(() => { btn.textContent = prev; }, 1200);
    } catch (e) {
      showError("คัดลอกไม่สำเร็จ: " + e.message, () => $("#t-copy").click());
    }
  });

  async function doRestore() {
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
      showError("คืนค่าไม่สำเร็จ: " + e.message, doRestore);
    }
  }

  $("#t-restore").addEventListener("click", doRestore);
}
