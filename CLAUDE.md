# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Thai PII detection and redaction system for PSU Future Tech Challenge 2026 (AI Innovation for Future Society, DIIS / PSU Cybersecurity & AI & Data Privacy Day). Prototype-level entry; submission deadline 29 June 2026, poster presentation 10 July 2026.

Two modes:
- **True redaction**: permanently black-box PII at bbox level in PDF
- **AI Guard**: pseudonymize PII with tokens before sending to external AI, re-identify locally from vault after response

Deliverables are an MS Form, one-page A4 doc, <=5 min video, and A1 poster (source code not required).

## Environment Setup

Windows console is cp1252 by default - set UTF-8 before every Python invocation:

```powershell
$env:PYTHONUTF8='1'
```

Use the venv directly (activation does not persist across tool calls):

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -r requirements-web.txt   # FastAPI/uvicorn
.\.venv\Scripts\python.exe -m pip install -r requirements-ml.txt    # WangchanBERTa (torch)
```

Thai font: `C:\Windows\Fonts\sarabun-v17-...-regular.ttf`

## Running

```powershell
# Local API backend (what the browser extension talks to).
# run.ps1 creates the venv + installs deps on first run, then starts uvicorn.
./run.ps1                      # Windows
# ./run.sh                     # git-bash / Linux / macOS

# Or directly:
$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe -m uvicorn app.server:app --port 8000

# CLI demo
$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe demo_cli.py
$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe ai_guard.py report --mode surrogate

# Tests
$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe -m pytest
$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe -m pytest tests/test_foo.py::test_name -v
```

**Browser extension** (primary UI): start the backend (above), then load `extension/`
unpacked in Chrome (`chrome://extensions` → Developer mode → Load unpacked). See
`extension/README.md`. The extension calls the backend cross-origin, so the server
enables permissive CORS (`app/server.py`).

## Architecture: "Single Brain, Multiple Storefronts"

One core pipeline (`pii_redactor/`) exposed via two storefronts over one shared backend:

| Storefront | Entry point |
|---|---|
| Browser extension (primary UI) | `extension/` (MV3: in-page Mask/Restore bar on ChatGPT/Claude/Gemini/Grok/Perplexity/GLM·Z.ai + docked side panel via `chrome.sidePanel`; per-site DOM selectors in `sites.js` with a generic fallback) |
| CLI | `demo_cli.py`, `ai_guard.py` |

Both sit on the **FastAPI backend** `app/server.py` (`/api/*`). The extension is the
product's front door; the backend is API-only (no web frontend) and runs on localhost.
`/` redirects to `/docs` (Swagger). The extension's service worker calls the backend, so
CORS is enabled. The browser never holds the vault — only the `session_id`; the
token → original map lives in the backend's in-memory `_SESSIONS` (`app/server.py`).

### Pipeline (Step 1-8 per design doc `step1-7_*.pdf`; the file name undercounts — the doc itself documents 8 steps)

**Step 1 - Ingest & Validate**

File type detection routes to one of three sub-paths:

- **Plain text**: input validation (language, size, Thai support) → encoding validation (all text normalized to UTF-8)
- **Text-layer PDF**: check if openable → extract text via pdfplumber/pypdfium2 → store word bboxes `(page, x, y, width, height)` for later PDF redaction
- **Hybrid/scanned PDF** (`pii_redactor/ingest/ocr_processor.py`): **per-page**, not whole-document — a page with a real text layer is extracted directly (same path as Text-layer PDF); an image-only page goes through PaddleOCR with image pre-processing (deskew, denoise, unsharp-mask sharpen) → confidence check; retries up to 3 times (escalating DPI/binarization) while confidence < 70%, then sets a `human_review` flag → produces the same `(page, x, y, width, height)` bboxes as the other paths. Optional dependency (`requirements-ocr.txt`); raises `OCRUnavailableError` if not installed. `text_extractor.extract()` returns `(text, word_bboxes, meta)` for every source type — `meta` carries `ocr_confidence`/`human_review`/`pages_ocred`/`pages_text_layer`/`warnings` (empty dict for `text`/`pdf_text`).

All paths converge at language detection (Thai primary, English minimum).

