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
$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe ai_guard.py report examples\prompts\02_medical_consult.txt
$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe ai_guard.py sanitize examples\prompts\01_sick_leave_email.txt
# (token/surrogate `mode` is a web-API concept — POST /api/sanitize — not a CLI flag)

# Tests (Python)
$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe -m pytest
$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe -m pytest tests/test_foo.py::test_name -v

# Tests (JS — extension harness, vitest+jsdom; needs `npm install` once)
npm run test:js

# Tests (Rust — Tauri shell incl. sidecar kill-sequence tests)
cd desktop/src-tauri; cargo test
```

JS harness note: `extension/sites.js` carries an additive CommonJS export shim
(`module.exports` — dead code in Chrome) exposing `selectFor(hostname)` + every
site config so `extension/tests/` can pin selector behavior against the DOM
fixtures in `extension/tests/fixtures/`. Playwright live-DOM checks and the
selector-drift badge are roadmap (Horizon-2 #13 รอบถัดไป).

**Browser extension** (primary UI): start the backend (above), then load `extension/`
unpacked in Chrome (`chrome://extensions` → Developer mode → Load unpacked). See
`extension/README.md`. The extension calls the backend cross-origin; the server's CORS
is a strict allowlist (`allow_origin_regex` for `chrome-extension://`, `moz-extension://`,
and Tauri origins only — not `*`) plus `TrustedHostMiddleware` limited to
localhost/127.0.0.1 (`app/server.py`).

## Architecture: "Single Brain, Multiple Storefronts"

One core pipeline (`pii_redactor/`) exposed via two storefronts over one shared backend:

| Storefront | Entry point |
|---|---|
| Browser extension (primary UI) | `extension/` (MV3: in-page Mask/Restore bar on ChatGPT/Claude/Gemini/Grok/Perplexity/GLM·Z.ai + docked side panel via `chrome.sidePanel`; per-site DOM selectors in `sites.js` with a generic fallback) |
| CLI | `demo_cli.py`, `ai_guard.py` |

Both sit on the **FastAPI backend** `app/server.py` (`/api/*`). The extension is the
product's front door; the backend is API-only (no web frontend) and runs on localhost.
`/` redirects to `/docs` (Swagger). The extension's service worker calls the backend;
CORS allows only extension/Tauri origins (strict allowlist, see above). The browser never holds the vault — only the `session_id`; the
token → original map lives in the backend's in-memory `SessionService` sessions
(`pii_redactor/session_service.py`, one `SessionVault` per session).

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
3. Character standardization (Thai digits → Arabic digits, strip zero-width characters)
4. Broken word recovery (PyThaiNLP dictionary)
5. OCR error detection (flag likely OCR substitutions: `2→Z`, `0→O`, `8→B`)
6. Broken sentence detection: algorithm identifies candidates only, does not auto-fix; pauses pipeline for user review (shows candidates, waits for confirm); on timeout or skip → use original text + log as skipped
7. Post-clean encoding check

**Data Quality Validation** (before PII detection):
- Pattern validation, structure validation, OCR confidence validation, quality scoring
- Output: **Normalized Document Model** (structured text + metadata + word bboxes)

Note on the CLI orchestrator: `run_pipeline()` calls the quality validator for information
only (result is not stored on `PipelineResult` and never halts), and it drops PDF word
bboxes — CLI export is always text-based. Bbox-level true redaction is wired only through
`POST /api/redact-pdf` → `pii_redactor/redactor.py`.

**Step 2 - PII Detection** (`pii_redactor/detectors/`)

Two parallel detection passes on the Normalized Document Model:

- **Format-Preserving (FP)**: regex + checksum for structured PII
  - Thai national ID (mod-11 Luhn), phone, email, bank account, credit card, IBAN, passport, vehicle plate, student ID, date of birth
  - High confidence - pattern match alone is sufficient
