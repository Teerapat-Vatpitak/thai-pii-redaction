'use strict';

/* ============================================================
   AI Guard — frontend logic (vanilla JS, wired to FastAPI)
   ============================================================ */

const $ = (id) => document.getElementById(id);

// data_type -> color family
const COLOR = {
  NAME: 'blue', SURNAME: 'blue', PERSON: 'blue',
  THAI_ID: 'amber', DATE_OF_BIRTH: 'amber', PASSPORT: 'amber',
  PHONE: 'sky', EMAIL: 'sky',
  ADDRESS: 'purple', BANK_ACCOUNT: 'purple', CREDIT_CARD: 'purple',
  IBAN: 'purple', STUDENT_ID: 'purple', VEHICLE_PLATE: 'purple',
};
const colorOf = (t) => COLOR[t] || 'blue';

const SAMPLE = `นายสมชาย ใจดี อายุ 32 ปี เลขบัตรประชาชน 1-1019-00000-10-0
โทรศัพท์ 081-234-5678 อีเมล somchai.jaidee@psu.ac.th
อาศัยอยู่ที่ 123/45 ถนนพระราม 4 แขวงคลองเตย จังหวัดกรุงเทพมหานคร
เลขบัญชีธนาคาร 123-4-56789-0 ธนาคารกสิกรไทย
ประวัติสุขภาพ: มีประวัติการรักษาโรคเบาหวานชนิดที่ 2 นับถือศาสนาพุทธ`;

let state = {
  sessionId: null,
  sanitized: false,
  restored: false,
  activeStep: 1,
};

// ── helpers ──────────────────────────────────────────────────
function showError(el, msg) { el.textContent = msg; el.classList.remove('hidden'); }
function clearError(el) { el.textContent = ''; el.classList.add('hidden'); }

async function postJSON(url, body) {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || res.statusText);
  return data;
}

// Build sorted, non-overlapping marks from entity + s26 span lists
function mergeMarks(entities, s26) {
  const all = [];
  (entities || []).forEach((e) => all.push({ start: e.start, end: e.end, kind: 'ent', ref: e }));
  (s26 || []).forEach((s) => { if (s.start != null) all.push({ start: s.start, end: s.end, kind: 's26', ref: s }); });
  all.sort((a, b) => a.start - b.start);
  const out = [];
  let last = -1;
  for (const m of all) { if (m.start >= last) { out.push(m); last = m.end; } }
  return out;
}

// ── rich text renderers (DOM-safe; never innerHTML with data) ──
function renderHighlighted(target, text, entities, s26) {
  target.textContent = '';
  const marks = mergeMarks(entities, s26);
  let cursor = 0;
  for (const m of marks) {
    if (cursor < m.start) target.appendChild(document.createTextNode(text.slice(cursor, m.start)));
    const slice = text.slice(m.start, m.end);
    if (m.kind === 's26') {
      const span = document.createElement('span');
      span.className = 's26-mark';
      span.title = `⚠ PDPA Section 26: ${m.ref.category}`;
      span.textContent = slice;
      target.appendChild(span);
    } else {
      const e = m.ref;
      const mk = document.createElement('mark');
      mk.className = `ent e-${colorOf(e.data_type)}`;
      mk.title = `${e.data_type} (${e.redact_type}) → ${e.token}`;
      mk.textContent = slice;
      target.appendChild(mk);
    }
    cursor = m.end;
  }
  if (cursor < text.length) target.appendChild(document.createTextNode(text.slice(cursor)));
}

function renderSanitized(target, text, entities) {
  target.textContent = '';
  const ents = (entities || []).slice().sort((a, b) => a.start - b.start);
  let cursor = 0;
  for (const e of ents) {
    if (e.start < cursor) continue;
    if (cursor < e.start) target.appendChild(document.createTextNode(text.slice(cursor, e.start)));
    const span = document.createElement('span');
    span.className = `tok e-${colorOf(e.data_type)}`;
    span.textContent = e.token;
    target.appendChild(span);
    cursor = e.end;
  }
  if (cursor < text.length) target.appendChild(document.createTextNode(text.slice(cursor)));
}