**Text Cleaning Pipeline** (runs after ingest):
1. Whitespace normalization (collapse repeats, remove blank lines)
2. Unicode normalization (decompose → canonical form)
3. Character standardization (Thai character shape variants: พ/ว/อ/น forms)
4. Broken word recovery (PyThaiNLP dictionary)
5. OCR error detection (flag likely OCR substitutions: `2→Z`, `0→O`, `8→B`)
6. Broken sentence detection: algorithm identifies candidates only, does not auto-fix; pauses pipeline for user review (shows candidates, waits for confirm); on timeout or skip → use original text + log as skipped
7. Post-clean encoding check

**Data Quality Validation** (before PII detection):
- Pattern validation, structure validation, OCR confidence validation, quality scoring
- Output: **Normalized Document Model** (structured text + metadata + word bboxes)

**Step 2 - PII Detection** (`pii_redactor/detectors/`)

Two parallel detection passes on the Normalized Document Model:

- **Format-Preserving (FP)**: regex + checksum for structured PII
  - Thai national ID (mod-11 Luhn), phone, email, bank account, credit card, IBAN, passport, vehicle plate, student ID, date of birth
  - High confidence - pattern match alone is sufficient
- **Text-Based (TB)**: NER + context classifier
  - PyThaiNLP thainer-CRF (`NER(engine="thainer")`) — the default, fast, fully offline. An opt-in WangchanBERTa engine (`AIGUARD_NER_ENGINE=wangchanberta`, maps to `NER(engine="thainer-v2")`) is available for higher recall at a real cost: ~1.3s/sentence on CPU vs near-instant for CRF. Selected once per process via env var, not per-request; fails loudly (`NEREngineUnavailableError`) rather than silently falling back if `transformers` isn't installed.
  - Name recall booster: `detectors/name_context.py` (`detect_name_context`, merged inside `detect_tb`) — token-level title/label cues (นาย/นาง/นางสาว/…, ผมชื่อ…, ลงชื่อ) capture names the CRF misses or clips; works on tokens so it ignores substrings like "นายก"/"คุณภาพ".
  - Sliding window ±3 sentences for context (NER is ambiguous without surrounding context)
  - Targets via thainer labels: name (PERSON), address (LOCATION), date (DATE)
  - Span chokepoint: reject spans < 2 characters (prevents single-char NER false positives)
- **Sensitive semantic (optional)**: `sensitive_detector.py` — MiniLM sentence-embedding similarity flags free-form PDPA Section 26 content (health, religion, etc.) the keyword scan misses. Non-generative (flags existing spans only). Requires `requirements-ml.txt`; degrades to no-op when absent.

Post-detection:
- Span boundary adjustment + deduplication (map repeated entities to original)
- False negative scan: lightweight second pass (13-digit, `@`, date patterns)
- **Entity Registry**: `entity_id`, `redact_type` (FP/TB), `data_type`, `span`, `score`
- Output: Detection Report → Step 3

**Step 3 - Pseudonymization** (`pii_redactor/anonymizer/`)

Session mapping table (in-memory only, never written to disk; keyed by `entity_id`):
- If entity already in table → reuse existing pseudonym (consistency)
- If new entity → route by `redact_type`:
  - **FP**: `anonymizer/fp_generator.py` `generate_fp()` — format-preserving generator per `data_type` (valid checksum, SHA256-seeded per entity for reproducibility; no LLM)
  - **TB**: `anonymizer/tb_generator.py` `generate_tb()` — realistic Thai names/addresses from local hardcoded pools, seeded per entity (no LLM; nothing is sent anywhere)

Replace real data using bboxes from entity registry → consistency check (same entity everywhere) → post-replace scan (verify no real PII remains; halt + alert if found).

Output: **Pseudonymized Document** + session mapping table (for re-identification) → Step 4 (send to AI)

**Step 4 - Session mapping table** (`pii_redactor/session_vault.py`, `SessionVault`)

In-memory only (never persisted), keyed by `entity_id`, with a reverse index keyed by pseudonym for Step 6. Idle timeout (default 1800s) raises `VaultTimeoutError` on read; `snapshot()`/`restore()` support rollback around a failed AI call; `clear()` overwrites `original` with null bytes before dropping references. Its own internal audit log records only `{action, entity_id, timestamp, session_id}` — no PII.

**Step 5 - Send to AI** (`pii_redactor/ai_client.py`, `send_to_ai`)

