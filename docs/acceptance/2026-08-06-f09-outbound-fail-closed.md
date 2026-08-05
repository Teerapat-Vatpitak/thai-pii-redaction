# F-09 outbound fail-closed policy

- Evidence date (Asia/Bangkok): `2026-08-06`
- Clean base commit: `3f3960aafb56c9b287ea3f6c10abadcce1c68f70`
- Reviewed code candidate: `042e21564c438dd6584f166f33b695717e11ebd2`
- Product version: `2.5.0` (unchanged)
- Python: `3.13.14`

This record is current-source automated evidence for F-09 at exact code
candidate `042e215`. It verifies the shared outbound residual policy, adapter
enforcement, safe failure boundaries, and a newly built generic sidecar. It is
not evidence of the pending HTTP v2 response-minimization cutover, an installed
application, a real browser or Office host, a live provider, an official
platform deployment, or a release. Product version remains `2.5.0`; published
v2.5.0 at `24914ab` predates this change.

All runtime checks used synthetic values. This record contains no request text,
entity value, mapping, credential, provider body, restored answer, or private
absolute path.

## Behavior established

One core outbound policy now rejects all of these conditions before returning
or transmitting masked text:

- structured false-positive-check findings;
- text-based residual findings;
- detector-independent contiguous runs of six or more digits;
- detected entities without a completed replacement; and
- unsafe caller-seeded prior mappings.

A prior mapping can be reused only when its pseudonym is nonempty, contains no
original value, does not already occur in the current source text, and is free
of independent structured, text-based, and digit-run residual signals. Token
mode additionally requires the product token shape for the detected data type.
Identity, embedded-original, empty, cross-type, residual, and duplicate-source
laundering cases fail closed.

The local session transaction includes the policy check, so a rejected request
does not publish a new session or mutate an existing session. Stateless
sanitize and hosted/stateless roundtrip reject before returning a masked
result. The CLI scans immediately before every outer provider call. Providers
declaring `handles_retries=True` receive one outer validation. HTTP and the
local worker emulator scan immediately before their direct provider calls.
No provider is invoked after a residual signal.

The current HTTP v1 API returns a bounded, value-free `residual_pii` 422. Its
request-validation handler returns a constant value-free 422 rather than
reflecting rejected input. Trusted internal HTTP failures are converted to a
value-free response, including failures raised before response rendering
starts. The worker retains envelope contract version 1 and returns a safe
typed error. Worker transport and emulator logging do not print exception
messages.

Exception containment clears traceback and chaining references, ordinary
custom attributes, and common built-in exception payload fields before a
swallowed failure leaves its boundary. Exception-group members are scrubbed
recursively. The exception-group shell remains intact because its message and
member tuple are read-only and clearing its arguments corrupts representation
on Python 3.13. Direct and grouped process-control signals are allowed to
propagate.

Provider status and attempt metadata are bounded before they enter safe errors.
PDF/OCR optional fallback boundaries also discard unsafe exception state.
Current HTTP v1 and worker compatibility still expose dynamic exception class
names in some safe failure categories; the HTTP v2 and provider-convergence
branches own removal of that compatibility debt.

The extension adds a defensive residual check before accepting a sanitize
response. This is source-level defense in depth, not current real-browser
acceptance.

## Local verification

| Gate | Result |
|---|---|
| Full Python suite | PASS — 1,860 passed, 5 skipped, 1 warning in 146.77 seconds |
| Final provider/API/worker/safe-error matrix | PASS — 162 passed, 1 warning |
| Documentation coverage | PASS — 6 passed |
| Root JavaScript | PASS — 12 files, 60 tests |
| `python -m ruff check .` | PASS |
| `python -m ruff format --check .` | PASS — 219 files |
| Version synchronization | PASS — `2.5.0` |
| Release-readiness check | PASS |
| `git diff --check` | PASS |
| Generic sidecar build | PASS |
| Generic sidecar smoke | PASS — health, synthetic sanitize, process-tree termination, and port release |
| Independent privacy/correctness review | PASS — no remaining F-09 blocker |
| Independent current-truth documentation audit | PASS — no blocker |

The full Python warning was the existing Starlette/httpx TestClient
deprecation warning. The five skips were optional OpenCV OCR cases because
`cv2` was not installed.