function renderRestored(target, text, replaced) {
  target.textContent = '';
  // collect occurrences of each original value
  const originals = (replaced || []).map((r) => r.original).filter(Boolean);
  const hits = [];
  for (const orig of originals) {
    let idx = 0;
    while (true) {
      const found = text.indexOf(orig, idx);
      if (found < 0) break;
      hits.push({ start: found, end: found + orig.length, original: orig });
      idx = found + orig.length;
    }
  }
  hits.sort((a, b) => a.start - b.start);
  let cursor = 0;
  for (const h of hits) {
    if (h.start < cursor) continue;
    if (cursor < h.start) target.appendChild(document.createTextNode(text.slice(cursor, h.start)));
    const mk = document.createElement('mark');
    mk.className = 'restored';
    mk.textContent = h.original;
    target.appendChild(mk);
    cursor = h.end;
  }
  if (cursor < text.length) target.appendChild(document.createTextNode(text.slice(cursor)));
}

// ── view switching ──────────────────────────────────────────
function switchView(view) {
  document.querySelectorAll('.nav-item').forEach((b) => b.classList.toggle('active', b.dataset.view === view));
  document.querySelectorAll('.main .view').forEach((v) => v.classList.toggle('hidden', v.id !== `view-${view}`));
}

// ── AI Guard: step indicator ────────────────────────────────
function updateSteps() {
  const { sanitized, restored, activeStep } = state;
  const done = { 1: sanitized, 2: restored, 3: restored };
  for (let i = 1; i <= 3; i++) {
    const step = $(`step${i}`);
    const dot = $(`step${i}dot`);
    const isActive = activeStep === i;
    const isDone = done[i];
    step.classList.toggle('is-active', isActive && !isDone);
    step.classList.toggle('is-done', isDone);
    step.classList.toggle('locked', i > 1 && !sanitized);
    step.classList.toggle('clickable', i === 1 || sanitized);
    dot.className = 'step-dot' + (isDone ? ' done' : isActive ? ' active' : '');
    dot.textContent = '';
    if (isDone) {
      dot.innerHTML = '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>';
    } else {
      dot.textContent = String(i);
    }
  }
  $('line1').classList.toggle('done', sanitized);
  $('line2').classList.toggle('done', restored);
}

function goStep(n) {
  if (n > 1 && !state.sanitized) return;
  state.activeStep = n;
  $('guardInputCard').classList.toggle('hidden', n !== 1);
  $('guardResults').classList.toggle('hidden', n !== 2);
  $('guardRestoreInput').classList.toggle('hidden', n !== 3);
  $('guardRestored').classList.toggle('hidden', !(n === 3 && state.restored));
  updateSteps();
}