`AIProvider` implementations: `FakeLLMProvider` (identity, for tests/dry-runs), `OllamaProvider`, `ClaudeProvider` (needs `ANTHROPIC_API_KEY`). Pre-send guard `_validate_pre_send` re-scans the pseudonymized text with `detect_fp` **and** `detect_tb` (excluding known pseudonyms) and raises `PreSendValidationError` on any real leak, plus a prompt-size check and a vault idle check. Retries up to 3x with exponential backoff on transient network errors; any other exception rolls back the vault snapshot and re-raises. `_validate_response` warns (does not halt) if an expected pseudonym is missing from the AI's reply.

**Step 6 - Reverse mapping** (`pii_redactor/reverse_mapper.py`, `reverse_map`)

Restores originals into the AI's response using the vault's pseudonym→original reverse index, replacing **longest pseudonym first** to avoid partial-match corruption (e.g. an email pseudonym vs. its username substring). Post-reverse validation flags pseudonym residue and incomplete replacement (`replaced_count < total_entities`) without halting; both surface in `ReverseResult.audit_summary`.

**Step 7 - Output validation** (`pii_redactor/output_validator.py` + `pii_redactor/audit.py`)

Three layers: Layer 1 re-scans the restored text with `detect_fp` for anything not in the vault's known-originals set and **raises `PIILeakError`** immediately if found (this layer only runs `detect_fp`, not `detect_tb`, since TB-type PII — names/addresses — is expected to be present post-restore). Layer 2 surfaces completeness/residue flags (never halts). Layer 3 checks UTF-8 encodability and a truncation heuristic, setting `halt=True` (but not raising) on failure — the caller (`exporter.py`) turns that into an `ExportError`. `audit.py` writes disk-based JSONL process/security logs (step, entity counts, flags, latency / layer, scan result, retry/rollback counts) — a broader, PII-free schema than the vault's own internal log; note `pipeline.py` does not currently call into `audit.py` itself.

**Step 8 - Export** (`pii_redactor/exporter.py`, `export`)

