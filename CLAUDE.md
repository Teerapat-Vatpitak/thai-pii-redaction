# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

AI Guard — open-source (Apache-2.0) Thai PII detection, anonymization, and redaction toolkit. Originally built as a PSU Future Tech Challenge 2026 entry; now maintained as a standalone open-source project. Two modes:

- **PDF redaction**: paint selected word boxes and flatten the result; exact
  entity-to-box association is a separate open correctness boundary
- **AI Guard**: pseudonymize PII with tokens before sending to external AI, re-identify locally from vault after response

### What this file is, and what it is not

This file is the **code map**: where things live, what each module is for, and
which invariants a change must not break. It deliberately carries no status and
no schedule. Three documents each carrying a bit of all three is how the
repository starts telling three different stories.

| Question | Document |
|---|---|
| Where does this live, and what must I not break? | this file |
| What gets built next, in what order, and what is the gate? | [ROADMAP.md](ROADMAP.md) |
| What is actually finished, and what is the evidence? | [docs/project-status.md](docs/project-status.md) |

`tests/test_docs_coverage.py` fails if a tracked top-level directory is absent
from this map or a storefront named here has no status row, so a new lane cannot
be added without appearing in both.

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

Thai font: bundled. `pii_redactor/fonts/IBMPlexSansThaiLooped-Regular.ttf`
(OFL-1.1, converted from the WOFF2 already vendored for the UI) is the first
entry in `FONT_CANDIDATES` and ships in the wheel via `package-data` and in the
exe via `--add-data`, so a generated PDF looks the same everywhere. System
paths below it (`sarabun-v17-…`, `leelawui.ttf`, the Debian tlwg paths) are a
net for a checkout whose data file is missing. `thai_pdf_text.py` also repairs a
reportlab `setRise` defect that strands text above the baseline for any font
positioning Thai marks by offset rather than glyph substitution.

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

# PDPA มาตรา 39 processing receipt (issue, then verify by rerunning)
$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe ai_guard.py receipt issue examples\prompts\01_sick_leave_email.txt -o receipt.json --pdf receipt.pdf
$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe ai_guard.py receipt verify receipt.json examples\prompts\01_sick_leave_email.txt

# PDPA มาตรา 37(4) breach assessment (scan a set of leaked files, write JSON + PDF)
$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe ai_guard.py breach assess examples\prompts -o breach.json --pdf breach.pdf

# PDPA มาตรา 30 DSAR helper (locate which files mention a data subject; subject.txt is one identifier per line)
$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe ai_guard.py dsar locate examples\prompts --subject-file subject.txt -o dsar.json --pdf dsar.pdf

# Tests (Python)
$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe -m pytest
$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe -m pytest tests/test_foo.py::test_name -v

# Detection benchmark (see the Benchmark section below)
$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe -m benchmark --source gold
$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe -m benchmark --source gold --compare-strategies

# Tests (JS — extension harness, vitest+jsdom; needs `npm install` once)
npm run test:js

# Tests (Rust — Tauri shell incl. sidecar kill-sequence tests)
cd desktop/src-tauri; cargo test

# Tests (Office add-in — its OWN npm project, Node 22; the root `test:js` does
# not reach it because office-addin/ has its own package.json + vitest.config.ts)
cd office-addin; npm install; npm test; npm run typecheck; npm run validate:manifest

# Lint + format (same two commands CI runs; config in pyproject.toml)
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format .
```

Tooling config lives in `pyproject.toml` (PEP 621 metadata + `[tool.pytest.ini_options]`
+ `[tool.ruff]`); there is no `pytest.ini` or `setup.py`. The ruff rule set is
kept green on purpose so CI can enforce it — style-only rules sit in `ignore`
with a comment marking them deferred, not endorsed. Formatting-only sweeps get
their own commit and an entry in `.git-blame-ignore-revs`.

JS harness note: `extension/sites.js` carries an additive CommonJS export shim
(`module.exports` — dead code in Chrome) exposing `selectFor(hostname)` + every
site config so `extension/tests/` can pin selector behavior against the DOM
fixtures in `extension/tests/fixtures/`. Playwright live-DOM checks and the
selector-drift badge are future work (not yet implemented).

**Browser extension** (primary UI): start the backend (above), then load `extension/`
unpacked in Chrome (`chrome://extensions` → Developer mode → Load unpacked). See
`extension/README.md`. The extension calls the backend cross-origin; the server's CORS
is a strict allowlist (`allow_origin_regex` for `chrome-extension://`, `moz-extension://`,
and Tauri origins only — not `*`) plus `TrustedHostMiddleware` limited to
localhost/127.0.0.1 (`app/server.py`).

## Architecture: "Single Brain, Multiple Storefronts"

One core pipeline (`pii_redactor/`) exposed via five storefronts over one shared backend:

| Storefront | Entry point |
|---|---|
| Browser extension (primary UI) | `extension/` (MV3: in-page Mask/Restore bar on ChatGPT/Claude/Gemini/Grok/Perplexity/GLM·Z.ai + docked side panel via `chrome.sidePanel`; per-site DOM selectors in `sites.js` with a generic fallback. Mask reports success only after re-reading the composer and matching the sanitized text (EXT-2); any mask failure raises a blocking overlay (EXT-3); the restored-PII overlay renders inside a closed shadow root so page scripts cannot read it — its styles live in `OVERLAY_CSS` in content.js, not content.css (EXT-4)) |
| CLI | `demo_cli.py`, `ai_guard.py` |
| Queue worker (provisional emulator) | `app/worker/` (`python -m app.worker`; job → stateless core; HTTP-poll transport and job schema are provisional local failure/retry fixtures, not the official AI for Thai delivery path; no PII in logs per VAULT-4; `docker compose --profile worker`) |
| Desktop app (Windows) | `desktop/` (Tauri: `src/` web UI, `src-tauri/` Rust shell that spawns and kills the packaged Python sidecar, `tests/` + `cargo test` for the kill sequence, `build-sidecar.ps1`). The Rust side owns process lifecycle and the boot token it passes to the sidecar; it is not a second copy of the pipeline. |
| Microsoft 365 add-in | `office-addin/` (TypeScript task pane, Vite + Vitest, Node 22. `src/adapters/{word,excel,powerpoint}.ts` are host adapters behind one contract; `src/controller.ts` holds the shared Detect/Analyze/Mask/Restore flow; `src/api.ts` talks to the backend over an HTTPS localhost proxy; session state is memory-only. `scripts/*.mjs` validate the per-host manifests and package the unified manifest. Its `package.json`/`vitest.config.ts` are separate from the repo-root ones.) |

