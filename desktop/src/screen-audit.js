import { auditLog } from "./api.js";

export function renderAudit(root) {
  root.innerHTML = `
    <h2>Audit Log</h2>
    <p>บันทึกกระบวนการ (ไม่มีข้อมูลส่วนบุคคล) — ล่าสุดก่อน</p>
    <div class="row"><button class="primary" id="au-refresh">Refresh</button> <span id="au-count"></span></div>
    <div id="au-out"></div>
    <p class="err hidden" id="au-err"></p>
  `;
  const $ = (id) => root.querySelector(id);

  async function load() {
    $("#au-err").classList.add("hidden");
    try {
      const r = await auditLog(200, 0);
      $("#au-count").textContent = `รวม ${r.total_count} รายการ`;
      $("#au-out").innerHTML = `<div class="card"><table>
        <tr><th>เวลา</th><th>step</th><th>entities</th><th>ผล</th><th>ms</th></tr>
        ${r.logs.map((x) => `<tr>
          <td>${new Date((x.timestamp || 0) * 1000).toLocaleString()}</td>
          <td class="mono">${x.step || x.layer || ""}</td>
          <td>${x.entity_count ?? ""}</td>
          <td>${x.validation_result || x.pii_scan_result || ""}</td>
          <td>${x.latency_ms != null ? x.latency_ms.toFixed(0) : ""}</td>
        </tr>`).join("")}
      </table></div>`;
    } catch (e) {
      $("#au-err").textContent = "โหลด audit log ไม่สำเร็จ: " + e.message;
      $("#au-err").classList.remove("hidden");
    }
  }
  $("#au-refresh").addEventListener("click", load);
  load();
}
