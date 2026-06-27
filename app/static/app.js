const i18n = {
  en: {
    appName: 'AI Guard',
    tab1: 'AI Guard',
    tab2: 'PDPA Report',
    tab3: 'PDF Redact',
  
    step1Label: 'Your document',
    step1Placeholder: 'Paste your text here...',
    maskBtn: 'Mask PII',
    maskedLabel: 'Masked text',
    copyBtn: 'Copy',
    copied: 'Copied',
    entitiesMasked: (n) => `${n} ${n === 1 ? 'entity' : 'entities'} masked`,

    step2Title: 'Step 2 — Send to AI',
    step2Hint: 'Copy the masked text above and paste it into ChatGPT or Claude. When you receive the response, paste it below.',

    step3Label: 'AI response (with masked tokens)',
    step3Placeholder: 'Paste the AI response here...',
    restoreBtn: 'Restore',
    restoredLabel: 'Restored text',

    reportInputLabel: 'Text to analyze',
    reportInputPlaceholder: 'Paste your document here...',
    analyzeBtn: 'Analyze',
    reportTitle: 'PDPA Risk Report',
    riskLevel: 'Risk Level',
    totalEntities: 'Total entities',
    structuredPII: 'Structured PII',
    namedEntities: 'Named entities',
    entityTypes: 'Entity types',
    noEntities: 'No PII entities detected.',

    dropzoneText: 'Click to select a PDF, or drag and drop',
    dropzoneActive: 'Drop PDF here',
    analyzePdfBtn: 'Analyze PDF',
    pdfNote: 'Analysis only — the original file is not modified.',
    pdfResultLabel: 'Result',

    loading: 'Processing...',
    errorPrefix: 'Error: ',
    noText: 'Please enter some text first.',
    noFile: 'Please select a PDF file first.',
    onlyPdf: 'Only PDF files are supported.',
  },
  th: {
    appName: 'AI Guard',
    tab1: 'AI Guard',
    tab2: 'รายงาน PDPA',
    tab3: 'วิเคราะห์ PDF',

    step1Label: 'เอกสารของคุณ',
    step1Placeholder: 'วางข้อความที่นี่...',
    maskBtn: 'ปิดบัง PII',
    maskedLabel: 'ข้อความที่ปิดบังแล้ว',
    copyBtn: 'คัดลอก',
    copied: 'คัดลอกแล้ว',
    entitiesMasked: (n) => `พบ ${n} รายการที่ถูกปิดบัง`,

    step2Title: 'ขั้นตอนที่ 2 — ส่งให้ AI',
    step2Hint: 'คัดลอกข้อความที่ปิดบังแล้วนำไปวางใน ChatGPT หรือ Claude เมื่อได้รับคำตอบกลับมา ให้นำมาวางด้านล่าง',

    step3Label: 'คำตอบจาก AI (ที่มี token ปิดบัง)',
    step3Placeholder: 'วางคำตอบจาก AI ที่นี่...',
    restoreBtn: 'คืนค่า',
    restoredLabel: 'ข้อความที่คืนค่าแล้ว',

    reportInputLabel: 'ข้อความที่ต้องการวิเคราะห์',
    reportInputPlaceholder: 'วางเอกสารที่นี่...',
    analyzeBtn: 'วิเคราะห์',
    reportTitle: 'รายงานความเสี่ยง PDPA',
    riskLevel: 'ระดับความเสี่ยง',
    totalEntities: 'จำนวนรายการทั้งหมด',
    structuredPII: 'PII แบบมีรูปแบบ',
    namedEntities: 'ชื่อบุคคล/สถานที่',
    entityTypes: 'ประเภทข้อมูล',
    noEntities: 'ไม่พบข้อมูลส่วนบุคคล',

    dropzoneText: 'คลิกเพื่อเลือกไฟล์ PDF หรือลากมาวาง',
    dropzoneActive: 'วาง PDF ที่นี่',
    analyzePdfBtn: 'วิเคราะห์ PDF',
    pdfNote: 'วิเคราะห์เท่านั้น — ไฟล์ต้นฉบับไม่ถูกแก้ไข',
    pdfResultLabel: 'ผลลัพธ์',

    loading: 'กำลังประมวลผล...',
    errorPrefix: 'เกิดข้อผิดพลาด: ',
    noText: 'กรุณาใส่ข้อความก่อน',
    noFile: 'กรุณาเลือกไฟล์ PDF ก่อน',
    onlyPdf: 'รองรับเฉพาะไฟล์ PDF เท่านั้น',
  },
};