The browser extension, desktop shell, and Office add-in use the local
**FastAPI backend** `app/server.py` (`/api/*`); the demo is an opt-in route on
that app. The CLI and provisional worker call shared `pii_redactor/` services
through their own adapters rather than going through FastAPI. Main now also
contains `app.hosted`, a strict-v2 generic hosted candidate with required
API-key/provider configuration and a fixed seven-route allowlist. It is not the
confirmed official route/lifecycle contract. The separately versioned sibling
port remains v1 and out of scope; its vendored core predates F09 and needs
separate authorization before any re-sync or push. Exact official route/auth
and acceptance remain pending. The extension is the product's front door; the normal local
backend is API-only (no web frontend) and runs on localhost. `/` redirects to
`/docs` (Swagger). The
extension's service worker calls the backend; CORS allows only extension/Tauri
origins (strict allowlist, see above). The canonical token → original map lives
in the backend's in-memory `SessionService` sessions
(`pii_redactor/session_service.py`, one `SessionVault` per session). The
current client boundary is `session_id` only: HTTP v2 projects no explicit
mapping DTO or original/token pairs, and browser, Desktop, and Office construct
fresh strict DTOs before using a result. Clients still necessarily hold their
submitted and returned text transiently; response minimization is not a claim
that caller-owned text cannot be compared.

### Pipeline (Step 1-8)

The steps below are the authoritative description. They came from a `step1-7_*.pdf`
design doc that is deliberately not in the repo (it is gitignored — a working
document, and its file name undercounts: the doc itself documents 8 steps). Do not
go looking for it in a fresh clone.

**Step 1 - Ingest & Validate**

File type detection routes to one of three sub-paths:

- **Plain text**: input validation (language, size, Thai support) → encoding validation (all text normalized to UTF-8)
- **Text-layer PDF**: check if openable → extract text via pdfplumber/pypdfium2 → store word bboxes `(page, x, y, width, height)` for later PDF redaction. `WordBbox` currently has no canonical source interval. `redactor.py` does not consume `Entity.span`; it builds normalized `Entity.original_text` fragments and globally substring-matches each box, rather than selecting boxes by exact offset intersection.
- **Hybrid/scanned PDF** (`pii_redactor/ingest/ocr_processor.py`): **per-page**, not whole-document. `detect_source_type` routes a document to `pdf_hybrid` as soon as ANY page carries a raster image — even one sitting beside a full text layer, because a pasted ID card hides PII the text layer never mentions. Such a page contributes BOTH its text layer and its OCR (`_remove_layer_text` drops OCR words already covered by the layer, so the same string is not counted twice). OCR runs PaddleOCR with image pre-processing (denoise, unsharp-mask sharpen — deliberately no deskew, and `use_doc_orientation_classify`/`use_doc_unwarping` are off for the same reason, see DET-3: a page rotated or unwarped for OCR puts the bboxes in a different coordinate space from the unrotated page `redactor.py` paints on, so black boxes miss the PII). Every raster page runs **at least `MIN_OCR_ATTEMPTS`=2** attempts and stops early only at `OCR_EARLY_STOP_THRESHOLD`=0.9, up to `MAX_OCR_RETRIES`=3 with escalating DPI/binarization; the attempts are then **merged**, not picked — `_merge_retry_words` adds text a later attempt found in new page areas, and may replace a read only when the replacement still carries every structured value it evicts (a retry that adds a digit to a national id must never delete the valid read). Page confidence is the LOWEST contributing attempt's mean, so admitting a weak attempt's word re-prices the page and sets `human_review`. Optional dependency (`requirements-ocr.txt`): a raster page with **no usable text layer** raises `OCRUnavailableError`, but one that has a text layer falls back to it with a warning and `human_review` rather than failing the whole document — the packaged exe ships without the OCR extra and a letterhead logo must not cost it PDF redaction. `text_extractor.extract()` returns `(text, word_bboxes, meta)` for every source type — `meta` carries `ocr_confidence`/`human_review`/`pages_ocred`/`pages_text_layer`/`ocr_text_ranges`/`ocr_observations`/`warnings` (empty dict for `text`/`pdf_text`). `ocr_observations` holds raw per-page OCR text for the benchmark probe's matcher; it is deliberately NOT returned by any API route or written to any log.

All paths converge at language detection (Thai primary, English minimum).

**Text Cleaning Pipeline** (runs after ingest) — 4 stages, returning `CleanResult(text, post_clean_warnings)`:
1. Whitespace normalization (collapse repeats, remove blank lines)
2. Unicode normalization (decompose → canonical form)
3. Character standardization (Thai digits → Arabic digits, strip zero-width characters)
4. Post-clean encoding check