Writes `.txt` or `.pdf_text` (a fresh reportlab-built text dump of the final de-identified string — unrelated to `redactor.py`'s flatten-to-image blackout of an original PDF). Halts via `ExportError` if `validation_result.halt`, format unsupported, or output exists without `overwrite=True`.

All 8 steps are wired together by `pii_redactor/pipeline.py`'s `run_pipeline()` and each has a dedicated test file (`tests/test_step4_vault.py` … `tests/test_step9_pipeline.py` for the full integration).

### Key Modules

| Module | Purpose |
|---|---|
| `pii_redactor/pipeline.py` | CLI pipeline orchestrator (`run_pipeline`); calls `send_to_ai` |
| `pii_redactor/detectors/` | FP (regex/checksum), TB (thainer CRF NER), FN scanner |
| `pii_redactor/anonymizer/` | Package: `anonymizer.py` (vault replace), `fp_generator.py` + `tb_generator.py` (valid-format / Thai fake values) |
| `pii_redactor/redactor.py` | True PDF redaction via bbox black boxes (wired through `/api/redact-pdf`) |
| `pii_redactor/reid_risk.py` | Quasi-identifier re-identification risk score (Sweeney model), 0-100 + grade |
| `pii_redactor/report.py` | PDPA risk report; `scan_section26` keyword flags (not auto-redacted) |
| `pii_redactor/sensitive_detector.py` | Optional MiniLM semantic Section-26 detector (non-generative); no-op without `requirements-ml.txt` |
| `pii_redactor/session_vault.py` | Step 4: in-memory `SessionVault` (pseudonym↔original), idle timeout, snapshot/restore rollback |
| `pii_redactor/ai_client.py` | Step 5: AI providers (Fake/Ollama/Claude) + pre-send leak guard (`detect_fp`+`detect_tb`) + retry/rollback |
| `pii_redactor/reverse_mapper.py` | Step 6: restores originals into the AI response, longest-pseudonym-first |
| `pii_redactor/output_validator.py` | Step 7: 3-layer post-reverse validation (PII leak / completeness / integrity) |
| `pii_redactor/audit.py` | Step 7: disk JSONL process/security logs (step/counts/flags/latency; no PII) — distinct from `SessionVault`'s own internal `{entity_id, action, timestamp}` log |
| `pii_redactor/exporter.py` | Step 8: writes final `.txt`/`.pdf_text` output |
| `pii_redactor/models.py` | Shared dataclasses (`Entity`, `EntityRegistry`, `WordBbox`, `VaultRecord`, `AIResponse`, `ReverseResult`, ...) |
| `pii_redactor/ingest/ocr_processor.py` | Step 1 (hybrid/scanned PDFs): per-page PaddleOCR extraction, deskew/denoise/sharpen preprocessing, retry x3 → `human_review` flag. Optional (`requirements-ocr.txt`); raises `OCRUnavailableError` if not installed |

Roadmap (not implemented): Presidio bridge.

### Web API Endpoints (`app/server.py`, v2 token-mode contract)

- `GET /api/health` → `{status, version}`
- `POST /api/sanitize {text, mode}` → `{session_id, original_text, sanitized_text, entities[], entity_type_counts, section26[]}`. `mode="token"` (default) → `[ชื่อ_1]`; `mode="surrogate"` → realistic valid-format fake data (reads naturally to the AI). Stores the pseudonym → original map in the in-memory `_SESSIONS` keyed by `session_id`.
- `POST /api/reidentify {session_id, text}` → `{restored_text, replaced[], replaced_count, leftover_tokens}` — restores pseudonyms from the stored session map (mode-agnostic).
- `POST /api/analyze {text}` → full PDPA report `{overall_score, overall_grade, risk_label, direct_pii_count, fp_count, tb_count, section26[], reid, breakdown[], recommendations[]}`. `section26[]` merges keyword hits with optional MiniLM semantic hits (`source:"semantic"`).
- `POST /api/redact-pdf` (multipart `pdf_file`) → `{filename, source_type, ocr_confidence, human_review, ocr_warnings, entity_count, fields[], section26[], redacted_pdf_b64, before_png_b64, after_png_b64}`. Detects on RAW extracted text (bboxes align), draws black boxes via `pii_redactor/redactor.py`, returns the redacted PDF + page previews. Routes both text-layer and scanned/hybrid PDFs via `detect_source_type()`; returns HTTP 503 if a scanned PDF needs OCR and `requirements-ocr.txt` isn't installed.

Note: the web API uses its own token/surrogate path (`_tokenize` + in-memory `_SESSIONS` in `app/server.py`), distinct from the CLI `pipeline.py`/`SessionVault`. Both are tested; they are not unified.

## Design Invariants

- **Recall > Precision**: prefer false positives over missed PII
- **Vault never leaves device**: pseudonym → original map is in-memory only (`_SESSIONS` web / `SessionVault` CLI); the extension keeps only `session_id`. `leftover_tokens` check on re-identification.
- **Pre-send leak guard**: before any send to an external AI, `ai_client._validate_pre_send` re-scans outbound text with `detect_fp` AND `detect_tb`; a real (non-pseudonym) hit halts the send.
- **PDPA Section 26 sensitive categories**: flagged/reported only (`report.scan_section26` keyword + optional `sensitive_detector` semantic), never auto-redacted.
- **Non-generative sensitive detection**: `sensitive_detector` flags only spans present in the source (embedding similarity), so it cannot hallucinate PII.
- **NER span filter**: reject any entity span < 2 characters before it reaches redaction.

## Requirements Split

- `requirements.txt` - core (pypdfium2, reportlab, Pillow, pdfplumber, PyThaiNLP, regex, httpx). httpx is core (not web-only) because `pii_redactor/ai_client.py` — imported by the core `pipeline.py` for `OllamaProvider`/`ClaudeProvider` — needs it unconditionally; it used to live only in `requirements-web.txt`, which broke a core-only install.
- `requirements-web.txt` - web (fastapi, uvicorn, requests)
- `requirements-ml.txt` - sentence-transformers + torch/transformers (MiniLM sensitive detector; WangchanBERTa engine is roadmap). Install only when the semantic detector is needed.
- `requirements-ocr.txt` - paddlepaddle + paddleocr + opencv-python-headless (scanned/hybrid PDF OCR, `pii_redactor/ingest/ocr_processor.py`). Install only when OCR-ing scanned PDFs is needed; excluded from the packaged `AIGuard.exe` (same treatment as `requirements-ml.txt`).

Note: licensed under Apache-2.0 (see LICENSE/NOTICE). PDF handling uses the permissive pypdfium2 / reportlab / pdfplumber; PyMuPDF (AGPL) was removed in phase 3 (redaction is now flatten-to-image).
