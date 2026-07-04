import { analyze } from "./api.js";

export function renderReport(root) {
  root.innerHTML = `
    <h2>PDPA Risk Report</h2>
    <p>วิเคราะห์ความเสี่ยง PDPA ของข้อความ (คะแนน, re-identification, ข้อมูลอ่อนไหว ม.26)</p>
    <textarea id="a-input" placeholder="วางข้อความเพื่อวิเคราะห์..."></textarea>
    <div class="row"><button class="primary" id="a-go">Analyze</button></div>
    <div id="a-out"></div>
    <p class="err hidden" id="a-err"></p>
  `;

  const $ = (id) => root.querySelector(id);

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
      $("#a-out").innerHTML = `
        <div class="card">
          <b>คะแนนรวม:</b> ${r.overall_score.toFixed(1)} (เกรด ${r.overall_grade}) — ${r.risk_label}<br/>
          <b>PII โดยตรง:</b> ${r.direct_pii_count} · <b>re-id:</b> ${r.reid.score.toFixed(1)} (เกรด ${r.reid.grade})${r.reid.high_risk_combo ? " · เสี่ยงสูงจากการรวมข้อมูล" : ""}
        </div>
        ${r.section26.length ? `<div class="card"><b>ข้อมูลอ่อนไหว ม.26 (${r.section26.length})</b><ul>${r.section26.map((s) => `<li>${s.category}: ${escapeHtml(s.text)}${s.source === "semantic" ? " (AI)" : ""}</li>`).join("")}</ul></div>` : ""}
        ${r.breakdown.length ? `<div class="card"><b>ประเภท PII ที่พบ</b><table><tr><th>ชนิด</th><th>กลุ่ม</th><th>จำนวน</th></tr>${r.breakdown.map((b) => `<tr><td>${b.data_type}</td><td>${b.redact_type}</td><td>${b.count}</td></tr>`).join("")}</table></div>` : ""}
        ${r.recommendations.length ? `<div class="card"><b>คำแนะนำ</b><ul>${r.recommendations.map((c) => `<li><b>[${c.level}]</b> ${escapeHtml(c.title)} — ${escapeHtml(c.desc)}</li>`).join("")}</ul></div>` : ""}
      `;
    } catch (e) {
      $("#a-err").textContent = "วิเคราะห์ไม่สำเร็จ: " + e.message;
      $("#a-err").classList.remove("hidden");
    } finally {
      $("#a-go").disabled = false;
    }
  });

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
    );
  }
}