// ── AI Guard: sanitize ──────────────────────────────────────
async function sanitize() {
  const text = $('guardInput').value.trim();
  clearError($('guardError'));
  if (!text) { showError($('guardError'), 'กรุณาวางข้อความก่อน / Please paste some text first.'); return; }

  const btn = $('sanitizeBtn');
  btn.disabled = true;
  const orig = btn.innerHTML;
  btn.innerHTML = '<div class="spinner" style="border-top-color:#fff;border-color:rgba(255,255,255,0.4)"></div> กำลังวิเคราะห์ PII...';

  try {
    const d = await postJSON('/api/sanitize', { text });
    state.sessionId = d.session_id;
    state.sanitized = true;
    state.restored = false;

    // detected summary
    $('detectCount').textContent = `${d.entities.length} PII entities`;
    const typesEl = $('detectTypes');
    typesEl.textContent = '';
    Object.entries(d.entity_type_counts || {}).forEach(([t, c]) => {
      const chip = document.createElement('span');
      chip.className = `type-chip t-${colorOf(t)}`;
      chip.textContent = `${t.replace(/_/g, ' ')} ×${c}`;
      typesEl.appendChild(chip);
    });

    // section 26 alert
    const s26El = $('s26Alert');
    if (d.section26 && d.section26.length) {
      s26El.textContent = '';
      const icon = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      icon.setAttribute('width', '13'); icon.setAttribute('height', '13');
      icon.setAttribute('viewBox', '0 0 24 24'); icon.setAttribute('fill', 'none');
      icon.setAttribute('stroke', '#DC2626'); icon.setAttribute('stroke-width', '2.5');
      icon.innerHTML = '<path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>';
      const span = document.createElement('span');
      const strong = document.createElement('strong');
      strong.textContent = 'PDPA Section 26: ';
      span.appendChild(strong);
      span.appendChild(document.createTextNode(
        d.section26.map((s) => s.category).join(', ') + ' — ต้องได้รับความยินยอมโดยชัดแจ้ง'));
      s26El.appendChild(icon);
      s26El.appendChild(span);
      s26El.classList.remove('hidden');
    } else {
      s26El.classList.add('hidden');
    }

    renderHighlighted($('origRender'), d.original_text, d.entities, d.section26);
    renderSanitized($('safeRender'), d.original_text, d.entities);

    // prefill restore input with the sanitized text (demo convenience)
    $('aiResponse').value = d.sanitized_text;
    window._sanitizedText = d.sanitized_text;

    goStep(2);
  } catch (e) {
    showError($('guardError'), 'เกิดข้อผิดพลาด: ' + e.message);
  } finally {
    btn.disabled = false;
    btn.innerHTML = orig;
  }
}

async function restore() {
  const text = $('aiResponse').value.trim();
  clearError($('restoreError'));
  if (!text) { showError($('restoreError'), 'กรุณาวาง response จาก AI ก่อน'); return; }
  if (!state.sessionId) { showError($('restoreError'), 'ไม่พบ session — กรุณา Sanitize ก่อน'); return; }

  const btn = $('restoreBtn');
  btn.disabled = true;
  const orig = btn.innerHTML;
  btn.innerHTML = '<div class="spinner" style="border-top-color:#fff;border-color:rgba(255,255,255,0.4)"></div> กำลังกู้คืน...';

  try {
    const d = await postJSON('/api/reidentify', { session_id: state.sessionId, text });
    state.restored = true;
    renderRestored($('restoredRender'), d.restored_text, d.replaced);
    $('restoredCount').textContent = `${d.replaced_count} tokens replaced`;
    $('guardRestored').classList.remove('hidden');
    updateSteps();
  } catch (e) {
    showError($('restoreError'), 'เกิดข้อผิดพลาด: ' + e.message);
  } finally {
    btn.disabled = false;
    btn.innerHTML = orig;
  }
}

function copySanitized() {
  const txt = window._sanitizedText || '';
  const btn = $('copyBtn');
  const done = () => {
    btn.classList.add('btn-copied');
    const o = btn.innerHTML;
    btn.innerHTML = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg> Copied!';
    setTimeout(() => { btn.classList.remove('btn-copied'); btn.innerHTML = o; }, 2000);
  };
  if (navigator.clipboard) navigator.clipboard.writeText(txt).then(done).catch(done);
  else done();
}

function resetGuard() {
  state = { sessionId: null, sanitized: false, restored: false, activeStep: 1 };
  $('guardInput').value = SAMPLE;
  $('aiResponse').value = '';
  $('charCount').textContent = countChars(SAMPLE);
  $('guardResults').classList.add('hidden');
  $('guardRestoreInput').classList.add('hidden');
  $('guardRestored').classList.add('hidden');
  clearError($('guardError'));
  clearError($('restoreError'));
  goStep(1);
}

function countChars(t) { return `${t.length.toLocaleString()} ตัวอักษร`; }

// ── PDPA Report ─────────────────────────────────────────────
function gaugeColor(score) {
  return score <= 20 ? '#16A34A' : score <= 40 ? '#65A30D' : score <= 60 ? '#D97706' : score <= 80 ? '#EA580C' : '#DC2626';
}