The original design had three more stages (broken-word recovery, OCR-error flagging, broken-sentence review). They were removed after the v2 audit verified the kill-list claim against running code: stage 4 tokenized every input through PyThaiNLP and rejoined it unchanged (0/4 representative Thai samples altered) while loading the whole Thai word set; stage 5 flagged every word containing B or Z (`Bob`, `Building`, `ZIP`); stage 6's interactive branch was unreachable because no caller passes `interactive=True`. Nothing consumed their outputs. `clean()` still accepts `interactive`/`review_timeout_s` and ignores them, so existing call sites and the CLI flag keep working.

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
  - PyThaiNLP thainer-CRF (`NER(engine="thainer")`) — the default, fast, fully offline. An opt-in WangchanBERTa engine (`AIGUARD_NER_ENGINE=wangchanberta`, maps to `NER(engine="thainer-v2")`) is available for higher recall at a real cost: ~1.3s/sentence on CPU vs near-instant for CRF. Selected once per process via env var, not per-request; fails loudly (`NEREngineUnavailableError`) rather than silently falling back if `transformers` isn't installed. A third value `AIGUARD_NER_ENGINE=union` runs thainer (CRF) and WangchanBERTa together and unions their NER spans; opt-in, needs `requirements-ml.txt`, and pays the WangchanBERTa cost on every sentence. As of gold v4 + the 2026-07 accuracy campaigns the default CRF matches or beats union on F2 at ~1/27 the compute (the cue/coalescing work closed union's old ADDRESS/NAME advantages) — see `docs/decisions/2026-07-28-engine-comparison-after-campaigns.md`; union survives as an option, not a recommendation. `AIGUARD_NER_ENGINE=tner` is an explicit remote engine and sends raw pre-mask chunks to AI for Thai. Missing configuration fails when that engine is first lazily loaded. A failed remote request aborts the whole operation as `ner_unavailable`; malformed, misaligned, truncated, illegal-BIO, or unknown-label ordered tokens abort it as `ner_incomplete`. Source-position spans preserve internal whitespace omitted by a tokenizer. Earlier chunk candidates are discarded and later chunks are not sent. Core, HTTP/hosted/PDF, local-session/stateless, and worker boundaries preserve only fixed metadata after clearing the original graph. The shared BIO/chunk engines (`thainer`, WangchanBERTa, and union) retain structural skip-and-continue resilience; the separate fine-tuned offset engine is outside this change. Live TNER response/mapping recertification remains separate from this automated source behavior.
  - Name recall booster: `detectors/name_context.py` (`detect_name_context`, merged inside `detect_tb`) — token-level title/label cues (นาย/นาง/นางสาว/…, ผมชื่อ…, ลงชื่อ) capture names the CRF misses or clips; works on tokens so it ignores substrings like "นายก"/"คุณภาพ".
  - **Stride-chunk windowing**: consecutive sentences are tagged as chunks (core ≤500 chars, `window_size=1` sentence margins each side, spans kept when they START in the core; tagged strings are slices of the ORIGINAL text, never sentence joins) — ~1.2x chars tagged vs the old ±3 sliding window's ~7x, which is what makes WangchanBERTa/union practical.
  - **Honest labels with cue upgrades**: PERSON→NAME; LOCATION→`LOCATION` (upgraded to `ADDRESS` when an address cue — ที่อยู่/บ้านเลขที่/เลขที่/ซอย/ถนน/ตำบล/แขวง/อำเภอ/เขต/จังหวัด — appears within 30 chars before OR inside the span); DATE→`DATE` (upgraded to `DATE_OF_BIRTH` on a preceding เกิด cue); ORGANIZATION→`ORGANIZATION` (kept and masked — quasi-identifier; spans with zero Thai characters are rejected because the CRF hallucinates ORGANIZATION on plain-English text, a deliberate boundary pinned by tests). FP side mirrors this: bare regex dates → `DATE`, bare 8-12 digit runs → `ID_NUMBER`, `STUDENT_ID`/general-`PASSPORT` only with their cues (Thai-format passport `[A-Z]{2}\d{7}` needs no cue). `STUDENT_ID` additionally requires its cue to be the *nearest* one: a competing number-introducer (ราคา/ยอด/ใบเสร็จ/สั่งซื้อ/invoice/order…) closer to the digits wins and the label falls back to `ID_NUMBER`, so "นักเรียนสั่งซื้อสินค้ารหัส 88910423" is an order number, not a student id. Same nearest-cue-wins rule as the bank/phone and bank/student pairs; measured to cost nothing on the gold set. Nothing previously masked became unmasked — labels and surrogates just stopped lying (business dates no longer become fake birthdays, invoice/PO numbers no longer become fake passports).
  - Span chokepoint: reject spans < 2 characters (prevents single-char NER false positives)
- **Sensitive semantic (optional)**: `sensitive_detector.py` — MiniLM sentence-embedding similarity flags free-form PDPA Section 26 content (health, religion, etc.) the keyword scan misses. Non-generative (flags existing spans only). Requires `requirements-ml.txt`; degrades to no-op when absent.

Post-detection:
- Span boundary adjustment + deduplication (map repeated entities to original). `detectors/aggregate.py detect_all` is the single entry point every caller uses — the web API, `pipeline.py`, `report.py` (so `/api/analyze`, the PDF report and the worker), and `ai_guard.py report`. It resolves FP/TB span overlaps through `dedupe_spans` (FP wins — checksum-backed) and coalesces address fragments before any replacement; unresolved overlaps would corrupt the text during the anonymizer's tail-first splice. Counting the raw `detect_fp` + `detect_tb` lists instead double-counts a value both detectors matched, which is why the entity totals in a report come from the deduped list.
- False negative scan: lightweight second pass (13-digit, `@`, date patterns)
- **Entity Registry**: `entity_id`, `redact_type` (FP/TB), `data_type`, `span`, `score`
- Output: Detection Report → Step 3

**Step 3 - Pseudonymization** (`pii_redactor/anonymizer/`)

