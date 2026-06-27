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
| Browser extension (primary UI) | `extension/` (MV3: in-page Mask/Restore bar + popup on ChatGPT/Claude) |
| CLI | `demo_cli.py`, `ai_guard.py` |

Both sit on the **FastAPI backend** `app/server.py` (`/api/*`). The extension is the
product's front door; the backend is API-only (no web frontend) and runs on localhost.
`/` redirects to `/docs` (Swagger). The extension's service worker calls the backend, so
CORS is enabled. The browser never holds the vault — only the `session_id`; the
token → original map lives in the backend's in-memory `_SESSIONS` (`app/server.py`).

### Pipeline (Step 1-7 per design doc `step1-7_*.pdf`)

**Step 1 - Ingest & Validate**

File type detection routes to one of three sub-paths:

- **Plain text**: input validation (language, size, Thai support) → encoding validation (all text normalized to UTF-8)
- **Text-layer PDF**: check if openable → extract text via pdfplumber/PyMuPDF → store word bboxes `(page, x, y, width, height)` for later PDF redaction
- **Hybrid/scanned PDF**: page image analysis → PaddleOCR with image pre-processing (normalize, deskew, denoise, sharpen) → OCR quality validation (confidence score, error check, text quality); retry up to 3 times, then `flag: human review` → store word bboxes

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
  - WangchanBERTa (`pythainlp/thainer-corpus-v2-base-model`) or PyThaiNLP thainer-CRF (CRF is default, faster; WangchanBERTa requires `requirements-ml.txt`)
  - Sliding window ±3 sentences for context (NER is ambiguous without surrounding context)
  - Targets: name, surname, address, ethnicity, political opinion, religion, criminal history, health data, disability, union membership (PDPA Section 26 sensitive categories)
  - Span chokepoint: reject spans < 2 characters (prevents WangchanBERTa single-char false positives with score 1.0)

Post-detection:
- Span boundary adjustment + deduplication (map repeated entities to original)
- False negative scan: lightweight second pass (13-digit, `@`, date patterns)
- **Entity Registry**: `entity_id`, `redact_type` (FP/TB), `data_type`, `span`, `score`
- Output: Detection Report → Step 3

**Step 3 - Pseudonymization** (`pii_redactor/anonymizer.py`, `pii_redactor/surrogate.py`)

Session mapping table (in-memory only, never written to disk; keyed by `entity_id`):
- If entity already in table → reuse existing pseudonym (consistency)
- If new entity → route by `redact_type`:
  - **FP**: format-preserving generator per `data_type` (preserves prefix/format, generates valid checksum, fixed seed per entity for reproducibility)
  - **TB**: LLM generator (separate endpoint; sends only `type + context`, never real data; generates realistic Thai names/addresses/places)

Replace real data using bboxes from entity registry → consistency check (same entity everywhere) → post-replace scan (verify no real PII remains; halt + alert if found).

Output: **Pseudonymized Document** + session mapping table (for re-identification) → Step 4 (send to AI)

**Steps 4-7**: see `step1-7_*.pdf` design doc in repo root (not yet implemented).

### Key Modules

| Module | Purpose |
|---|---|
| `pii_redactor/pipeline.py` | Main pipeline orchestrator, `build_payload` for AI |
| `pii_redactor/detectors/` | FP (regex/checksum) and TB (NER) detectors |
| `pii_redactor/anonymizer.py` | Pseudonymization, session vault |
| `pii_redactor/surrogate.py` | Realistic fake data with valid checksums; `pseudonymize(surrogate=True)` |
| `pii_redactor/redactor.py` | True PDF redaction via bbox black boxes |
| `pii_redactor/reid_risk.py` | Quasi-identifier re-identification risk score (Sweeney model), 0-100 + grade |
| `pii_redactor/report.py` | PDPA risk report; Section 26 sensitive categories flagged (keyword), not auto-redacted |
| `pii_redactor/presidio_bridge.py` | Presidio Thai recognizer + checksum validator |
| `pii_redactor/llm_detector.py` | LLM-based detection with anti-hallucination (only accepts spans present verbatim in source) |
| `pii_redactor/wangchanberta.py` | Optional WangchanBERTa NER wrapper |
| `pii_redactor/audit.py` | Audit log |

### Web API Endpoints (`app/server.py`, v2 token-mode contract)

- `GET /api/health` → `{status, version}`
- `POST /api/sanitize {text}` → `{session_id, original_text, sanitized_text, entities[], entity_type_counts, section26[]}` — token-mode pseudonymization (`[ชื่อ_1]`); stores the token → original map in the in-memory `_SESSIONS` keyed by `session_id`.
- `POST /api/reidentify {session_id, text}` → `{restored_text, replaced[], replaced_count, leftover_tokens}` — restores tokens from the stored session map.
- `POST /api/analyze {text}` → full PDPA report `{overall_score, overall_grade, risk_label, direct_pii_count, fp_count, tb_count, section26[], reid, breakdown[], recommendations[]}`.
- `POST /api/redact-pdf` (multipart `pdf_file`) → `{filename, entity_count, fields[], section26[]}` (analysis for the redaction view; bbox redaction itself is in `pii_redactor/redactor.py`).

## Design Invariants

- **Recall > Precision**: prefer false positives over missed PII
- **Vault never leaves device**: session mapping table is in-memory only; `leftover_tokens` check on re-identification
- **AI payload integrity**: `build_payload` instructs AI to keep tokens (e.g. `[ชื่อ_1]`) intact
- **PDPA Section 26 sensitive categories**: flagged and reported via `report.py`, not auto-redacted (only keyword/flag detection via `detect_all(use_sensitive=True)`)
- **LLM anti-hallucination**: LLM detector output filtered to spans that exist verbatim in source text
- **WangchanBERTa span filter**: reject any entity span < 2 characters before it reaches redaction

## Requirements Split

- `requirements.txt` - core (PyMuPDF, pdfplumber, PyThaiNLP, regex)
- `requirements-web.txt` - web (fastapi, uvicorn, requests)
- `requirements-ml.txt` - WangchanBERTa (torch, transformers, sentencepiece); install only when ML model needed

Note: PyMuPDF is AGPL licensed.