async function analyze() {
  const text = $('reportInput').value.trim();
  clearError($('reportError'));
  if (!text) { showError($('reportError'), 'กรุณาวางข้อความก่อน'); return; }

  $('reportLoading').classList.remove('hidden');
  $('analyzeBtn').disabled = true;
  try {
    const d = await postJSON('/api/analyze', { text });
    renderReport(d);
    $('reportEmpty').classList.add('hidden');
    $('reportResult').classList.remove('hidden');
  } catch (e) {
    showError($('reportError'), 'เกิดข้อผิดพลาด: ' + e.message);
  } finally {
    $('reportLoading').classList.add('hidden');
    $('analyzeBtn').disabled = false;
  }
}

function renderReport(d) {
  const score = Math.round(d.overall_score);
  const col = gaugeColor(score);
  const CIRC = 2 * Math.PI * 48;

  const arc = $('gaugeArc');
  arc.setAttribute('stroke', col);
  arc.setAttribute('stroke-dasharray', `${(CIRC * score) / 100} ${CIRC}`);
  arc.style.filter = `drop-shadow(0 0 4px ${col})`;
  $('gaugeGrade').textContent = d.overall_grade;
  $('gaugeScore').textContent = `${score}/100`;
  $('gaugeRisk').textContent = d.risk_label;
  $('gaugeRisk').style.color = col;

  $('statPii').textContent = d.direct_pii_count;
  $('statPiiNote').textContent = `FP: ${d.fp_count} · TB: ${d.tb_count}`;
  $('statS26').textContent = (d.section26 || []).length;
  $('statS26Note').textContent = (d.section26 || []).map((s) => s.category).join(' · ') || 'none';
  $('statReid').textContent = Math.round(d.reid.score);
  $('statReidNote').textContent = `${d.reid.high_risk_combo ? 'High-risk combo' : 'Quasi-ID based'} · ${d.reid.grade}`;
  $('statQi').textContent = (d.reid.qi_found || []).length;
  $('statQiNote').textContent = (d.reid.qi_found || []).join(' · ') || 'none';

  // breakdown bars
  const bd = $('breakdown');
  bd.textContent = '';
  const items = d.breakdown || [];
  const maxCount = Math.max(1, ...items.map((i) => i.count));
  $('breakdownEmpty').classList.toggle('hidden', items.length > 0);
  items.forEach((it) => {
    const c = colorOf(it.data_type);
    const row = document.createElement('div'); row.className = 'bar-row';
    const head = document.createElement('div'); head.className = 'bar-head';
    const left = document.createElement('div'); left.className = 'left';
    const sq = document.createElement('div'); sq.className = `bar-sq`; sq.style.background = barColor(c);
    const name = document.createElement('span'); name.className = 'name'; name.textContent = it.data_type;
    const tag = document.createElement('span'); tag.className = `type-chip t-${c}`; tag.textContent = it.redact_type;
    left.append(sq, name, tag);
    const cnt = document.createElement('span'); cnt.className = 'cnt'; cnt.textContent = it.count;
    head.append(left, cnt);
    const track = document.createElement('div'); track.className = 'bar-track';
    const fill = document.createElement('div'); fill.className = 'bar-fill';
    fill.style.width = `${(it.count / maxCount) * 100}%`; fill.style.background = barColor(c);
    track.appendChild(fill);
    row.append(head, track);
    bd.appendChild(row);
  });

  // section 26
  const s26 = $('s26List'); s26.textContent = '';
  $('s26Empty').classList.toggle('hidden', (d.section26 || []).length > 0);
  (d.section26 || []).forEach((s) => {
    const row = document.createElement('div'); row.className = 's26-row';
    const head = document.createElement('div'); head.className = 's26-head';
    const dot = document.createElement('div'); dot.className = 's26-dot';
    const cat = document.createElement('span'); cat.className = 's26-cat'; cat.textContent = s.category;
    head.append(dot, cat);
    const quote = document.createElement('div'); quote.className = 's26-quote'; quote.textContent = `"${s.text}"`;
    const note = document.createElement('div'); note.className = 's26-note'; note.textContent = 'ต้องได้รับความยินยอมโดยชัดแจ้ง · §26';
    row.append(head, quote, note);
    s26.appendChild(row);
  });

  // quasi-identifiers
  const qi = $('qiWrap'); qi.textContent = '';
  (d.reid.qi_found || []).forEach((q) => {
    const chip = document.createElement('span'); chip.className = 'qi-chip'; chip.textContent = q;
    qi.appendChild(chip);
  });
  $('qiAlert').classList.toggle('hidden', !d.reid.high_risk_combo);

  // recommendations
  const rec = $('recommendations'); rec.textContent = '';
  (d.recommendations || []).forEach((r) => {
    const variant = r.level === 'high' ? 'red' : r.level === 'medium' ? 'amber' : 'blue';
    const icon = variant === 'blue' ? 'i' : '!';
    const row = document.createElement('div'); row.className = `rec rec-${variant}`;
    const ic = document.createElement('div'); ic.className = 'rec-icon'; ic.textContent = icon;
    const body = document.createElement('div');
    const title = document.createElement('div'); title.className = 'rec-title'; title.textContent = r.title;
    body.appendChild(title);
    if (r.desc) { const desc = document.createElement('div'); desc.className = 'rec-desc'; desc.textContent = r.desc; body.appendChild(desc); }
    row.append(ic, body);
    rec.appendChild(row);
  });
}