- **Text-Based (TB)**: NER + context classifier
  - PyThaiNLP thainer-CRF (`NER(engine="thainer")`) — the default, fast, fully offline. An opt-in WangchanBERTa engine (`AIGUARD_NER_ENGINE=wangchanberta`, maps to `NER(engine="thainer-v2")`) is available for higher recall at a real cost: ~1.3s/sentence on CPU vs near-instant for CRF. Selected once per process via env var, not per-request; fails loudly (`NEREngineUnavailableError`) rather than silently falling back if `transformers` isn't installed. A third value `AIGUARD_NER_ENGINE=union` runs thainer (CRF) and WangchanBERTa together and unions their NER spans (highest recall per the strategy ADR `docs/superpowers/specs/2026-07-15-ner-engine-strategy-decision.md`); opt-in, needs `requirements-ml.txt`, and pays the WangchanBERTa cost on every sentence.
  - Name recall booster: `detectors/name_context.py` (`detect_name_context`, merged inside `detect_tb`) — token-level title/label cues (นาย/นาง/นางสาว/…, ผมชื่อ…, ลงชื่อ) capture names the CRF misses or clips; works on tokens so it ignores substrings like "นายก"/"คุณภาพ".
  - **Stride-chunk windowing** (Horizon-2 #10): consecutive sentences are tagged as chunks (core ≤500 chars, `window_size=1` sentence margins each side, spans kept when they START in the core; tagged strings are slices of the ORIGINAL text, never sentence joins) — ~1.2x chars tagged vs the old ±3 sliding window's ~7x, which is what makes WangchanBERTa/union practical.
  - **Honest labels with cue upgrades**: PERSON→NAME; LOCATION→`LOCATION` (upgraded to `ADDRESS` when an address cue — ที่อยู่/บ้านเลขที่/เลขที่/ซอย/ถนน/ตำบล/แขวง/อำเภอ/เขต/จังหวัด — appears within 30 chars before OR inside the span); DATE→`DATE` (upgraded to `DATE_OF_BIRTH` on a preceding เกิด cue); ORGANIZATION→`ORGANIZATION` (kept and masked — quasi-identifier; spans with zero Thai characters are rejected because the CRF hallucinates ORGANIZATION on plain-English text, a deliberate boundary pinned by tests). FP side mirrors this: bare regex dates → `DATE`, bare 8-12 digit runs → `ID_NUMBER`, `STUDENT_ID`/general-`PASSPORT` only with their cues (Thai-format passport `[A-Z]{2}\d{7}` needs no cue). Nothing previously masked became unmasked — labels and surrogates just stopped lying (business dates no longer become fake birthdays, invoice/PO numbers no longer become fake passports).
  - Span chokepoint: reject spans < 2 characters (prevents single-char NER false positives)
- **Sensitive semantic (optional)**: `sensitive_detector.py` — MiniLM sentence-embedding similarity flags free-form PDPA Section 26 content (health, religion, etc.) the keyword scan misses. Non-generative (flags existing spans only). Requires `requirements-ml.txt`; degrades to no-op when absent.

Post-detection:
- Span boundary adjustment + deduplication (map repeated entities to original). Both the web API (`detect_all`) and the CLI pipeline resolve FP/TB span overlaps through the central `detectors/aggregate.py dedupe_spans` (FP wins — checksum-backed) before any replacement; unresolved overlaps would corrupt the text during the anonymizer's tail-first splice.
- False negative scan: lightweight second pass (13-digit, `@`, date patterns)
- **Entity Registry**: `entity_id`, `redact_type` (FP/TB), `data_type`, `span`, `score`
- Output: Detection Report → Step 3

**Step 3 - Pseudonymization** (`pii_redactor/anonymizer/`)

Session mapping table (in-memory only, never written to disk; keyed by `entity_id`):
- If entity already in table → reuse existing pseudonym (consistency)
- If new entity → route by `redact_type`:
  - **FP**: `anonymizer/fp_generator.py` `generate_fp()` — format-preserving generator per `data_type` (valid checksum, SHA256-seeded per entity for reproducibility; no LLM)
  - **TB**: `anonymizer/tb_generator.py` `generate_tb()` — realistic Thai names/addresses from local hardcoded pools, seeded per entity (no LLM; nothing is sent anywhere)
  - **Collision-safe**: the fake pools are small, so two different people can draw the same pseudonym. `anonymizer.py _generate_unique_pseudonym` rejects a candidate that is already vaulted for a different original, equals another entity's real value, or appears verbatim in the source text; it re-rolls the seed (generators take `attempt=`) up to 8 times, then forces uniqueness with a `#N` suffix (mirrors the web path). Same original → same pseudonym is still allowed (consistency).

Replace real data using character spans from the entity registry (tail-first so earlier offsets stay valid) → consistency check (same entity everywhere) → post-replace scan with `detect_fp` (verify no real structured PII remains; halt + alert if found).

Output: **Pseudonymized Document** + session mapping table (for re-identification) → Step 4 (send to AI)

**Step 4 - Session mapping table** (`pii_redactor/session_vault.py`, `SessionVault`)

In-memory only (never persisted), keyed by `entity_id`, with a reverse index keyed by pseudonym for Step 6. `write()` raises `ValueError` if a pseudonym is already mapped to a different original (a silent reverse-index overwrite would restore the wrong person). Idle timeout (default 1800s) raises `VaultTimeoutError` on read; `snapshot()`/`restore()` support rollback around a failed AI call; `clear()` overwrites `original` with null bytes before dropping references. Its own internal audit log records only `{action, entity_id, timestamp, session_id}` — no PII.

**Step 5 - Send to AI** (`pii_redactor/ai_client.py`, `send_to_ai`)

`AIProvider` implementations: `FakeLLMProvider` (identity, for tests/dry-runs), `OllamaProvider`, `ClaudeProvider` (needs `ANTHROPIC_API_KEY`). Pre-send guard `_validate_pre_send` re-scans the pseudonymized text with `detect_fp` **and** `detect_tb` (excluding known pseudonyms) and raises `PreSendValidationError` on any real leak, plus a prompt-size check and a vault idle check. Retries up to 3x with exponential backoff on transient errors only (timeouts, network errors, HTTP 429/5xx); non-transient HTTP errors (other 4xx) and any other exception roll back the vault snapshot and re-raise. `_validate_response` logs a warning via `logging` (does not halt) if an expected pseudonym is missing from the AI's reply.

**Step 6 - Reverse mapping** (`pii_redactor/reverse_mapper.py`, `reverse_map`)

Restores originals into the AI's response using the vault's pseudonym→original reverse index via **positional replacement**: every pseudonym occurrence is located on the ORIGINAL (untouched) text (claimed longest-first, ranges never overlap — same rule as `leak_guard`), then spliced in a single tail-first pass. A progressive `str.replace` would re-scan the growing text and corrupt an already-restored original that happens to contain a pseudonym-looking substring; longest-first alone does not prevent that. Post-reverse validation flags pseudonym residue and incomplete replacement without halting; completeness compares `replaced_count` against the vault's **distinct expected pseudonyms** (an entity named N times = N registry entries but ONE pseudonym, so counting raw entities would flag every perfect restore). Both surface in `ReverseResult.audit_summary`.

**Step 7 - Output validation** (`pii_redactor/output_validator.py` + `pii_redactor/audit.py`)

Three layers: Layer 1 re-scans the restored text with `detect_fp` for anything not in the vault's known-originals set and **raises `PIILeakError`** immediately if found (this layer only runs `detect_fp`, not `detect_tb`, since TB-type PII — names/addresses — is expected to be present post-restore). Layer 2 surfaces completeness/residue flags (never halts). Layer 3 checks UTF-8 encodability and a Thai-aware truncation heuristic (Thai has no sentence-final punctuation, so text ending in Thai characters counts as a valid ending — only an abrupt non-Thai/non-punctuation cut trips it), setting `halt=True` (but not raising) on failure — the caller (`exporter.py`) turns that into an `ExportError`. `audit.py` writes disk-based JSONL process/security logs (step, entity counts, flags, latency / layer, scan result, retry/rollback counts) — a broader, PII-free schema than the vault's own internal log; note `pipeline.py` does not currently call into `audit.py` itself. `audit.py` allowlist-sanitizes `session_id` (`[A-Za-z0-9_-]`) before interpolating it into the log filename, so a hostile session id cannot path-traverse out of the log dir.

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
| `pii_redactor/reverse_mapper.py` | Step 6: restores originals into the AI response — positional splice on the untouched text (longest-first claiming, non-overlapping) |
| `pii_redactor/output_validator.py` | Step 7: 3-layer post-reverse validation (PII leak / completeness / integrity) |
| `pii_redactor/audit.py` | Step 7: disk JSONL process/security logs (step/counts/flags/latency; no PII) — distinct from `SessionVault`'s own internal `{entity_id, action, timestamp}` log |
| `pii_redactor/exporter.py` | Step 8: writes final `.txt`/`.pdf_text` output |
| `pii_redactor/models.py` | Shared dataclasses (`Entity`, `EntityRegistry`, `WordBbox`, `VaultRecord`, `AIResponse`, `ReverseResult`, ...) |
| `pii_redactor/ingest/ocr_processor.py` | Step 1 (hybrid/scanned PDFs): per-page PaddleOCR extraction, deskew/denoise/sharpen preprocessing, retry x3 → `human_review` flag. Optional (`requirements-ocr.txt`); raises `OCRUnavailableError` if not installed |
| `pii_redactor/session_service.py` | Single brain behind the web API: session lifecycle + sanitize/restore over core components |
| `pii_redactor/leak_guard.py` | Shared outbound leak scan used by `ai_client` pre-send guard and `SessionService` |

Roadmap (not implemented): Presidio bridge.

### Web API Endpoints (`app/server.py`, v2 token-mode contract)

- `GET /api/health` → `{status, version, capabilities: {token_required}}`
- `POST /api/sanitize {text, mode, session_id}` → `{session_id, original_text, sanitized_text, entities[], entity_type_counts, section26[], warnings[]}`. `mode="token"` (default) → `[ชื่อ_1]`; `mode="surrogate"` → realistic valid-format fake data (reads naturally to the AI). `session_id` is optional — pass an existing one to reuse it for multi-turn token consistency (mode must match the session's locked mode). An unknown `mode` string returns HTTP 400 (no silent fallback). Stores the pseudonym → original map in `pii_redactor/session_service.py`'s in-memory `SessionService`, keyed by `session_id`.
- `POST /api/reidentify {session_id, text}` → `{restored_text, replaced[], replaced_count, leftover_tokens, warnings[]}` — restores pseudonyms from the stored session map (mode-agnostic).
- `POST /api/analyze {text}` → full PDPA report `{overall_score, overall_grade, risk_label, direct_pii_count, fp_count, tb_count, section26[], reid, breakdown[], recommendations[]}`. `section26[]` merges keyword hits with optional MiniLM semantic hits (`source:"semantic"`).
- `POST /api/redact-pdf` (multipart `pdf_file`) → `{filename, source_type, ocr_confidence, human_review, ocr_warnings, entity_count, fields[], section26[], redacted_pdf_b64, before_png_b64, after_png_b64}`. Detects on RAW extracted text (bboxes align), draws black boxes via `pii_redactor/redactor.py`, returns the redacted PDF + page previews. Routes both text-layer and scanned/hybrid PDFs via `detect_source_type()`; returns HTTP 503 if a scanned PDF needs OCR and `requirements-ocr.txt` isn't installed. Uploads are read in 64 KB chunks against a 50 MB cap (`_MAX_PDF_BYTES`) — HTTP 413 once exceeded, before the body is fully buffered.

Both the web API and the CLI now run on the same core: `pii_redactor/session_service.py` (`SessionService`) wraps `detect_all` → `anonymize(mode=token|surrogate)` → `leak_guard.scan_outbound_leaks` for `/api/sanitize`, and `reverse_map` → `validate_output` (warnings only, inbound) for `/api/reidentify`. Sessions: cap 200, idle TTL 1800s, vault null-byte-cleared on drop/evict. `/api/sanitize` accepts optional `session_id` for multi-turn token consistency and returns additive `warnings[]`; FP-grade residual leaks return HTTP 422.

Control-plane boot token: the `AIGUARD_TOKEN` env var (generated by `launcher.py` when unset; the Tauri shell generates one and passes it to the sidecar it spawns — never logged) gates `POST /api/shutdown` and `DELETE /api/session/{id}` via the `X-AIGuard-Token` header (`secrets.compare_digest`). Unset token = legacy behavior byte-for-byte (`X-AIGuard-Local` for shutdown, open delete-session), so a from-source backend + extension keeps working. The data plane (`sanitize`/`reidentify`) is deliberately not token-gated until the extension gets a token channel (native messaging, roadmap Horizon-3 #16).

## Versioning

Single source of truth is the `VERSION` file at repo root (`app/server.py` derives `__version__` from it; bundled into the frozen exe). Bump with `scripts/bump_version.py <new>` (rewrites manifest.json, tauri.conf.json, Cargo.toml/lock, package.json); CI runs `scripts/check_version.py` as a fail-safe drift gate. The `_read_version()` fallback literal in `app/server.py` sits outside the system and must be hand-bumped at release. Do not hand-edit version strings anywhere else.

Packaging manifests (winget/scoop under `packaging/`) point at a *released* installer, not the in-repo version, so they are deliberately NOT in `bump_version.py`'s target set. After a release publishes its `SHA256SUMS` asset, bump all four with `scripts/update_packaging.py [vX.Y.Z]` (fail-loud, no partial writes), review the diff, then submit yourself — nothing is submitted automatically (see `packaging/README.md`).

## Verifiable build (Horizon-2 #11)

Shipped unsigned by design — trust comes from verifiability, not a certificate. Every build input is pinned: hash-pinned Python lockfiles (see Requirements Split), all GitHub Actions pinned by commit SHA with `.github/dependabot.yml` keeping them fresh. `release.yml`'s `checksums-and-attest` job publishes `SHA256SUMS` and GitHub build provenance for every release asset; users verify with `certutil`/`sha256sum -c` (integrity) and `gh attestation verify` (origin). This is origin+integrity verification, **not** bit-for-bit reproducibility (PyInstaller/NSIS embed timestamps). That job and the lock-based release build first run on a real `v*` tag — review the first tagged run's logs before relying on them.

## Design Invariants

- **Recall > Precision**: prefer false positives over missed PII
- **Vault never leaves device**: pseudonym → original map is in-memory only (`SessionVault` — per-session via `SessionService` on the web path, per-run on the CLI path); the extension keeps only `session_id`. `leftover_tokens` check on re-identification.
- **Pre-send leak guard**: before any send to an external AI, `ai_client._validate_pre_send` re-scans outbound text with `detect_fp` AND `detect_tb`; a real (non-pseudonym) hit halts the send.
- **PDPA Section 26 sensitive categories**: flagged/reported only (`report.scan_section26` keyword + optional `sensitive_detector` semantic), never auto-redacted.
- **Non-generative sensitive detection**: `sensitive_detector` flags only spans present in the source (embedding similarity), so it cannot hallucinate PII.
- **NER span filter**: reject any entity span < 2 characters before it reaches redaction.

## Requirements Split

- `requirements.txt` - core (pypdfium2, reportlab, Pillow, pdfplumber, PyThaiNLP, regex, httpx). httpx is core (not web-only) because `pii_redactor/ai_client.py` — imported by the core `pipeline.py` for `OllamaProvider`/`ClaudeProvider` — needs it unconditionally; it used to live only in `requirements-web.txt`, which broke a core-only install.
- `requirements-web.txt` - web (fastapi, uvicorn, requests)
- `requirements-ml.txt` - sentence-transformers + torch/transformers (MiniLM sensitive detector + the opt-in WangchanBERTa/union NER engines, `AIGUARD_NER_ENGINE`). Install only when the semantic detector or the WangchanBERTa/union NER engine is needed.
- `requirements-ocr.txt` - paddlepaddle + paddleocr + opencv-python-headless (scanned/hybrid PDF OCR, `pii_redactor/ingest/ocr_processor.py`). Install only when OCR-ing scanned PDFs is needed; excluded from the packaged `AIGuard.exe` (same treatment as `requirements-ml.txt`).

Lockfiles (Horizon-2 #11, verifiable build): the `.txt` files keep loose `>=` floors for the end-user/library `pip install` path, but CI and the release/exe build install from hash-pinned lockfiles instead — `requirements.lock` (core+web) and `requirements-build.lock` (+ a pinned PyInstaller from `requirements-build.txt`), both compiled with `uv pip compile --universal --generate-hashes --python-version 3.13` and installed with `pip --require-hashes`. Regenerate after editing any `requirements*.txt` with `scripts/lock_deps.py` (it drives uv with the right flags) and review the diff; `tests/test_lock_coverage.py` fails if a source package is missing from a lock. `ml`/`ocr` extras are not locked (never in the exe or CI). The CI job `pytest-core-only` deliberately stays on the unpinned `requirements.txt` to keep guarding the end-user install path. `scripts/build_sidecar.py` installs PyInstaller from `requirements-build.lock` (build the exe on Python 3.13, matching CI).

Note: licensed under Apache-2.0 (see LICENSE/NOTICE). PDF handling uses the permissive pypdfium2 / reportlab / pdfplumber; PyMuPDF (AGPL) was removed in phase 3 (redaction is now flatten-to-image).
