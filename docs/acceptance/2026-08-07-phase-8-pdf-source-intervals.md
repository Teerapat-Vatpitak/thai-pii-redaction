# Phase 8 authoritative PDF source intervals

- Evidence date (Asia/Bangkok): `2026-08-07`
- Clean base commit: `37f121515ce6c092bf6ad753a2ceb3ab16c41437`
- Candidate branch: `codex/phase-8-pdf-source-intervals`
- Product version: `2.5.0` (unchanged)
- Status: **integrated candidate; local and branch gates complete**

This record covers one Phase 8 unit: authoritative mapping from detected source
intervals to the exact PDF boxes that produced those characters. It does not
cover the native broker, provider orchestration, TNER, broader OCR accuracy,
the hosted PDF resource/capability decision, a release, deployment, installed
applications, or real browser/Office/platform acceptance.

All automated fixtures use fabricated markers or repository synthetic data.
This record and its evidence contain no document value, extracted text,
mapping, credential, provider body, restored response, screenshot, or unsafe
exception graph.

## Baseline defect

At clean base `37f1215`, `extract()` returned page-joined text and geometry as
separate values. Detected `Entity.span` values were authoritative half-open
offsets into that text, but `WordBbox` did not retain the interval that
produced its geometry. `redact_pdf()` therefore discarded `Entity.span`, built
text fragments from `Entity.original_text`, and searched every box in the
document. Identical and overlapping strings could select a different
occurrence or page.

## Locked source-provenance contract

Every PDF `WordBbox` returned by `extract()` carries one half-open
`source_span=(start, end)` into the exact `full_text` returned beside it:

- `full_text[start:end]` is the box text;
- spans use Python Unicode character offsets, including Thai combining
  characters;
- page separators and intra-page whitespace remain explicit in `full_text`;
- pdfplumber geometry is derived from its character-to-text map rather than
  aligned later by substring search;
- the pdfium fallback assigns offsets while consuming its character stream and
  explicitly maps CRLF-to-LF normalization;
- OCR text and boxes are assembled together, so their intervals are assigned
  when the OCR fragments enter the page text; and
- joining pages shifts local spans by the exact inserted separator length.

`clean_length_preserving()` remains the only transformation before PDF
detection. Its Thai-digit substitution is one code point for one code point,
so detection spans stay in the extraction coordinate space. Whitespace
collapse, NFC, zero-width removal, or any other length-changing normalization
does not enter this path.

## Locked redaction behavior

For each entity, the redactor selects only boxes whose authoritative source
interval intersects `Entity.span`. It never searches box text for the entity
value. The mapping must cover every non-whitespace character in the entity
interval; whitespace between mapped fragments needs no visual box.

This establishes:

- identical values at different offsets are independently selectable;
- a detected occurrence cannot select an identical occurrence on the same or
  another page;
- prefix/suffix similarity cannot widen the selection;
- adjacent and overlapping entities are deterministic;
- one entity may map to multiple text fragments, visual boxes, or pages when
  its own interval actually crosses them; and
- merging is scoped to boxes selected for one entity on one page, so unrelated
  nearby selections cannot paint across a negative-control gap.

If a box span is missing, malformed, inconsistent with its text, mapped to an
invalid page/geometry, or leaves a non-whitespace entity character uncovered,
the operation fails before writing an output. The core raises one fixed
value-free mapping error after dropping input references. HTTP v2 contains it
as the existing fixed `internal_error`; no wire field or error code is added.
The redactor does not fall back to global, page-local, normalized, or fuzzy
text matching.

Flatten-to-image output, opaque padding, per-entity same-line box merging,
lossless palette output, page geometry, the no-deskew rule, upload/work caps,
temporary-file cleanup, and fixed public error containment remain unchanged.

## Tests-first contract

Before production changes, adversarial tests must fail on the clean base for:

1. the same fabricated marker twice on one page with only one interval
   selected;
2. the same marker on different pages with only the requested page selected;
3. independent selection of two identical values at two offsets;
4. repeated prefixes and suffixes;
5. overlapping and adjacent source fragments/entities;
6. one entity spanning multiple boxes;
7. Thai combining characters;
8. spaces, newlines, and page separators;
9. missing or inconsistent provenance failing before output; and
10. source-mapping error containment with no retained input graph.

Existing real-sample pixel coverage, flattening, Thai-digit normalization,
hybrid/OCR routing, temporary cleanup, API v2 projection, and non-PDF behavior
remain regression gates.

## Evidence ledger

