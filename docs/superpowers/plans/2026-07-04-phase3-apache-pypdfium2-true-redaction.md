# Phase 3 (Option B): Apache-2.0 + drop PyMuPDF, keep TRUE redaction — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`). This plan is **spike-gated**: Task 1 must succeed before Tasks 3+ are worth doing. If Task 1 fails, STOP and escalate to the human (the fallback is Option D in `specs/2026-07-04-phase3-5-decisions-roadmap.md`).

**Goal:** Remove the AGPL dependency (PyMuPDF/fitz) from the project so it can be licensed Apache-2.0, WITHOUT losing true redaction (redacted text must be unrecoverable, not just visually covered). Replace fitz with permissive libraries: `pypdfium2` (Apache/BSD, rendering), `pikepdf` (MPL, content-stream editing / text removal), `reportlab` (BSD, drawing black boxes).

**Architecture:** True redaction = draw an opaque black rectangle over each PII word bbox (reportlab overlay via pikepdf) AND remove the underlying text-showing operators from the page content stream (a custom `pikepdf.TokenFilter`). Page rendering (before/after PNG previews, hybrid-PDF page images for OCR) moves to `pypdfium2`. Word-bbox extraction for text-layer PDFs already uses `pdfplumber` (permissive) — only the fitz fallback + hybrid rendering need migrating.

**Tech Stack:** `pypdfium2`, `pikepdf`, `reportlab`, existing `pdfplumber`. Remove `pymupdf`.

## Global Constraints

- **True redaction is non-negotiable** (this is why Option B was chosen): after redaction, extracting text from the output PDF must NOT return the redacted words. Every redaction path needs a test asserting this.
- Keep the `/api/redact-pdf` response shape (adds no required fields; may add `redaction_mode`). Keep `redactor.redact_pdf(input_pdf_path, entity_registry, word_bboxes, output_path)` signature so `app/server.py` is unaffected.
- PyMuPDF/fitz usage sites to migrate: `pii_redactor/redactor.py`, `app/server.py` (before/after PNG), `pii_redactor/exporter.py` (`pdf_text` build), `pii_redactor/ingest/text_extractor.py` (`_extract_pdf_fitz` fallback + hybrid page render), `pii_redactor/ingest/ocr_processor.py` (page→image). After phase 3, `grep -ri "import fitz\|pymupdf" pii_redactor app` returns nothing.
- Windows; venv python: `PYTHONUTF8=1 ./.venv/Scripts/python.exe`. Work on a branch off main; finish with a PR.
- Do not regress the existing test suite (260+). The redaction tests live in `tests/test_step12_redact_pdf.py`.

---

### Task 1: SPIKE — prove text removal works (GATE; do this first, alone)

Prove that a `pikepdf.TokenFilter` can remove text at a bbox on a real text-layer PDF AND that the removed text is unrecoverable. This is the whole risk of Option B; do not build anything else until it passes.

**Files:**
- Create: `spikes/redaction_tokenfilter_spike.py` (throwaway; not shipped)
- Create: `tests/test_spike_redaction.py` (the acceptance test; kept)

**Interfaces:**
- Produces: a proven function `remove_text_in_bboxes(in_pdf, page_bboxes, out_pdf)` approach that Task 3 will adopt.

- [ ] **Step 1: Install the permissive libs**

```powershell
$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe -m pip install pypdfium2 pikepdf reportlab
```
(`pypdfium2` is already present from the sidecar build; `pikepdf` + `reportlab` may be new.)

- [ ] **Step 2: Write the acceptance test FIRST**

Create `tests/test_spike_redaction.py`. Use the existing sample-PDF helper (`examples/make_sample_pdf.py`) or `tests/test_step12_redact_pdf.py`'s fixtures to get a text-layer PDF containing a known token (e.g. the phone `0812345678`). The test:

```python
def test_tokenfilter_removes_text_unrecoverably(tmp_path):
    # 1. Build/копy a text-layer PDF containing "0812345678" at a known page+bbox.
    #    (reuse the fixture pattern from tests/test_step12_redact_pdf.py)
    # 2. Call the spike's remove_text_in_bboxes(in_pdf, {page: [bbox_of_phone]}, out_pdf)
    # 3. Extract text from out_pdf with pdfplumber and assert the phone is GONE:
    import pdfplumber
    with pdfplumber.open(str(out_pdf)) as pdf:
        text = "\n".join((p.extract_text() or "") for p in pdf.pages)
    assert "0812345678" not in text
```
(Fill in steps 1-2 with the real fixture + the spike import. The assertion in step 3 is the true-redaction proof.)

- [ ] **Step 3: Prototype `remove_text_in_bboxes` in `spikes/redaction_tokenfilter_spike.py`**

Implement using `pikepdf` content-stream tokens: iterate `page.Contents` tokens, track the text position via `Tm`/`Td`/`TJ` state, and drop `Tj`/`TJ`/`'`/`"` operators whose current text position falls inside a redaction bbox. Start from the pikepdf `TokenFilter` docs. This is the 200+-line hard part; expect to iterate. Also handle: pages whose `/Contents` is an array of streams (filter each); coordinate origin (PDF text space vs the pdfplumber `top`-based bbox — convert via page height).

- [ ] **Step 4: Run the acceptance test until it passes**

```powershell
$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe -m pytest tests/test_spike_redaction.py -v
```
Expected: PASS (redacted phone absent from extracted text).

- [ ] **Step 5: GATE decision**

- If Step 4 passes reliably on the sample PDF(s) → the approach is viable. Commit the spike + test (`git add spikes/ tests/test_spike_redaction.py; git commit -m "spike: prove pikepdf TokenFilter true text removal"`) and continue to Task 2.
- If it does NOT pass (text still recoverable, or the token-tracking is intractable for the target PDFs) → **STOP. Escalate to the human.** Option B is not achievable at acceptable cost; recommend falling back to Option D (permissive visual default + optional AGPL PyMuPDF for true redaction). Do not proceed to Tasks 2+.

---

### Task 2: pypdfium2 rendering helper (before/after PNG)

**Files:**
- Create: `pii_redactor/pdf_render.py`
- Test: `tests/test_pdf_render.py`

**Interfaces:**
- Produces: `render_page_png(pdf_path: str, page_index: int, scale: float = 2.0) -> bytes` (PNG bytes), replacing fitz `get_pixmap`.

- [ ] **Step 1: Failing test** — render a sample PDF's first page, assert non-empty PNG bytes starting with the PNG magic `\x89PNG`.
- [ ] **Step 2: Implement with pypdfium2**

```python
import io
import pypdfium2 as pdfium

def render_page_png(pdf_path: str, page_index: int = 0, scale: float = 2.0) -> bytes:
    pdf = pdfium.PdfDocument(pdf_path)
    try:
        page = pdf[page_index]
        pil = page.render(scale=scale).to_pil()
        buf = io.BytesIO()
        pil.save(buf, format="PNG")
        return buf.getvalue()
    finally:
        pdf.close()
```
- [ ] **Step 3: Test passes; commit.**

---

### Task 3: Rewrite `redactor.py` — black box overlay + true text removal

**Files:**
- Modify: `pii_redactor/redactor.py`
- Test: `tests/test_step12_redact_pdf.py`

**Interfaces:**
- Keep the exact signature `redact_pdf(input_pdf_path, entity_registry, word_bboxes, output_path) -> Path` (so `app/server.py` is unchanged).
- Consumes: the spike's proven text-removal approach (Task 1) + reportlab/pikepdf overlay.

- [ ] **Step 1: Add a "text not recoverable" test** to `tests/test_step12_redact_pdf.py`: redact a PDF with a phone/ID, then assert (a) the output renders (Task 2 PNG non-empty), and (b) `pdfplumber` text extraction of the output does NOT contain the redacted value.
- [ ] **Step 2: Reimplement `redact_pdf`** keeping `_build_redact_set` and the word-bbox matching logic (unchanged), but replacing the fitz body: for each page, (a) build a reportlab overlay PDF with black `rect()` at each matched bbox (convert pdfplumber `top` origin to reportlab bottom-left via page height), (b) merge via `pikepdf` `add_overlay`, (c) apply the Task-1 TokenFilter to remove the text at those bboxes, (d) save. Remove `import fitz`.
- [ ] **Step 3: Run `tests/test_step12_redact_pdf.py` until green** (both the existing tests and the new not-recoverable test). Commit.