let lang = 'en';
let sessionId = null;
let pdfFile = null;

function t(key, ...args) {
  const val = i18n[lang][key];
  return typeof val === 'function' ? val(...args) : val;
}

function applyLang() {
  document.querySelectorAll('[data-i18n]').forEach(el => {
    const key = el.dataset.i18n;
    if (key) el.textContent = t(key);
  });
  document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
    const key = el.dataset.i18nPlaceholder;
    if (key) el.placeholder = t(key);
  });
  document.getElementById('langBtnEn').classList.toggle('active', lang === 'en');
  document.getElementById('langBtnTh').classList.toggle('active', lang === 'th');
}

function switchLang(newLang) {
  lang = newLang;
  applyLang();
  if (pdfFile) updateDropzoneLabel();
}

// Tab switching
function switchTab(name) {
  document.querySelectorAll('.tab-bar button').forEach(b => b.classList.toggle('active', b.dataset.tab === name));
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.toggle('active', p.id === 'tab-' + name));
}

// Copy to clipboard
function copyText(text, btn) {
  navigator.clipboard.writeText(text).then(() => {
    const orig = btn.textContent;
    btn.textContent = t('copied');
    setTimeout(() => { btn.textContent = orig; }, 1500);
  });
}

// Risk badge — uses DOM methods to avoid XSS from API-returned level value
function setRiskBadge(level) {
  const el = document.getElementById('riskBadge');
  el.textContent = '';
  const span = document.createElement('span');
  const cls = level === 'Low' ? 'badge-green' : level === 'Medium' ? 'badge-yellow' : 'badge-red';
  const label = lang === 'th'
    ? ({ Low: 'ต่ำ', Medium: 'ปานกลาง', High: 'สูง' }[level] || level)
    : level;
  span.className = `badge ${cls}`;
  span.textContent = label;
  el.appendChild(span);
}

function setError(el, msg) {
  el.textContent = msg;
  el.classList.remove('hidden');
}

function clearError(el) {
  el.textContent = '';
  el.classList.add('hidden');
}

// ── Tab 1: AI Guard ──────────────────────────────────────────────────────────

async function maskPII() {
  const input = document.getElementById('guardInput').value.trim();
  const errEl = document.getElementById('guardError');
  clearError(errEl);

  if (!input) { setError(errEl, t('noText')); return; }

  const btn = document.getElementById('maskBtn');
  btn.disabled = true;
  btn.textContent = t('loading');

  try {
    const res = await fetch('/api/sanitize', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: input, provider: 'fake' }),
    });
    if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
    const data = await res.json();
    sessionId = data.session_id;

    document.getElementById('maskedOut').textContent = data.pseudonymized_text;
    document.getElementById('maskCount').textContent = t('entitiesMasked', data.entity_count);
    document.getElementById('maskCount').classList.remove('hidden');
    document.getElementById('maskedSection').classList.remove('hidden');
    document.getElementById('step2Section').classList.remove('hidden');
    document.getElementById('step3Section').classList.remove('hidden');
    document.getElementById('guardResponseInput').value = data.pseudonymized_text;
  } catch (e) {
    setError(errEl, t('errorPrefix') + e.message);
  } finally {
    btn.disabled = false;
    btn.setAttribute('data-i18n', 'maskBtn');
    btn.textContent = t('maskBtn');
  }
}

async function restorePII() {
  const input = document.getElementById('guardResponseInput').value.trim();
  const errEl = document.getElementById('restoreError');
  clearError(errEl);

  if (!input) { setError(errEl, t('noText')); return; }

  const btn = document.getElementById('restoreBtn');
  btn.disabled = true;
  btn.textContent = t('loading');

  try {
    const res = await fetch('/api/reidentify', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: input, provider: 'fake' }),
    });
    if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
    const data = await res.json();

    document.getElementById('restoredOut').textContent = data.restored_text;
    document.getElementById('restoredSection').classList.remove('hidden');
  } catch (e) {
    setError(errEl, t('errorPrefix') + e.message);
  } finally {
    btn.disabled = false;
    btn.setAttribute('data-i18n', 'restoreBtn');
    btn.textContent = t('restoreBtn');
  }
}

// ── Tab 2: PDPA Report ───────────────────────────────────────────────────────