Session mapping table (in-memory only, never written to disk; keyed by `entity_id`).
The UUID is the vault identity only; it is not used as a pseudonym seed:
- If entity already in table → reuse existing pseudonym (consistency)
- If new entity → route by `redact_type`:
  - **FP**: `anonymizer/fp_generator.py` `generate_fp()` — format-preserving generator per `data_type` (valid checksum, SHA256-seeded from the caller's `salt` and the original value, with deterministic `attempt=` rerolls; no LLM)
  - **TB**: `anonymizer/tb_generator.py` `generate_tb()` — realistic Thai names/addresses from local hardcoded pools, seeded from the caller's `salt`, original value, and deterministic `attempt=` reroll; name cues and full-name shape also come from the supplied context (no LLM; nothing is sent anywhere)
  - **Collision-safe**: the fake pools are small, so two different people can draw the same pseudonym. `anonymizer.py _generate_unique_pseudonym` rejects a candidate that is already vaulted for a different original, equals another entity's real value, or appears verbatim in the source text; it re-rolls the seed (generators take `attempt=`) up to 8 times, then forces uniqueness with a `#N` suffix (mirrors the web path). Same original → same pseudonym is still allowed (consistency).

For fixed generator inputs, the result is deterministic. `SessionService` keeps
one random salt for a session, so the same original remains consistent within
that vault. `run_pipeline()` generates a fresh salt when none is supplied, and
independent sessions/runs therefore are not guaranteed to produce the same
surrogate. Stateless surrogate output is reproducible when the caller supplies
the same salt. Stateless token calls deliberately receive a fresh random
generation namespace and fresh nonces for newly minted tokens; a caller that
needs token continuity must pass its prior mapping. Restoration uses the
vault/mapping and does not require cross-run identical pseudonyms.

Token mode emits
`[<localized-label>_<25-letter-generation-tag>_<20-letter-token-nonce>_<ordinal>]`.
The `a`-through-`f` tag encodes 64 random bits and belongs to one vault
lifecycle. Each newly minted token adds about 94 bits of unpredictable
`a`-through-`z` nonce; the complete token is reused for the same original.
Neither component is a credential or `session_id`. Detached transaction clones
and snapshot/restore preserve the tag and complete records, then `clear()`
invalidates them. Exercised lifecycle regressions keep stale and guessed tokens
foreign. The 64-bit tag plus approximately 94-bit nonce makes accidental
identity reuse and same-session future-token preplay computationally
impractical; the separation is probabilistic, not impossible.

Replace real data using character spans from the entity registry (tail-first so earlier offsets stay valid) → consistency check (same entity everywhere) → post-replace scan with `detect_fp` (verify no real structured PII remains; halt + alert if found). Before a masked result can leave the sanitization boundary, `leak_guard.enforce_outbound_policy` also checks structured FP and text-based TB findings plus detector-independent contiguous runs of six or more digits. Every detected entity must resolve to a replacement record; an absent record blocks rather than returning an incomplete entity projection.

Output: **Pseudonymized Document** + backend-owned session mapping table. Only
the masked document crosses the provider boundary; the mapping remains for
Step 6 re-identification.

**Step 4 - Session mapping table** (`pii_redactor/session_vault.py`, `SessionVault`)

In-memory only (never persisted), keyed by `entity_id`, with a reverse index keyed by pseudonym for Step 6. `write()` rejects a different entity ID claiming an already-owned pseudonym with another original, but same-ID replacement remains possible. `seed()` re-admits caller-held stateless mappings under the lifecycle lock: a new pair gets opaque `seed:<uuid4>` identity, safe `SEEDED` provenance, and one structural `seed` audit row; exact replay returns the same immutable record without changing lookup/audit/access state; a conflicting original raises the constant value-free `seed pseudonym collision` error before mutation. A token-shaped seed is scanned for FP/TB/digit residuals before its shape can be admitted. One valid namespaced prior-mapping chain supplies the namespace for newly minted stateless tokens; legacy `[<label>_<ordinal>]` tokens are readable only at this explicit boundary and are never minted. Idle timeout (default 1800s) raises `VaultTimeoutError` when a known vault is accessed; there is no wall-clock sweeper. `snapshot()`/`restore()` support rollback around a failed AI call, while a clear-generation check prevents a stale snapshot from reviving explicitly cleared mappings. `clear()` drops vault-owned table/reverse/token-namespace references but may retain safe structural audit rows; it cannot securely zeroize Python immutable strings.

**Step 5 - Send to AI** (`pii_redactor/ai_client.py`, `send_to_ai`)

`AIProvider` implementations: `FakeLLMProvider` (identity, for tests/dry-runs), `OllamaProvider`, `ClaudeProvider` (needs `ANTHROPIC_API_KEY`), `PathummaProvider`, `TokenmindProvider` (LiteLLM gateway ของงาน AIFT; ต้องมี `TOKENMIND_BASE_URL` ลงท้าย `/v1` + `TOKENMIND_API_KEY`). The CLI pipeline uses `send_to_ai()`: immediately before each outer `provider.complete()` invocation, `_validate_pre_send` invokes the shared outbound policy and raises the value-free `PreSendValidationError("outbound residual detected")` for structured FP, text-based TB, or detector-independent contiguous 6+ digit findings. A caller-seeded prior-mapping key is not trusted merely because the caller declared it; reuse requires a nonempty pseudonym that does not contain its original, did not already occur in the current source text, and does not independently trigger the FP/TB/digit policy. Token-mode reuse must also match the product token shape for the detected data type. The same validation also applies the prompt-size and vault-idle checks. The CLI retries up to 3x with exponential backoff on transient provider errors only (timeouts, network errors, HTTP 429/5xx); a guard failure never enters that retry policy. A provider declaring `handles_retries=True` receives one outer validation and one outer call, then may retry the same immutable masked text internally. Tokenmind's current internal loop still uses one total timeout and honors `Retry-After`; convergence to the locked per-attempt 60-second, fixed 1/2-second policy belongs to the open shared-orchestration work. The public `send_to_ai()` wrapper contains ordinary Exception-derived snapshot, capability, validation, provider, response-tail, and rollback failures, scrubs their original graphs, and surfaces only fixed safe categories. `_validate_response` logs a warning via `logging` (does not halt) if an expected pseudonym is missing from the AI's reply. HTTP roundtrip and the worker still call `provider.complete()` directly, but both now repeat the shared outbound policy immediately before that call. They do not yet share the CLI's complete retry/rollback orchestration.

**Step 6 - Reverse mapping** (`pii_redactor/reverse_mapper.py`, `reverse_map`)

Restores originals into the AI's response using the vault's pseudonym→original reverse index via **positional replacement**: every pseudonym occurrence is located on the ORIGINAL (untouched) text (claimed longest-first, ranges never overlap — same rule as `leak_guard`), then reconstructed left-to-right while recording the exact restored-output ranges. A progressive `str.replace` would re-scan the growing text and corrupt an already-restored original that happens to contain a pseudonym-looking substring; longest-first alone does not prevent that. Post-reverse validation flags pseudonym residue and incomplete replacement without halting; completeness compares `replaced_count` against the vault's **distinct expected pseudonyms** (an entity named N times = N registry entries but ONE pseudonym, so counting raw entities would flag every perfect restore). Audit metadata keeps counts, never the replaced or residual pseudonym values. A foreign-token detector also runs here, surfacing `foreign_tokens:N` in the audit summary when the AI's reply contains product-token strings that were never in this session's vault. Exact current-format tokens remain foreign in every mode so a stale value cannot fail open through a surrogate replacement session; legacy or translated bracket shapes are checked only in token mode. Unknown values remain unchanged, and v2 projects only the count-only `foreign_replacement` warning.

**Step 7 - Output validation** (`pii_redactor/output_validator.py` + `pii_redactor/audit.py`)

Three layers: Layer 1 re-scans the restored text with `detect_fp` for anything not in the vault's known-originals set and **raises `PIILeakError`** immediately if found (this layer only runs `detect_fp`, not `detect_tb`, since TB-type PII — names/addresses — is expected to be present post-restore). Layer 2 surfaces completeness/residue flags (never halts). Layer 3 checks UTF-8 encodability and a truncation heuristic inverted to a blocklist (VAULT-5): any letter/digit ending in any script is a valid ending — a last line that is a phone number, version string, or Thai/English prose is normal output — and only mid-cut connector endings (trailing comma/hyphen/opening bracket/colon and the like) trip it, setting `halt=True` (but not raising) on failure — the caller (`exporter.py`) turns that into an `ExportError`. `audit.py` writes JSONL process/security logs (step, entity counts, flags, latency / layer, scan result, retry/rollback counts) to local disk or configured stdout; note `pipeline.py` does not currently call it. Current API callers use fresh non-authorizing operation UUIDs instead of live restoration session IDs for sanitize, reidentify, and roundtrip. The legacy filename/entry field remains named `session_id`, and `/api/audit-log` omits it. In file mode, fresh operation IDs create operation-specific files with no timed deletion; configured stdout mode writes no file. This is current-source automated evidence, not published-2.5.0 or official-platform acceptance.

**Step 8 - Export** (`pii_redactor/exporter.py`, `export`)

Writes `.txt` or `.pdf_text` (a fresh reportlab-built text dump of the final de-identified string — unrelated to `redactor.py`'s flatten-to-image blackout of an original PDF). Halts via `ExportError` if `validation_result.halt`, format unsupported, or output exists without `overwrite=True`.

All 8 steps are wired together by `pii_redactor/pipeline.py`'s `run_pipeline()` and each has a dedicated test file (`tests/test_step4_vault.py` … `tests/test_step9_pipeline.py` for the full integration).

### Key Modules

| Module | Purpose |
|---|---|
| `app/http_v2.py` | Strict v2 response/error DTOs and extra-field rejection for main HTTP adapters |
| `app/hosted.py` | Generic strict-v2 hosted candidate with required API-key/provider configuration and a fixed seven-route allowlist; not official deployment evidence |
| `pii_redactor/pipeline.py` | CLI pipeline orchestrator (`run_pipeline`); calls `send_to_ai` |
| `pii_redactor/detectors/` | FP (regex/checksum), TB (thainer CRF NER), FN scanner |
| `pii_redactor/anonymizer/` | Package: `anonymizer.py` (vault replace), `fp_generator.py` + `tb_generator.py` (valid-format / Thai fake values) |
| `pii_redactor/redactor.py` | Flattened PDF redaction via bbox black boxes (wired through `/api/redact-pdf`); current entity-to-box association is a substring heuristic, not exact source-span alignment |
| `pii_redactor/reid_risk.py` | Quasi-identifier re-identification risk score (Sweeney model), 0-100 + grade |
| `pii_redactor/report.py` | PDPA risk report; `scan_section26` keyword flags (not auto-redacted) |
| `pii_redactor/receipt.py` | PDPA มาตรา 39 processing receipt — one slip per run (not a cumulative RoPA; the vault is in-memory and the hosted roundtrip mapping is request-transient, so a register would mean retaining what those paths promise not to). `build_receipt()` records source sha256 + a digest over the detection result + counts/types + version/engine/PyThaiNLP version; `verify_receipt()` re-runs the same input through the shared `process_for_receipt()` and compares **every factual field**, not just the two digests — both sides build them from one `_claims()` helper, so a field added later is verified by construction (the first cut compared digests only, and a receipt edited to claim zero entities verified clean). Authenticity comes from recomputation rather than a signature (no key to keep). The digest excludes `entity_id` (fresh UUID4 per run) and `score` (a detector's internal float). Nothing derived from the document is a value — but `--purpose`/`--controller` are operator free text drawn verbatim onto the PDF, and no document may claim otherwise. Wired through `ai_guard.py receipt issue|verify`; deliberately no HTTP endpoint by design |
| `pii_redactor/receipt_pdf.py` | The receipt rendered as a Thai PDF slip (reportlab + `thai_pdf_text.draw_text`), including the command that verifies it. PII-free by the same structural argument as `report_pdf.py` — a receipt dict has no values in it to begin with; shares that module's `_TYPE_LABELS` so both documents name a data type the same way |
| `pii_redactor/breach.py` | PDPA มาตรา 37(4) breach-assessment aggregation across a set of leaked/affected files (`assess_breach(paths, *, recursive=False)`) — not a legal conclusion, states what was found and how the estimate was derived, never that notification is required. Reuses the same `extract`/`clean`/`detect_all`/`scan_section26`/`assess_reid_risk` every other storefront calls; nothing re-implemented. A file that fails anywhere in that chain becomes a `FailedFile` row (basename + exception class, with every spelling of the input path scrubbed from the message so a directory name never leaks) and the assessment continues; `NoFilesAssessedError` only when nothing could be assessed. A directory scan also reports every file it chose not to look at (`files.skipped`: count + basenames, for anything outside `*.txt`/`*.pdf`) rather than dropping it silently, and `files.total` counts everything the scan found, not just what survived that filter. Affected-subject estimate: `subjects_min` is the largest distinct-value count among the strong identifier types — `THAI_ID` (the code's real `Entity.data_type` label; the original design note said "NATIONAL_ID"), `PASSPORT`, `PHONE`, `EMAIL` — each canonicalized before counting (digits-only id, a `+66` mobile or landline form folded to its domestic digits so the same number typed two ways collapses to one value); `subjects_max` is their sum, on the stated-not-hidden assumption that no subject spans two identifier types. When no strong identifier is found at all, `subjects.no_strong_identifiers` is `true` and the CLI/PDF headline renders as inconclusive rather than a literal "0-0 คน", which would otherwise read as "nobody affected" instead of "no strong identifier found". `NAME` is tracked and reported but excluded from both bounds as a weak identifier (spelling/OCR variants inflate it). `to_json_dict()` is the one JSON-shape builder the CLI and `breach_pdf.py` both consume, so the two artifacts cannot drift; every field is a count, a type/category name, a basename, or a version string — no value, excerpt, or hash of a value (a hash of a 13-digit id is brute-forceable, so it counts as a value here too). Wired through `ai_guard.py breach assess`, which also deletes an already-written `--pdf` if the following `-o` JSON write fails, so a hard-failure run never leaves a complete artifact behind unmentioned; deliberately no HTTP endpoint by design |
| `pii_redactor/breach_pdf.py` | The breach assessment rendered as a Thai PDF slip, same whitelist-renderer idiom as `report_pdf.py`/`receipt_pdf.py` (shares `_TYPE_LABELS`) — only counts, type/category labels, grades, version strings, failed-file basenames + short reasons, and skipped-file basenames ever reach the canvas. The subject-estimate method statement and the NAME weak-identifier note are drawn verbatim from the dict rather than retyped, so the JSON and the PDF cannot describe the estimate two different ways. Unlike `receipt_pdf.render_receipt` (which returns bytes), `render_breach_pdf(assessment_dict, output_path)` writes the file itself, matching what the CLI calls before it writes the JSON |
| `pii_redactor/dsar.py` | PDPA มาตรา 30 data-subject access request helper — LOCATES which of a set of files mention a subject, never reproduces content (`locate_subject(paths, subject_file, *, recursive=False) -> DsarResult`). `subject_file` is one identifier per line, classified by shape (13 digits → `THAI_ID`, `[A-Z]{2}\d{7}` → `PASSPORT`, contains `@` → `EMAIL`, digit/`+66` phone shape → `PHONE`, else the `NAME` catch-all); identifiers are never accepted inline on the CLI, so no value can enter shell history. Shares `pii_redactor/scan_common.py`'s `discover_files`/`short_reason`/`canonical_value` with `breach.py` — extracted out of `breach.py` into this new module for `dsar.py` to reuse. Matching is value-based only: a detected entity's raw text is canonicalized under each SUBJECT identifier's own type rules and compared for exact equality, so the detector's own label for that entity is never consulted — a phone number the detector happens to label `BANK_ACCOUNT` in one document (bank/phone nearest-cue-wins), or a name it labels `ORGANIZATION` in another, still matches, because the label is the detector's contextual guess, not a property of the value. One deliberate exception guards precision: PHONE's international-to-domestic fold (`+66` → `0`) only applies when the entity's raw text still carries an explicit `+66` marker, so a bare digit run that merely starts with `66` (e.g. an unrelated bank account) is never folded into a false phone match — a re-review caught this as a real false positive in F1's first cut. No fuzzy matching: an OCR misread of a scanned identifier will not match even where a human reader would recognize it as the same value (a known Track A limitation, stated in the artifact rather than papered over). A matched file's row carries `third_party_possible`, set (warn-only, heuristic — it also fires on the subject's own data under a type they didn't list, and on the detector's own false positives) whenever the file's overall PII inventory holds a type or a count beyond what matched the subject's own identifiers, and `weak_only`, true when the ONLY matched identifier type is NAME — a weak identifier by the same reasoning `breach.py` already applies to its own `subjects_min`/`subjects_max`, so a NAME-only match is flagged for human confirmation rather than presented the same as a checksum-backed match. Unmatched files are counted in the aggregate but never listed as rows — a DSAR artifact should not inventory documents out of scope for the request. `to_json_dict()` is the one builder the CLI and `dsar_pdf.py` both draw from; no field is ever a subject or document value, or a hash of one — only identifier TYPE occurrence counts, basenames, type/grade names, flags, and the five fixed method/limitation/third-party/name-weak-match/scope statements. Wired through `ai_guard.py dsar locate`; deliberately no HTTP endpoint by design |
| `pii_redactor/dsar_pdf.py` | The DSAR locate result rendered as a Thai PDF slip, same whitelist-renderer idiom as `breach_pdf.py`/`receipt_pdf.py` (shares `_TYPE_LABELS`) — only identifier TYPE names/counts, file aggregate counts, each matched file's basename/source type/matched-identifier-type occurrence counts/full PII type inventory/risk grade/`human_review`/`third_party_possible`/`weak_only`, failed/skipped basenames, and the fixed method statements (drawn verbatim from the dict, never retyped) ever reach the canvas. `render_dsar_pdf(result_dict, output_path)` writes the file itself, same idiom as `render_breach_pdf` — not `receipt_pdf.render_receipt`'s bytes-returning one — matching what the CLI calls before it writes the JSON |
| `pii_redactor/sensitive_detector.py` | Optional MiniLM semantic Section-26 detector (non-generative); no-op without `requirements-ml.txt` |
| `pii_redactor/session_vault.py` | Step 4: in-memory `SessionVault` (pseudonym↔original), random token-generation namespace, idle timeout, detached transaction clone, and clear-generation-protected snapshot/restore rollback |
| `pii_redactor/stateless.py` | One-call sanitize/restore core for HTTP/worker adapters: throwaway vault, transient internal mapping, explicit prior-mapping token-namespace continuity, shared fail-closed policy, and fixed value-free direct-core failure translation |
| `pii_redactor/ai_client.py` | Step 5: AI providers (Fake/Ollama/Claude/Pathumma/Tokenmind + `PROVIDER_FACTORIES` registry) + shared outbound policy before each outer provider invocation + retry/rollback |
| `pii_redactor/reverse_mapper.py` | Step 6: restores originals into the AI response — positional reconstruction on the untouched text (longest-first claiming, non-overlapping), records inserted ranges, and runs a count-only foreign-token detector; exact current tokens remain foreign in every mode while broad legacy shapes stay token-mode gated |
| `pii_redactor/output_validator.py` | Step 7: 3-layer post-reverse validation (PII leak / completeness / integrity) |
| `pii_redactor/audit.py` | Step 7: disk/stdout JSONL process/security logs (step/counts/flags/latency; no PII); current API callers pass operation UUIDs into the legacy `session_id` field — distinct from `SessionVault`'s own internal `{entity_id, action, timestamp}` log |
| `pii_redactor/exporter.py` | Step 8: writes final `.txt`/`.pdf_text` output |
| `pii_redactor/models.py` | Shared dataclasses (`Entity`, `EntityRegistry`, `WordBbox`, `VaultRecord`, `AIResponse`, `ReverseResult`, ...) |
| `pii_redactor/ingest/ocr_processor.py` | Step 1 (hybrid/scanned PDFs): per-page PaddleOCR extraction, denoise/sharpen preprocessing (no deskew, no orientation/unwarping — bbox coordinate integrity, DET-3), 2-3 attempts merged rather than picked (a replacement must preserve the structured values it evicts) → lowest contributing confidence + `human_review` flag. Optional (`requirements-ocr.txt`); raises `OCRUnavailableError` only for a raster page with no usable text layer; swallowed dependency/OCR-retry errors are graph-cleared before fallback |
| `pii_redactor/session_service.py` | Single brain behind the web API: session lifecycle + sanitize/restore over core components; `sanitize_transaction()` stages a detached graph through endpoint finalization and publishes it with one session-dictionary assignment; unexpected sanitize/restore failures translate only after sensitive frames are cleared |
| `pii_redactor/leak_guard.py` | Shared fail-closed outbound policy: FP/TB rescans, a detector-independent contiguous 6+ digit signal, trusted-current-replacement rules, and bounded value-free failure labels |
| `pii_redactor/safe_errors.py` | Clears completed traceback frames/chaining plus ordinary mutable exception payloads before a boundary translates or swallows a failure; nested group members are scrubbed recursively, while the read-only `BaseExceptionGroup` shell is preserved and dropped to avoid Python 3.13 `repr()` corruption; built-in attribute access resists hostile overrides |
| `scripts/http_v2_client.py` | Strict contract-v2 smoke client used by container and packaged-runtime checks |
| `pii_redactor/guard/injection.py` | ชั้นสัญญาณเตือน prompt injection แบบ dependency-light (explicit rules + bounded normalization/intent classifier แยกจาก PII detection และ leak_guard); `scan_injection` → `GuardFinding[]`; 5 bypass เดิมเป็น passing regression พร้อม negative controls |
| `training/` | Fine-tuning lane (Track A #5): `lexicons.json` (gold-disjoint fabricated pools), `generate_data.py` (synthetic BIO data + ThaiNER rehearsal + hard negatives), `train.py` (HF Trainer). Weights live OUTSIDE the repo; the opt-in engine `AIGUARD_NER_ENGINE=finetuned` loads them via `AIGUARD_FINETUNED_MODEL_DIR` through `detectors/finetuned_engine.py` (char-offset adapter) with a model-as-verifier policy for the extended name-cue passes (strong cues stay unconditional). Needs `requirements-train.txt` on top of `requirements-ml.txt`. |


Roadmap (not implemented): Presidio bridge.

### Web API Endpoints (`app/server.py`, current HTTP contract v2)

`GET /api/health` is open contract discovery and returns
`{status, version, contract_version: 2, capabilities:
{control_token_required, api_key_required}}`. Every other `/api/*` operation
requires `X-AIGuard-Contract-Version: 2`, and every actual API success/error
returns the same assertion header. Request models and nested response DTOs
reject extra fields.

- `POST /api/sanitize {text, mode?, session_id?}` → `{session_id,
  sanitized_text, detected_entity_count, replacement_count,
  entity_type_counts, highlights[], section26_categories, guard_findings[],
  warnings[], safety}`. Highlights use half-open Unicode code-point offsets into
  `sanitized_text` and never carry a token field. Token mode emits
  `[<label>_<generation-tag>_<token-nonce>_<ordinal>]`; surrogate mode emits realistic
  format-valid fake data. A residual or missing replacement returns the stable
  `residual_pii` 422 envelope and publishes no staged state.
- `POST /api/reidentify {session_id, text}` → `{restored_text, replaced_count,
  leftover_count, warnings[]}`. There is no replaced pair/list or leftover
  token string. `generated_pii` or `foreign_replacement` is count-only and
  blocks first-party writeback.
- `POST /api/detect {text}` → `{detected_entity_count, entity_type_counts,
  highlights[]}`. It uses `clean_length_preserving`; highlights refer to the
  caller's source text and this inspection path does not invoke the outbound
  block.
- `POST /api/analyze {text}` → the strict aggregate PDPA DTO with scores,
  counts, `section26_categories`, `reidentification`, `breakdown[]`, and
  structured allowlisted `recommendations[]`; no source value or match text.
- `POST /api/guard {text}` → `{flagged, guard_findings[]}` with category and
  severity only. Prompt-injection remains warn/report, not automatic blocking.
- `POST /api/roundtrip {text, mode, provider}` → minimized masked/restored
  text, counts/types, selected provider, safe Section 26/guard/warning
  metadata, `safety`, and count-only `restoration`. The throwaway mapping is
  consumed inside one request. The adapter rescans immediately before its
  direct provider call and never falls back to another provider.
- `POST /api/analyze-report {text}` → `{report_pdf_b64, overall_score,
  overall_grade}`. It shares `_analyze_text` and the whitelist-only PDF
  renderer.
- `POST /api/redact-pdf` → source/OCR review metadata, count/type projections,
  `redacted_pdf_b64`, and only the after-redaction PNG preview. It does not
  return filename or an unredacted preview. Geometry remains source-space, but
  entity-to-box ownership is still heuristic rather than exact source-offset
  alignment. The 50 MB streaming cap and optional-OCR fallback remain.
- `GET /api/audit-log`, `DELETE /api/session/{id}`, and `POST /api/shutdown`
  are local-only introspection/control routes. `app/hosted.py` removes them,
  document routes, developer metadata, and the demo. Its fixed allowlist is
  health, detect, analyze, guard, sanitize, reidentify, and roundtrip.
- `GET /demo` serves `demo/playground.html` only when `AIGUARD_DEMO=1`.

All error responses use the exact stable-code/count/category/retryability/status
envelope from the
[v2 decision](docs/decisions/2026-08-05-http-contract-v2.md). They never include
request values, originals, replacements, mappings, provider bodies, guard or
Section 26 excerpts, credentials, session authority, or exception messages.

Both the web API and CLI use the same core components, but complete provider
orchestration is not yet unified. `SessionService` owns stateful
sanitize/restore: cap 200, LRU by `last_access`, idle TTL 1800 seconds checked
on known-session access, and one coarse `RLock`. `sanitize_transaction()` holds
that lock while it clones the complete session/vault state, runs core and
endpoint finalization, and publishes through one dictionary assignment.
Pre-publication failure preserves the published graph and LRU/capacity state;
expiry disposal is outside rollback and displaced-vault cleanup after
publication is best effort. HTTP/worker direct-provider adapters repeat the
outbound scan immediately before their call but do not yet share CLI
retry/rollback orchestration.

`AIGUARD_TOKEN` is control-plane authority for shutdown/session disposal and is
never given to browser or Office JavaScript. The optional, separate
`AIGUARD_API_KEY` gates v2 data-plane, document, and introspection routes;
health remains open. This caller authentication does not prove which process
owns fixed localhost port 8000, so packaged browser/Office/Desktop identity
still requires the native broker.

## Versioning

Single source of truth is the `VERSION` file at repo root (`app/server.py` derives `__version__` from it; bundled into the frozen exe). Bump with `scripts/bump_version.py <new>` (rewrites manifest.json, tauri.conf.json, Cargo.toml/lock, package.json, and both npm package-lock root fields); CI runs `scripts/check_version.py` as a fail-safe drift gate. The `_read_version()` fallback literal in `app/server.py` sits outside the system and must be hand-bumped at release. Do not hand-edit version strings anywhere else.

Distribution is direct download, not a package manager. The winget/Scoop manifests and their `update_packaging.py` generator were removed on 2026-07-29 (see [the distribution ADR](docs/decisions/2026-07-29-store-distribution-and-signing.md)); installers are published as GitHub Release assets with `SHA256SUMS` and build provenance, and the owner links them from the web. Nothing in the tree needs a post-release manifest bump any more.

## Verifiable build

Shipped unsigned by design — trust comes from verifiability, not a certificate. Build inputs are pinned: hash-pinned Python lockfiles (see Requirements Split), all GitHub Actions pinned by commit SHA with `.github/dependabot.yml` keeping them fresh, the PyThaiNLP NER model pinned by SHA256 in `scripts/build_sidecar.py` (it is fetched from an upstream host at build time and baked into the attested exe), and — since REL-12 — pip, the Rust toolchain and Node pinned to explicit versions instead of `latest`/`stable`/`lts/*` (`tests/test_workflow_pins.py` guards this). The one deliberate exception is apt packages, left unversioned because Ubuntu's archive drops superseded versions and a pin would break the build when it rotates. `release.yml`'s `checksums-and-attest` job publishes `SHA256SUMS` and GitHub build provenance for every release asset; users verify with `certutil`/`sha256sum -c` (integrity) and `gh attestation verify` (origin). This is origin+integrity verification, **not** bit-for-bit reproducibility (PyInstaller/NSIS embed timestamps). The tagged release pipeline has run end to end on published `v*` tags, with checksums and attestations verified (see `docs/project-status.md`).

## Benchmark (`benchmark/`)

`python -m benchmark` scores the detector against one of two corpora, selected
with `--source`:

- `synthetic` — `corpus.py` generates documents from seeded templates. Fast and
  unbounded, but it can only contain the entity shapes its own generators emit,
  so a rule that agrees with the generator scores perfectly whether or not it is
  right. Every field is drawn from one shared `random.Random(seed)`, so editing
  any generator reshuffles unrelated values at a fixed seed.
- `gold` — `data/gold.jsonl`, 252 hand-authored documents carrying 648 annotated
  entities across 11 types (v4, adjudicated 2026-07-28 against
  `docs/annotation-guidelines.md`), no type under 24 instances, plus a
  45-document `negative` slice containing no PII at all. Each record stores the document with
  entities marked inline (`[[NAME|สมชาย ใจดี]]`); `gold.py` strips the markup and
  derives the spans, so the text and its annotation cannot drift apart. All
  values are fabricated.

The negative slice is what makes a false-positive rate reportable — a corpus in
which every document contains PII can report recall and nothing else.

`scorer.py` reports three views of the same predictions, and they disagree by
design: entity-level type-aware matching (a hit on one shared character, greedy
one-to-one), character-level coverage (the share of annotated PII characters any
prediction actually covered — the figure that describes what a redaction box
leaves visible), and exact boundary. Headline is F2, since recall is weighted
four times precision here. Recall is undefined on the negative slice, which
reports false-positive count and clean-document rate instead.

`llm_strategy.py` + `llm_providers.py` + `scripts/run_llm_benchmark.py` score a
hosted model as a detector over the same gold set, both with and without the
type label, because several Thai models answer with the Thai field name as the
type. Responses are cached under `benchmark/reports/llm_cache/` as parsed
`(type, value)` pairs — never the provider's response body, which AGENTS.md
forbids in acceptance artifacts — keyed by a hash of provider, prompt and
document text so a prompt or gold-set edit cannot silently reuse a stale answer.
`benchmark/reports/` is gitignored.

`blind.py` — the held-out blind set (Track A). **NEVER decrypt, read, or print
the blind corpus in a development session** — it exists to measure whether
gold-set tuning generalizes, and reading it (by human or agent) burns it. The
corpus is committed only as `data/blind-*.enc` (HMAC-keystream obfuscation +
auth MAC; blinding, not security) with a lock file pinning hashes and counts;
the key lives outside the repo, passed via `AIGUARD_BLIND_KEY_FILE`. Scoring
(`python -m benchmark --source blind --reason "..."`) is aggregate-only and
appends a hash-chained entry to the committed `data/blind-scores.jsonl` under
a reveal budget; the LLM benchmark must never touch it (test-pinned). Protocol:
`docs/decisions/2026-07-28-blind-set-protocol.md`.

Top-level `research/` holds frozen paper evidence: `research/stt52/` pins the
STT52 study at gold-v3 and a fixed system commit so the paper's numbers stay
reproducible while the detector moves on. Its prediction files carry offsets
and types only — never document text or entity values (see its README).

## Performance baseline (`perf/`)

`scripts/measure_perf.py` times detect, sanitize, restore, and PDF redaction
in-process (deliberately not over HTTP, so the numbers describe the pipeline
rather than the network stack) and samples resident memory, then compares
against the committed `perf/baseline.json`. A change touching `pii_redactor/`
or `app/` runs it and reports the numbers; the budget is 20% on time and 15% on
memory, and moving the baseline needs a reason in the same commit. It is a
local gate, not a CI job — shared runners are too noisy to gate timings on.

**The gate does not see the OCR path.** Its fixture is
`examples/sample_document.pdf`, which `detect_source_type` routes `pdf_text`,
so no OCR runs in any of the four timed operations. Every raster page costs at
least `MIN_OCR_ATTEMPTS` full OCR passes and up to three, and the merge across
attempts re-runs `_structured_keys` per word — none of that can move a gate
number. A change to `ingest/ocr_processor.py` therefore needs its own timing
evidence (time a hybrid page directly and say so in the commit); "perf gate
green" is not a statement about OCR.

## Design Invariants

- **Recall > Precision**: prefer false positives over missed PII
- **Intended local mapping boundary**: the canonical pseudonym → original map is in-memory only (`SessionVault` — per-session via `SessionService` on the web path, per-run on the CLI path), and first-party clients keep only `session_id`. The published 2.5.0/v1 artifact violated the projection half by returning direct or reconstructable mapping fields; current unreleased source implements strict v2 projections and clients, while matching packaged/real-host acceptance remains open.
- **Fail-closed outbound policy**: local-session and stateless sanitization reject structured FP, text-based TB, detector-independent contiguous 6+ digit, anonymization, and missing-replacement failures. Caller seeds are not trusted merely by declaration, and unsafe identity/embedded/pre-existing values are not reused. The CLI repeats the scan before each outer provider invocation; self-retrying providers receive one outer validation before resending the same immutable masked text. HTTP and worker repeat it immediately before their direct provider call. Complete provider orchestration, packaged/live acceptance, and the native broker remain open.
- **PDPA Section 26 sensitive categories**: flagged/reported only (`report.scan_section26` keyword + optional `sensitive_detector` semantic), never auto-redacted.
- **Non-generative sensitive detection**: `sensitive_detector` flags only spans present in the source (embedding similarity), so it cannot hallucinate PII.
- **NER span filter**: reject any entity span < 2 characters before it reaches redaction.

## Requirements Split

- `requirements.txt` - core (pypdfium2, reportlab, Pillow, pdfplumber, PyThaiNLP, regex, httpx). httpx is core (not web-only) because `pii_redactor/ai_client.py` — imported by the core `pipeline.py` for `OllamaProvider`/`ClaudeProvider` — needs it unconditionally; it used to live only in `requirements-web.txt`, which broke a core-only install.
- `requirements-web.txt` - web (fastapi, uvicorn, requests)
- `requirements-ml.txt` - sentence-transformers + torch/transformers (MiniLM sensitive detector + the opt-in WangchanBERTa/union NER engines, `AIGUARD_NER_ENGINE`). Install only when the semantic detector or the WangchanBERTa/union NER engine is needed.
- `requirements-ocr.txt` - paddlepaddle + paddleocr/PaddleX (which supplies the single OpenCV contrib runtime) for scanned/hybrid PDF OCR. Do not add a second `opencv-python*` wheel beside PaddleX because both distributions own `cv2`. Install only when OCR-ing scanned PDFs is needed; excluded from the packaged `AIGuard.exe` (same treatment as `requirements-ml.txt`).

Lockfiles (verifiable build): the `.txt` files keep loose `>=` floors for the end-user/library `pip install` path, but CI and the release/exe build install from hash-pinned lockfiles instead — `requirements.lock` (core+web) and `requirements-build.lock` (+ a pinned PyInstaller from `requirements-build.txt`), both compiled with `uv pip compile --universal --generate-hashes --python-version 3.13` and installed with `pip --require-hashes`. Regenerate after editing any `requirements*.txt` with `scripts/lock_deps.py` (it drives uv with the right flags) and review the diff; `tests/test_lock_coverage.py` fails if a source package is missing from a lock. `ml`/`ocr` extras are not locked (never in the exe or CI). The CI job `pytest-core-only` deliberately stays on the unpinned `requirements.txt` to keep guarding the end-user install path. `scripts/build_sidecar.py` installs PyInstaller from `requirements-build.lock` (build the exe on Python 3.13, matching CI).

Note: licensed under Apache-2.0 (see LICENSE/NOTICE). PDF handling uses the permissive pypdfium2 / reportlab / pdfplumber; PyMuPDF (AGPL) was removed in phase 3 (redaction is now flatten-to-image).
