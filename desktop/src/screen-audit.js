import { auditLog } from "./api.js";
import { screenHeader, escapeHtml } from "./ui.js";

const REFRESH_ICON = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M23 4v6h-6"/><path d="M1 20v-6h6"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>`;

function formatUpdatedAt(date) {
  const hh = String(date.getHours()).padStart(2, "0");
  const mm = String(date.getMinutes()).padStart(2, "0");
  return `${hh}:${mm}`;
}

function skeletonRows() {
  return Array.from({ length: 5 })
    .map(
      () => `<tr>
        <td><div class="skeleton" style="width:120px"></div></td>
        <td><div class="skeleton" style="width:80px"></div></td>
        <td><div class="skeleton" style="width:60px"></div></td>
        <td><div class="skeleton" style="width:90px"></div></td>
        <td><div class="skeleton" style="width:40px"></div></td>
      </tr>`
    )
    .join("");
}

export function renderAudit(root) {
  root.innerHTML = `
    ${screenHeader("Audit Log", "บันทึกกระบวนการล่าสุดก่อน ไม่มีข้อมูลส่วนบุคคล")}
    <div class="row" style="justify-content: space-between;">
      <span class="meta" id="au-updated"></span>
      <button class="btn btn--ghost" id="au-refresh" title="Refresh" aria-label="Refresh">${REFRESH_ICON}</button>
    </div>
    <div id="au-out"></div>
    <p class="err hidden" id="au-err"></p>
  `;
  const $ = (id) => root.querySelector(id);

  $("#au-out").innerHTML = `<div class="card"><table class="table">
    <thead><tr><th>เวลา</th><th>step</th><th>entities</th><th>ผล</th><th>ms</th></tr></thead>
    <tbody>${skeletonRows()}</tbody>
  </table></div>`;

  async function load() {
    $("#au-err").classList.add("hidden");
    try {
      const r = await auditLog(200, 0);
      if (!r.logs.length) {
        $("#au-out").innerHTML = `<div class="card"><p class="muted" style="text-align:center;">ยังไม่มีบันทึก</p></div>`;
      } else {
        $("#au-out").innerHTML = `<div class="card"><table class="table">
          <thead><tr><th>เวลา</th><th>step</th><th>entities</th><th>ผล</th><th>ms</th></tr></thead>
          <tbody>${r.logs
            .map(
              (x) => `<tr>
            <td class="meta">${escapeHtml(new Date((x.timestamp || 0) * 1000).toLocaleString())}</td>
            <td class="mono-cell">${escapeHtml(x.step || x.layer || "")}</td>
            <td>${escapeHtml(x.entity_count ?? "")}</td>
            <td>${escapeHtml(x.validation_result || x.pii_scan_result || "")}</td>
            <td class="num">${x.latency_ms != null ? escapeHtml(x.latency_ms.toFixed(0)) : ""}</td>
          </tr>`
            )
            .join("")}</tbody>
        </table></div>`;
      }
      $("#au-updated").textContent = `อัปเดตล่าสุด ${formatUpdatedAt(new Date())}`;
    } catch (e) {
      $("#au-err").textContent = "โหลด audit log ไม่สำเร็จ: " + e.message;
      $("#au-err").classList.remove("hidden");
    }
  }
  $("#au-refresh").addEventListener("click", load);
  load();
}