async function analyzeText() {
  const input = document.getElementById('reportInput').value.trim();
  const errEl = document.getElementById('reportError');
  clearError(errEl);

  if (!input) { setError(errEl, t('noText')); return; }

  const btn = document.getElementById('analyzeBtn');
  btn.disabled = true;
  btn.textContent = t('loading');

  try {
    const res = await fetch('/api/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: input }),
    });
    if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
    const data = await res.json();
    renderReport(data);
    document.getElementById('reportCard').classList.remove('hidden');
  } catch (e) {
    setError(errEl, t('errorPrefix') + e.message);
  } finally {
    btn.disabled = false;
    btn.setAttribute('data-i18n', 'analyzeBtn');
    btn.textContent = t('analyzeBtn');
  }
}

function renderReport(data) {
  setRiskBadge(data.risk_level);
  document.getElementById('totalCount').textContent = data.entity_count;
  document.getElementById('fpCount').textContent = data.fp_count;
  document.getElementById('tbCount').textContent = data.tb_count;

  const pillsEl = document.getElementById('entityPills');
  pillsEl.textContent = '';
  if (data.entity_count === 0) {
    const pill = document.createElement('span');
    pill.className = 'entity-pill';
    pill.textContent = t('noEntities');
    pillsEl.appendChild(pill);
  } else {
    Object.entries(data.entity_types || {}).forEach(([type, count]) => {
      const pill = document.createElement('span');
      pill.className = 'entity-pill';
      pill.textContent = `${type.replace(/_/g, ' ')} ×${count}`;
      pillsEl.appendChild(pill);
    });
  }
}

// ── Tab 3: PDF Redact ────────────────────────────────────────────────────────

function updateDropzoneLabel() {
  const label = document.getElementById('dropzoneFile');
  label.textContent = pdfFile ? pdfFile.name : '';
  label.classList.toggle('hidden', !pdfFile);
}

function handleFileSelect(file) {
  if (!file) return;
  if (file.type !== 'application/pdf') {
    setError(document.getElementById('pdfError'), t('onlyPdf'));
    return;
  }
  clearError(document.getElementById('pdfError'));
  pdfFile = file;
  updateDropzoneLabel();
}

function setupDropzone() {
  const zone = document.getElementById('dropzone');
  const input = document.getElementById('pdfInput');

  zone.addEventListener('click', () => input.click());
  input.addEventListener('change', () => handleFileSelect(input.files[0]));

  zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('drag-over'); });
  zone.addEventListener('dragleave', () => zone.classList.remove('drag-over'));
  zone.addEventListener('drop', e => {
    e.preventDefault();
    zone.classList.remove('drag-over');
    handleFileSelect(e.dataTransfer.files[0]);
  });
}

async function analyzePDF() {
  const errEl = document.getElementById('pdfError');
  clearError(errEl);

  if (!pdfFile) { setError(errEl, t('noFile')); return; }

  const btn = document.getElementById('analyzePdfBtn');
  btn.disabled = true;
  btn.textContent = t('loading');

  try {
    const form = new FormData();
    form.append('pdf_file', pdfFile);

    const res = await fetch('/api/redact-pdf', { method: 'POST', body: form });
    if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
    const data = await res.json();

    document.getElementById('pdfResult').textContent =
      `${t('entitiesMasked', data.entity_count)} — ${data.message}`;
    document.getElementById('pdfResultSection').classList.remove('hidden');
  } catch (e) {
    setError(errEl, t('errorPrefix') + e.message);
  } finally {
    btn.disabled = false;
    btn.setAttribute('data-i18n', 'analyzePdfBtn');
    btn.textContent = t('analyzePdfBtn');
  }
}

// ── Boot ─────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  applyLang();
  setupDropzone();

  document.getElementById('langBtnEn').addEventListener('click', () => switchLang('en'));
  document.getElementById('langBtnTh').addEventListener('click', () => switchLang('th'));
  document.querySelectorAll('.tab-bar button').forEach(b => {
    b.addEventListener('click', () => switchTab(b.dataset.tab));
  });

  document.getElementById('maskBtn').addEventListener('click', maskPII);
  document.getElementById('restoreBtn').addEventListener('click', restorePII);
  document.getElementById('analyzeBtn').addEventListener('click', analyzeText);
  document.getElementById('analyzePdfBtn').addEventListener('click', analyzePDF);

  document.getElementById('copyMaskedBtn').addEventListener('click', () => {
    const text = document.getElementById('maskedOut').textContent;
    copyText(text, document.getElementById('copyMaskedBtn'));
  });
  document.getElementById('copyRestoredBtn').addEventListener('click', () => {
    const text = document.getElementById('restoredOut').textContent;
    copyText(text, document.getElementById('copyRestoredBtn'));
  });
});
