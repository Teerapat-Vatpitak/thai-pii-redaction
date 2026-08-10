import { copyMasked, disposeSession, sanitize, reidentify } from "./api.js";
import { safeErrorMessage } from "./errors.js";
import {
  renderHighlightedText,
  restorationIsComplete,
} from "./contract-v2.js";
import { screenHeader } from "./ui.js";

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
  let maskedText = "";
  let copyAllowed = false;
  let screenActive = true;
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

  function invalidateSession() {
    sessionId = null;
    copyAllowed = false;
    maskedText = "";
    $("#t-out").classList.add("hidden");
  }

  function invalidatePublication() {
    if (!screenActive) return;
    screenActive = false;
    invalidateSession();
    $("#t-input").value = "";
    $("#t-reply").value = "";
    $("#t-masked").textContent = "";
    $("#t-count").textContent = "";
    $("#t-restored").textContent = "";
    $("#t-leftover").textContent = "";
  }

  async function doMask() {
    if (!screenActive) return;
    $("#t-mask").disabled = true;
    const text = $("#t-input").value;
    if (!text.trim()) {
      $("#t-mask").disabled = false;
      return;
    }
    hideError();
    copyAllowed = false;
    maskedText = "";
    $("#t-out").classList.add("hidden");
    $("#t-restored").classList.add("hidden");
    $("#t-leftover").classList.add("hidden");
    try {
      const res = sessionId
        ? await sanitize(text, mode, sessionId)
        : await sanitize(text, mode);
      if (!screenActive) return;
      if (
        !res ||
        typeof res.sanitized_text !== "string" ||
        res.sanitized_text.length === 0 ||
        !res.safety ||
        res.safety.status !== "pass" ||
        res.safety.residual_count !== 0
      ) {
        throw new Error("ผลลัพธ์ไม่ผ่านการตรวจความปลอดภัย");
      }
      sessionId = res.session_id;
      maskedText = res.sanitized_text;
      copyAllowed = true;
      const chipClass = mode === "surrogate" ? "chip--surrogate" : "chip--token";
      $("#t-masked").innerHTML = renderHighlightedText(
        maskedText,
        res.highlights,
        chipClass
      );
      $("#t-count").textContent = `ปกปิด ${res.replacement_count} รายการ`;
      $("#t-out").classList.remove("hidden");
    } catch (e) {
      if (!screenActive) return;
      if (e && e.sessionInvalidated === true) invalidateSession();
      showError("ปกปิดไม่สำเร็จ: " + safeErrorMessage(e), doMask);
    } finally {
      if (screenActive) $("#t-mask").disabled = false;
    }
  }

  $("#t-mask").addEventListener("click", doMask);

  $("#t-copy").addEventListener("click", async () => {
    if (!screenActive) return;
    const btn = $("#t-copy");
    if (!copyAllowed || !maskedText || !sessionId) {
      showError("ยังไม่มีผลลัพธ์ที่ผ่านการตรวจความปลอดภัย", doMask);
      return;
    }
    try {
      await copyMasked(sessionId, maskedText);
      if (!screenActive) return;
      const prev = btn.textContent;
      btn.textContent = "คัดลอกแล้ว";
      setTimeout(() => { btn.textContent = prev; }, 1200);
    } catch (e) {
      if (e && e.sessionInvalidated === true) invalidateSession();
      showError("คัดลอกไม่สำเร็จ: " + safeErrorMessage(e), () => $("#t-copy").click());
    }
  });

  async function doRestore() {
    if (!screenActive || !sessionId) return;
    const reply = $("#t-reply").value;
    try {
      const res = await reidentify(sessionId, reply);
      if (!screenActive) return;
      if (!restorationIsComplete(res)) {
        $("#t-restored").textContent = "";
        $("#t-restored").classList.add("hidden");
        const warningCount = res.warnings.reduce(
          (sum, warning) => sum + warning.count,
          0
        );
        $("#t-leftover").textContent =
          `คืนค่าไม่ครบ เหลือ ${res.leftover_count} รายการ` +
          (warningCount ? ` และมีคำเตือน ${warningCount} รายการ` : "");
        $("#t-leftover").classList.remove("hidden");
        return;
      }
      $("#t-restored").textContent = res.restored_text;
      $("#t-restored").classList.remove("hidden");
      $("#t-leftover").classList.add("hidden");
    } catch (e) {
      if (!screenActive) return;
      if (e && e.sessionInvalidated === true) invalidateSession();
      showError("คืนค่าไม่สำเร็จ: " + safeErrorMessage(e), doRestore);
    }
  }

  $("#t-restore").addEventListener("click", doRestore);

  const cleanup = async () => {
    const ownedSession = sessionId;
    invalidatePublication();
    if (!ownedSession) return;
    try {
      await disposeSession(ownedSession);
    } catch {
      // Never claim disposal. Scope close or connection teardown owns the
      // fail-closed fallback.
    }
  };
  cleanup.invalidatePublication = invalidatePublication;
  return cleanup;
}
