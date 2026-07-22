import { analyze } from "./api.js";
import { screenHeader, escapeHtml } from "./ui.js";

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
    <div class="row"><button class="btn btn--primary" id="a-go">วิเคราะห์</button></div>
    <div id="a-out">
      <p class="muted" style="text-align:center">วางข้อความแล้วกดวิเคราะห์เพื่อดูรายงาน</p>
    </div>
    <div class="banner banner--err hidden" id="a-err"></div>
  `;

  const $ = (id) => root.querySelector(id);

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

  $("#a-go").addEventListener("click", async () => {
    $("#a-go").disabled = true;
    const text = $("#a-input").value.trim();
    if (!text) {
      $("#a-go").disabled = false;
      return;
    }
    $("#a-err").classList.add("hidden");
    try {
      const r = await analyze(text);
      renderReportBody(r);
    } catch (e) {
      $("#a-err").textContent = "วิเคราะห์ไม่สำเร็จ: " + e.message;
      $("#a-err").classList.remove("hidden");
    } finally {
      $("#a-go").disabled = false;
    }
  });
}
