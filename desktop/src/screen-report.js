import { analyze, analyzeReport } from "./api.js";
import { screenHeader, escapeHtml } from "./ui.js";

const REPORT_FILENAME = "aiguard-pdpa-report.pdf";

function b64ToPdfBlob(b64) {
  if (typeof b64 !== "string" || !b64) {
    throw new Error("เซิร์ฟเวอร์ไม่ส่งไฟล์ PDF กลับมา");
  }
  const bytes = atob(b64);
  const arr = new Uint8Array(bytes.length);
  for (let i = 0; i < bytes.length; i++) arr[i] = bytes.charCodeAt(i);
  return new Blob([arr], { type: "application/pdf" });
}

/** Trigger a download with a fixed ASCII filename; no user input reaches the filename. */
export function downloadReportPdf(b64) {
  const url = URL.createObjectURL(b64ToPdfBlob(b64));
  const link = document.createElement("a");
  link.href = url;
  link.download = REPORT_FILENAME;
  link.rel = "noopener";
  document.body.appendChild(link);
  link.click();
  link.remove();
  // Let the WebView consume the click in its next task before invalidating the
  // URL. Immediate revocation is timing-sensitive across browser engines.
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

/** Grade band -> chip color. A/B read as low risk (ok), C/D as medium (warn), F as high (err). */
function gradeChipClass(grade) {
  if (grade === "A" || grade === "B") return "chip--ok";
  if (grade === "C" || grade === "D") return "chip--warn";
  return "chip--err";
}

/** Recommendation level -> CSS variable name for the left-border/text color. */
function levelVar(level) {
  if (level === "high") return "--err";
  if (level === "medium") return "--warn";
  return "--ok";
}

export function renderReport(root) {
  root.innerHTML = `
    ${screenHeader("PDPA Report", "วิเคราะห์ความเสี่ยง PDPA ของข้อความ คะแนนรวม re-identification และข้อมูลอ่อนไหวตามมาตรา 26")}
    <textarea id="a-input" placeholder="วางข้อความเพื่อวิเคราะห์..."></textarea>
    <div class="row">
      <button class="btn btn--primary" id="a-go">วิเคราะห์</button>
      <button class="btn btn--secondary" id="a-download" disabled>ดาวน์โหลดรายงาน PDF</button>
    </div>
    <div class="banner hidden" id="a-status" role="status" aria-live="polite"></div>
    <div id="a-out">
      <p class="muted" style="text-align:center">วางข้อความแล้วกดวิเคราะห์เพื่อดูรายงาน</p>
    </div>
    <div class="banner banner--err hidden" id="a-err" role="alert"></div>
  `;

  const $ = (id) => root.querySelector(id);
  const isMounted = (element, selector) =>
    element.isConnected && root.querySelector(selector) === element;

  function hideStatus() {
    $("#a-status").classList.add("hidden");
    $("#a-status").classList.remove("banner--ok");
  }

  function showStatus(message, success = false) {
    $("#a-status").textContent = message;
    $("#a-status").classList.toggle("banner--ok", success);
    $("#a-status").classList.remove("hidden");
  }

  function showError(message) {
    $("#a-err").textContent = message;
    $("#a-err").classList.remove("hidden");
  }

  $("#a-input").addEventListener("input", () => {
    $("#a-download").disabled = !$("#a-input").value.trim();
    hideStatus();
  });

  function renderReportBody(r) {
    const gradeClass = gradeChipClass(r.overall_grade);
    const reidCombo = r.reid.high_risk_combo
      ? `<span class="chip chip--warn">เสี่ยงสูงจากการรวมข้อมูล</span>`
      : "";

    const section26Html = r.section26.length
      ? `<div class="card">
          <p class="muted">ข้อมูลอ่อนไหว มาตรา 26 (${r.section26.length})</p>
          ${r.section26
            .map(
              (s) => `<div class="row">
                <span class="chip chip--warn">${escapeHtml(s.category)}</span>
                <span>${escapeHtml(s.text)}</span>
                ${s.source === "semantic" ? `<span class="meta">semantic</span>` : ""}
              </div>`
            )
            .join("")}
        </div>`
      : "";

    const breakdownHtml = r.breakdown.length
      ? `<div class="card">
          <p class="muted">ประเภท PII ที่พบ</p>
          <table class="table">
            <thead><tr><th>ชนิด</th><th>กลุ่ม</th><th class="num">จำนวน</th></tr></thead>
            <tbody>
              ${r.breakdown
                .map(
                  (b) => `<tr>
                    <td>${escapeHtml(b.data_type)}</td>
                    <td><span class="chip ${b.redact_type === "FP" ? "chip--token" : "chip--surrogate"}">${escapeHtml(b.redact_type)}</span></td>
                    <td class="num">${Number(b.count) || 0}</td>
                  </tr>`
                )
                .join("")}
            </tbody>
          </table>
        </div>`
      : "";

    const recommendationsHtml = r.recommendations.length
      ? `<div class="card">
          <p class="muted">คำแนะนำ</p>
          ${r.recommendations
            .map((c) => {
              const v = levelVar(c.level);
              return `<div class="row" style="border-left:2px solid var(${v}); padding-left:12px">
                <span style="color:var(${v})">${escapeHtml(c.level)}</span>
                <span>${escapeHtml(c.title)}</span>
                <span class="muted">${escapeHtml(c.desc)}</span>
              </div>`;
            })
            .join("")}
        </div>`
      : "";

    $("#a-out").innerHTML = `
      <div class="card stat-band">
        <div class="stat">
          <span class="stat__num">${r.overall_score.toFixed(1)}</span>
          <span class="stat__cap"><span class="chip ${gradeClass}">เกรด ${escapeHtml(r.overall_grade)}</span> ${escapeHtml(r.risk_label)}</span>
        </div>
        <div class="stat">
          <span class="stat__num">${r.reid.score.toFixed(1)}</span>
          <span class="stat__cap">re-identification (เกรด ${escapeHtml(r.reid.grade)}) ${reidCombo}</span>
        </div>
        <div class="stat">
          <span class="stat__num">${Number(r.direct_pii_count) || 0}</span>
          <span class="stat__cap">PII โดยตรง</span>
        </div>
      </div>
      ${section26Html}
      ${breakdownHtml}
      ${recommendationsHtml}
    `;
  }

  $("#a-go").addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    const text = $("#a-input").value.trim();
    if (!text) {
      button.disabled = false;
      return;
    }
    $("#a-err").classList.add("hidden");
    hideStatus();
    try {
      const r = await analyze(text);
      if (!isMounted(button, "#a-go")) return;
      renderReportBody(r);
    } catch (e) {
      if (!isMounted(button, "#a-go")) return;
      showError("วิเคราะห์ไม่สำเร็จ: " + e.message);
    } finally {
      if (isMounted(button, "#a-go")) button.disabled = false;
    }
  });

  $("#a-download").addEventListener("click", async () => {
    const button = $("#a-download");
    const text = $("#a-input").value.trim();
    if (!text) {
      showError("กรุณาวางข้อความก่อนสร้างรายงาน PDF");
      button.disabled = true;
      return;
    }

    $("#a-err").classList.add("hidden");
    button.disabled = true;
    button.textContent = "กำลังสร้าง PDF...";
    showStatus("กำลังสร้างรายงาน PDPA PDF...");
    try {
      const r = await analyzeReport(text);
      // selectTab() reuses the same root. If this screen was replaced while
      // the request was pending, its result belongs to an abandoned action:
      // do not download it or write into the newly mounted screen.
      if (!isMounted(button, "#a-download")) return;
      downloadReportPdf(r.report_pdf_b64);
      showStatus("ดาวน์โหลดรายงาน PDPA PDF แล้ว", true);
    } catch (e) {
      if (!isMounted(button, "#a-download")) return;
      hideStatus();
      showError("สร้างรายงาน PDF ไม่สำเร็จ: " + e.message);
    } finally {
      if (isMounted(button, "#a-download")) {
        button.textContent = "ดาวน์โหลดรายงาน PDF";
        button.disabled = !$("#a-input").value.trim();
      }
    }
  });
}