The sidecar build reported unavailable optional ML/OCR imports, removed or
optional PyThaiNLP hidden imports, unauthenticated model-cache metadata
requests, and PyInstaller analysis warnings. The supported core artifact built
and passed its smoke. The smoke observed `/api/health` 200 and
`/api/sanitize` 200, then terminated the process tree and released port 8000.
It also surfaced the expected source/v1 warning that `AIGUARD_API_KEY` was not
set. It did not install or open Desktop, a browser, or Office.

The principal local commands were:

```powershell
$env:PYTHONUTF8='1'
.\.venv\Scripts\python.exe -m pytest -q -rs
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe scripts\measure_perf.py
.\.venv\Scripts\python.exe scripts\check_version.py
.\.venv\Scripts\python.exe scripts\check_release_readiness.py
.\.venv\Scripts\python.exe scripts\build_sidecar.py
.\.venv\Scripts\python.exe scripts\smoke_exe.py
npm run test:js
git diff --check
```

## Performance

The formal performance command was red against the older committed timing
anchor:

| Operation | Candidate | Committed baseline | Delta | Formal result |
|---|---:|---:|---:|---|
| Detect | 6.54 ms | 5.73 ms | +14% | within 20% |
| Sanitize | 12.42 ms | 10.08 ms | +23% | over 20% |
| Restore | 0.47 ms | 0.28 ms | +68% | over 20% |
| PDF redact | 79.28 ms | 67.67 ms | +17% | within 20% |
| Resident memory | 151.6 MiB | 151.4 MiB | +0.1% | within 15% |

Because the committed sub-millisecond restore anchor and local timings were
already known to vary, five alternating runs compared the branch with its exact
clean base in the same environment:

| Operation | Clean base | F-09 branch | Branch delta | Budget |
|---|---:|---:|---:|---:|
| Detect | 7.03 ms | 6.73 ms | -4.3% | within 20% |
| Sanitize | 14.28 ms | 12.70 ms | -11.1% | within 20% |
| Restore | 0.48 ms | 0.47 ms | -2.1% | within 20% |
| PDF redact | 83.49 ms | 79.39 ms | -4.9% | within 20% |
| Resident memory | 151.8 MiB | 151.4 MiB | -0.3% | within 15% |

Late trials varied substantially for both base and branch. The paired medians
show no measured F-09 regression, but they do not turn the red formal command
green. The committed baseline was not changed.

## Branch CI

[GitHub Actions run 31036175866](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31036175866)
passed all 11 jobs at exact code candidate `042e215`:

- Ruff lint and format;
- full pytest on Ubuntu and Windows;
- core-only pytest with optional dependencies absent;
- product-version synchronization;
- extension/Desktop JavaScript syntax and Vitest;
- Office manifest/version validation, typecheck, tests, and build;
- Desktop Rust tests;
- Docker image build and all five declared endpoint smokes; and
- Windows packaged-executable build and generic API smoke.

The Docker and packaged-executable jobs are generic build/smoke evidence. They
are not installed, storefront, real-host, live-provider, or official-platform
acceptance.

## Compatibility and evidence boundaries

HTTP remains contract v1 in this branch. Its successful sanitize and
reidentify responses still cross the mapping boundary, and Section 26 and
guard projections still include raw matched text or excerpts. First-party
clients are not yet strict HTTP v2 consumers. Those issues are intentionally
reserved for the atomic HTTP v2 cutover.

The worker remains a local failure/retry emulator with envelope contract
version 1. It is not the official AI for Thai delivery path. The official
hosted path remains the HTTP/FastAPI adapter and bypasses the local queue.

Historical storefront, published Desktop, Office, PDF, live-provider, and
hosted evidence predates this policy change and is not current-candidate
acceptance. This record does not verify:

- strict HTTP v2 schemas or mapping-minimized browser, Desktop, and Office
  clients;
- an installed Desktop application, real extension site, Office host, unified
  Office package, or certificate trust path;
- any of the eight open Office real-host/package gates;
- a live Pathumma, Tokenmind, TNER, or official AI for Thai call;
- deployment, resource/soak behavior, retry ownership, or platform logs;
- optional OpenCV OCR or optional ML execution;
- request-driven session sweeping, client continuity, or authenticated
  disposal;
- authenticated localhost process identity or packaged broker enforcement;
- unified provider orchestration, explicit-TNER whole-request failure, or exact
  PDF entity-to-box alignment; or
- migration of the separately versioned sibling AI for Thai port.

No live provider, installed application, real host, deployment, certificate,
registration, or store action was operated for this record.