| Gate | Result |
|---|---|
| Tests-first adversarial collection against unchanged production | Expected failure: `13 failed` in `tests/test_pdf_source_intervals.py`; failures pin missing source provenance, repeated/wrong-page over-redaction, absent fail-closed mapping, and unchanged HTTP containment target |
| Final focused extraction/redaction/API/probe matrix | PASS — 252 tests across the new adversarial contracts plus ingest, rendered-PDF, probe, model, and detection regressions |
| Full Python suite | PASS — 2,331 passed, 5 optional OpenCV skips, 1 existing Starlette/httpx warning |
| Root JavaScript tests | PASS — syntax checks plus 123 tests across 16 files |
| Desktop Rust tests | PASS — 31 tests |
| Office manifest/type/unit/build gates | PASS — repository, upstream, packaged, and three XML manifest validations; TypeScript; 129 tests across 12 files; 13-module build |
| Ruff lint and format | PASS — lint passed and all 220 files were formatted |
| Type and security checks used by the repository | PASS with unchanged development-tool debt — Office TypeScript and privacy/error-graph regressions passed; read-only audits reproduced 1 root moderate and 19 Office dev-tree advisories |
| Version and release-readiness checks | PASS — synchronized `2.5.0`; both scripts and 39 version/workflow/release tests passed |
| Performance and PDF resource checks | PASS against exact clean base — all paired deltas are inside the 20% time and 15% memory budgets; the formal stale-anchor result is recorded below |
| `git diff --check` and final privacy/correctness review | PASS — no offset drift, normalization mismatch, wrong-page selection, heuristic fallback, duplicated mapping algorithm, unsafe boundary, provider/native-broker overlap, stale current-state claim, unrelated change, or version drift found |
| Reviewed code-candidate branch CI | PASS — corrected candidate `19b8b71b0c985f6a4939db0489a3300471fb2eaa` passed all 11 required jobs in [run 31190057013](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31190057013) |
| Final evidence branch-head CI | PASS — branch head `b3ff6059db2cbd72122dcb6436dde93f2be7437d` passed all 11 required jobs in [run 31190456107](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31190456107) |
| Post-integration main CI and commit alignment | Not claimed by this pre-integration record; verified separately after the squash push |

Local source automation cannot certify optional real PaddleOCR inference,
physical scans, handwriting, an installed Desktop application, a browser
download/open flow, an Office host, the sibling deployment, official platform
resources/logs, or hosted PDF acceptance.

## Principal commands

```powershell
$env:PYTHONUTF8='1'
.\.venv\Scripts\python.exe -m pytest tests\test_pdf_source_intervals.py tests\test_step1_ingest.py tests\test_step12_redact_pdf.py tests\test_probe_document.py tests\test_models.py tests\test_step2_detection.py -q
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe scripts\measure_perf.py
.\.venv\Scripts\python.exe scripts\check_version.py
.\.venv\Scripts\python.exe scripts\check_release_readiness.py
npm run test:js
cargo test --manifest-path desktop\src-tauri\Cargo.toml
npm test --prefix office-addin
npm run build --prefix office-addin
git diff --check
```

The optional PaddleOCR stack was not installed, so the five OpenCV-dependent
tests skipped. The repository's existing Starlette/httpx TestClient
deprecation warning remained. Office XML schema validation is source/manifest
evidence only and does not certify execution in Word, Excel, or PowerPoint.

## Performance

The required formal command ran without changing `perf/baseline.json`:

| Operation | Candidate | Committed baseline | Formal result |
|---|---:|---:|---|
| Detect | 6.87 ms | 5.73 ms | within 20% |
| Sanitize | 18.20 ms | 10.08 ms | +81%, over the stale anchor |
| Restore | 0.27 ms | 0.28 ms | within 20% |
| PDF redact | 81.78 ms | 67.67 ms | +21%, over the stale anchor |
| Resident memory | 151.2 MiB | 151.4 MiB | within 15% |

Sanitize is outside this unit. Because the changed PDF path was one percentage
point beyond the old absolute anchor, three alternating 20-iteration processes
compared the candidate with exact clean base `37f1215` on the same machine:

| Operation | Clean base median | Candidate median | Candidate delta | Budget |
|---|---:|---:|---:|---:|
| Detect | 8.74 ms | 9.39 ms | +7.4% | within 20% |
| Sanitize | 23.15 ms | 23.86 ms | +3.1% | within 20% |
| Restore | 0.33 ms | 0.34 ms | +3.0% | within 20% |
| PDF redact | 89.06 ms | 91.09 ms | +2.3% | within 20% |
| Resident memory | 155.9 MiB | 155.4 MiB | -0.3% | within 15% |

The branch is inside the repository budgets. The committed baseline was not
moved.

## Privacy and correctness review

Extraction now creates provenance at the only points where text is transformed:
the pdfplumber character map, pdfium's CRLF-aware character loop, retained OCR
assembly, and page joining. The benchmark probe consumes the same intervals.
There is no second alignment algorithm or text search.

The redactor validates all box intervals before selecting any entity. Selection
uses only half-open interval intersection; length-preserving Thai-digit
equivalence is checked only for the overlapping slice. Every non-whitespace
entity character must be covered. Invalid pages, non-finite/empty geometry,
conflicting pages for one source character, missing spans, inconsistent text,
and uncovered characters abort before output with a fixed value-free error.
Selected boxes merge only within one entity and page. Flattening, opaque
padding, lossless palette output, and the no-deskew coordinate rule are
unchanged.

Retained-error tests pin extraction and redaction graph disposal, and HTTP v2
still emits its existing exact `internal_error` object. No raw fixture value,
mapping, credential, provider body, restored response, or exception detail is
written to this record. The branch does not touch provider orchestration,
hosted allowlists, worker/HTTP wire DTOs, the native broker, or `VERSION`.

Read-only dependency audits reproduced the same development-only findings
recorded by the preceding Phase 8 unit: one moderate root advisory and 19
Office development-tool advisories (12 high, 7 moderate). Office has no runtime
dependency addition, and this branch changes no manifest or lockfile. This is
not a claim that the development dependency trees are vulnerability-free.

The first branch run on implementation commit
`7404fc66b4114ede0c6914064f522bbe9886c1c0` passed 10 of 11 jobs. Its core-only
job exposed a test-collection defect: the new HTTP containment fixture imported
optional FastAPI before applying the repository's core-only skip convention.
Commit `19b8b71b0c985f6a4939db0489a3300471fb2eaa` added that skip without changing
production behavior; the corrected exact candidate then passed all 11 jobs.