function barColor(c) {
  return { blue: '#2563EB', amber: '#D97706', sky: '#0EA5E9', purple: '#7C3AED' }[c] || '#2563EB';
}

// ── PDF Redact ──────────────────────────────────────────────
let pdfFile = null;

function handlePdf(file) {
  if (!file) return;
  if (file.type !== 'application/pdf') { showError($('pdfError'), 'รองรับเฉพาะไฟล์ PDF เท่านั้น'); return; }
  clearError($('pdfError'));
  pdfFile = file;
  $('pdfFileName').textContent = file.name;
  $('pdfFileName').classList.remove('hidden');
  analyzePdf();
}

async function analyzePdf() {
  if (!pdfFile) return;
  $('pdfLoading').classList.remove('hidden');
  $('pdfResult').classList.add('hidden');
  try {
    const form = new FormData();
    form.append('pdf_file', pdfFile);
    const res = await fetch('/api/redact-pdf', { method: 'POST', body: form });
    const d = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(d.detail || res.statusText);
    renderPdf(d);
    $('pdfResult').classList.remove('hidden');
    $('pdfDrop').classList.add('hidden');
  } catch (e) {
    showError($('pdfError'), 'เกิดข้อผิดพลาด: ' + e.message);
  } finally {
    $('pdfLoading').classList.add('hidden');
  }
}

const FIELD_LABELS = {
  NAME: 'ชื่อ', SURNAME: 'นามสกุล', THAI_ID: 'เลขบัตรประชาชน', DATE_OF_BIRTH: 'วันเกิด',
  ADDRESS: 'ที่อยู่', PHONE: 'เบอร์โทร', EMAIL: 'อีเมล', BANK_ACCOUNT: 'เลขบัญชีธนาคาร',
  CREDIT_CARD: 'บัตรเครดิต', PASSPORT: 'พาสปอร์ต', STUDENT_ID: 'รหัสนักศึกษา',
};