---

### Task 4: Migrate the remaining fitz sites

**Files:**
- Modify: `pii_redactor/exporter.py` (`pdf_text` build → reportlab), `pii_redactor/ingest/text_extractor.py` (`_extract_pdf_fitz` + hybrid page render → pypdfium2), `pii_redactor/ingest/ocr_processor.py` (page→image → pypdfium2), `app/server.py` (before/after PNG → `pdf_render.render_page_png`).
- Tests: existing `tests/test_step8_export.py`, `tests/test_step1_ingest.py`, `tests/test_ocr.py`, `tests/test_step12_redact_pdf.py`.

- [ ] **Step 1:** For each site, replace the fitz call with the permissive equivalent (exporter: build a simple text PDF with reportlab; text_extractor fitz fallback: use `pypdfium2` textpage char boxes aggregated into words, OR since pdfplumber is the primary path, consider dropping the fitz fallback entirely if pdfplumber covers the test corpus — verify against `tests/test_step1_ingest.py`; ocr_processor + hybrid render: `pypdfium2 page.render`). Run each site's test after changing it.
- [ ] **Step 2:** `grep -ri "import fitz" pii_redactor app` returns nothing. Full suite green. Commit.

---

### Task 5: Requirements + license flip to Apache-2.0

**Files:**
- Modify: `requirements.txt` (remove `pymupdf`; add `pypdfium2`, `pikepdf`, `reportlab`)
- Create: `LICENSE` (Apache-2.0), `NOTICE`
- Modify: `README.md` (license section), `CLAUDE.md` (drop the "PyMuPDF is AGPL" note)

- [ ] **Step 1:** Update `requirements.txt`. Confirm nothing else imports fitz (`build_exe.ps1` also has `--collect-all pymupdf` → change to `--collect-all pypdfium2` + `--collect-all pikepdf`).
- [ ] **Step 2:** Add `LICENSE` (standard Apache-2.0 text) + `NOTICE` (attributions: pypdfium2/PDFium BSD, pikepdf MPL, reportlab BSD, pdfplumber MIT, PyThaiNLP). Update README with the Apache-2.0 badge + license section.
- [ ] **Step 3:** Full suite green (`pytest -q`); commit.

---

### Task 6: Full regression + sidecar rebuild verification

- [ ] **Step 1:** `PYTHONUTF8=1 ./.venv/Scripts/python.exe -m pytest -q` — all pass, including the not-recoverable redaction test.
- [ ] **Step 2:** Rebuild the sidecar (`./build_exe.ps1`) and smoke-test `/api/redact-pdf` end-to-end on a sample PDF (redacts + output text not recoverable). Confirm the exe no longer bundles PyMuPDF.
- [ ] **Step 3:** Commit; open the PR. PR body must state: license flipped to Apache-2.0, true redaction preserved + verified unrecoverable, fitz fully removed.

---

## Self-Review

- **Coverage:** all 5 fitz sites (redactor, server PNG, exporter, text_extractor, ocr_processor) → Tasks 3-4; license flip → Task 5; the hard true-removal → Task 1 spike gate + Task 3.
- **Honest risk:** Task 1 is a genuine spike — the exact TokenFilter code cannot be fully specified in advance (the research confirmed no off-the-shelf solution). The plan front-loads it as a GATE with an explicit escalate-to-Option-D fallback if it fails. This is deliberate, not a placeholder.
- **Invariant enforced:** every redaction path has a "text not recoverable" assertion (Tasks 1, 3) — Option B's whole point.
- **Signature stability:** `redact_pdf(...)` signature unchanged → `app/server.py` redaction call site untouched (only its PNG-render lines change in Task 4).