function renderPdf(d) {
  $('pdfDocName').textContent = d.filename || 'document.pdf';
  $('pdfDoneText').textContent = `${d.entity_count} PII fields detected. After download, these are permanently replaced with black boxes — original text is unrecoverable.`;

  const fields = d.fields || [];

  // redacted document sheet preview
  const sheet = $('pdfSheet'); sheet.textContent = '';
  const title = document.createElement('div'); title.className = 'pdf-sheet-title';
  title.innerHTML = '<div class="org">Prince of Songkla University</div><div class="h">แบบฟอร์มข้อมูลผู้เข้าร่วม</div><div class="sub">Participant Information Form</div>';
  sheet.appendChild(title);
  const fieldsWrap = document.createElement('div'); fieldsWrap.className = 'pdf-fields';
  (fields.length ? fields : [{ data_type: 'NAME' }, { data_type: 'THAI_ID' }, { data_type: 'PHONE' }]).forEach((f) => {
    const row = document.createElement('div'); row.className = 'row';
    const key = document.createElement('span'); key.className = 'key';
    key.textContent = (FIELD_LABELS[f.data_type] || f.data_type) + ':';
    const bb = document.createElement('span'); bb.className = 'blackbox';
    bb.style.width = (80 + Math.random() * 120) + 'px';
    row.append(key, bb);
    fieldsWrap.appendChild(row);
  });
  sheet.appendChild(fieldsWrap);

  // redacted fields list
  const rf = $('redactedFields'); rf.textContent = '';
  (fields.length ? fields : []).forEach((f) => {
    const row = document.createElement('div'); row.className = 'rf';
    const left = document.createElement('div'); left.className = 'left';
    const bb = document.createElement('div'); bb.className = 'bb';
    const name = document.createElement('span'); name.className = 'name'; name.textContent = FIELD_LABELS[f.data_type] || f.data_type;
    left.append(bb, name);
    const tag = document.createElement('span'); tag.className = `type-chip t-${colorOf(f.data_type)}`; tag.textContent = f.data_type;
    row.append(left, tag);
    rf.appendChild(row);
  });
}

function resetPdf() {
  pdfFile = null;
  $('pdfInput').value = '';
  $('pdfFileName').classList.add('hidden');
  $('pdfResult').classList.add('hidden');
  $('pdfDrop').classList.remove('hidden');
  clearError($('pdfError'));
}

// ── boot ────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  // nav
  document.querySelectorAll('.nav-item').forEach((b) => b.addEventListener('click', () => switchView(b.dataset.view)));

  // guard
  $('guardInput').value = SAMPLE;
  $('charCount').textContent = countChars(SAMPLE);
  $('guardInput').addEventListener('input', (e) => { $('charCount').textContent = countChars(e.target.value); });
  $('sanitizeBtn').addEventListener('click', sanitize);
  $('copyBtn').addEventListener('click', copySanitized);
  $('goRestoreBtn').addEventListener('click', () => goStep(3));
  $('restoreBtn').addEventListener('click', restore);
  $('resetBtn').addEventListener('click', resetGuard);
  $('step1').addEventListener('click', () => goStep(1));
  $('step2').addEventListener('click', () => goStep(2));
  $('step3').addEventListener('click', () => goStep(3));
  updateSteps();

  // report
  $('reportInput').value = SAMPLE;
  $('analyzeBtn').addEventListener('click', analyze);

  // pdf
  const dz = $('pdfDrop');
  dz.addEventListener('click', () => $('pdfInput').click());
  $('browseBtn').addEventListener('click', (e) => { e.stopPropagation(); $('pdfInput').click(); });
  $('pdfInput').addEventListener('change', () => handlePdf($('pdfInput').files[0]));
  dz.addEventListener('dragover', (e) => { e.preventDefault(); dz.classList.add('drag'); });
  dz.addEventListener('dragleave', () => dz.classList.remove('drag'));
  dz.addEventListener('drop', (e) => { e.preventDefault(); dz.classList.remove('drag'); handlePdf(e.dataTransfer.files[0]); });
  $('downloadBtn').addEventListener('click', () => alert('Demo: ในเวอร์ชันเต็ม ปุ่มนี้จะดาวน์โหลด PDF ที่ redact แล้วจาก pii_redactor/redactor.py'));
  $('pdfResetBtn').addEventListener('click', resetPdf);
});
