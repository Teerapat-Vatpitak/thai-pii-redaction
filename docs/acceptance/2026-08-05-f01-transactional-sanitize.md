# F-01 transactional local sanitize

- Evidence date (UTC): `2026-08-05`
- Clean base commit: `304b07126ebd095847d4012060f17f25b1655af5`
- Implementation snapshot: `58f554b0531339fc452c7314e40d21670b7d3c77`
- First reviewed branch candidate:
  `7c971641921fe10017384fbf1d26da467caafc16`
- Product version: `2.5.0` (unchanged)
- Python: `3.13.14`

This record is current-source automated evidence for F-01. It is not a release,
installed-application, browser, Office real-host, live-provider, or official
platform acceptance record. Tests used synthetic values, and this record
contains no request text, entity value, mapping, pseudonym, credential,
provider body, restored answer, or private absolute path.

## Behavior established

Local stateful sanitize now stages a detached session and vault graph while
holding the existing coarse service lock. Detection, anonymization, residual
scanning, Section 26 projection, guard projection, HTTP v1 response
construction and serialization, and the required correlation-only process
audit write complete before one session-dictionary publication.

Automated regressions establish the following behavior:

- A failed new-session request publishes no session and performs no
  capacity-driven eviction.
- A non-expiry failure against an existing session preserves the published
  mapping, reverse index, entities, pseudonym ordinals, audit rows, timestamps,
  mode, salt, and LRU order.
- Detection, partial anonymization, residual scan, Section 26, guard,
  response-projection, JSON-render, and audit-write failures all discard staged
  state.
- Concurrent restore and drop operations cannot observe the staged graph.
- A successful request preserves pseudonym reuse, ordinal behavior, and the
  existing HTTP v1 response shape.
- A stale provider rollback cannot restore vault references after an explicit
  clear; a vault clear wins the tested snapshot/restore interleavings.
- Successful sanitize writes a safe `prepared` process record before
  publication. A rejected attempt may retain a safe `blocked` process record,
  but neither record carries live session authority or entity values.
- Sanitize, reidentify, and roundtrip API process-audit callers use fresh,
  non-authorizing operation UUIDs. The legacy audit field is still named
  `session_id`.
- Cleanup of replaced or evicted vault state occurs after publication and is
  best effort. A cleanup failure cannot convert a published success into an
  error.

Genuine request-driven expiry remains outside the rollback guarantee. If a
known session is expired when accessed, its disposal is intentional lifecycle
behavior rather than a failed sanitize mutation.

## Local verification

| Gate | Result |
|---|---|
| Full Python suite | PASS — 1,716 passed, 5 skipped, 1 warning in 271.50 seconds |
| Focused service/vault/API matrix | PASS — 234 passed, 1 warning |
| Independent reviewer matrix | PASS — 165 passed, 1 warning |
| Documentation and current API checks | PASS — 63 passed, 1 warning |
| `python -m ruff check .` | PASS |
| `python -m ruff format --check .` | PASS — 217 files |
| Version synchronization | PASS — `2.5.0` |
| Release-readiness check | PASS |
| `git diff --check` | PASS |
| Sidecar build | PASS |
| Packaged sidecar smoke | PASS — health, synthetic sanitize, process-tree termination, and port release |
| Independent privacy/concurrency review | PASS — no remaining F-01 blocker |
| Independent current-truth documentation audit | PASS — no remaining blocker |

The full Python warning was the existing Starlette/httpx deprecation warning.
The five skips were the optional OpenCV OCR cases because `cv2` was not
installed. The sidecar build also reported unavailable optional ML/OCR imports
and an unauthenticated model-hub cache warning; the supported core artifact
still built and passed its smoke. No installed Desktop application was opened.

The principal local commands were:

```powershell
$env:PYTHONUTF8='1'
.\.venv\Scripts\python.exe -m pytest `
  tests\test_session_service.py `
  tests\test_stateless.py `
  tests\test_step4_vault.py `
  tests\test_leak_guard.py `
  tests\test_stateless_leak_regression.py `
  tests\test_platform_api_contract.py -q
.\.venv\Scripts\python.exe -m pytest -q -rs
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe scripts\measure_perf.py
.\.venv\Scripts\python.exe scripts\check_version.py
.\.venv\Scripts\python.exe scripts\check_release_readiness.py
.\.venv\Scripts\python.exe scripts\build_sidecar.py
.\.venv\Scripts\python.exe scripts\smoke_exe.py
git diff --check
```

## Performance

The formal performance script remained red against its older committed timing
anchor on both the branch and an unchanged clean control. A paired same-session
comparison against the clean base measured:

| Operation | Clean base | F-01 branch | Branch delta | Budget |
|---|---:|---:|---:|---:|
| Detect | 8.55 ms | 10.11 ms | +18.2% | within 20% |
| Sanitize | 14.28 ms | 14.78 ms | +3.5% | within 20% |
| Restore | 0.47 ms | 0.51 ms | +8.5% | within 20% |
| PDF redact | 98.49 ms | 99.48 ms | +1.0% | within 20% |
| Resident memory | 152.3 MiB | 152.6 MiB | +0.2% | within 15% |

A separate nine-trial, 500-turn retained-session comparison measured a median
2.0021 ms on the clean base and 2.0271 ms on the branch, a +1.2% delta.
Detached vault containers structurally share immutable entity, vault-record,
and audit-row values; profiling no longer placed transaction cloning among the
top twenty costs.

## Branch CI

[GitHub Actions run 30997497821](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/30997497821)
passed at branch candidate `7c97164`:

- Ruff lint and format;
- full pytest on Ubuntu and Windows;
- core-only pytest with optional dependencies absent;
- product-version synchronization;
- extension/Desktop JavaScript syntax and Vitest;
- Office manifest/version validation, typecheck, tests, and build;
- Desktop Rust tests;
- Docker image build and all five declared endpoint smokes; and
- Windows packaged-executable build and API smoke.

The local Docker daemon was unavailable and was not started. The green CI
Docker job supplies the container build/smoke evidence for this candidate.

## Review and compatibility notes

Independent review found and closed three material defects before this
candidate:

1. a same-named timeout raised outside the staged core could have disposed the
   published session;
2. a stale snapshot could have restored mappings after `clear()`; and
3. a deep transaction clone imposed unnecessary retained-session cost.

`Entity`, `VaultRecord`, and internal vault-audit rows are now immutable so
their values can be shared safely between detached containers. No in-repository
consumer mutates those objects. `SessionVault` now also owns a lifecycle lock.
Mutation, copying, or pickling behavior for an unknown out-of-repository Python
consumer was not verified.

`clear()` drops vault-owned lookup references and invalidates older snapshots.
It does not and cannot claim secure zeroization of Python immutable strings.
File-mode process audit still creates operation-specific files with no timed
retention policy; configured stdout mode creates no file.

## Evidence boundaries and open work

This record does not verify:

- a packaged or installed Desktop application containing this change;
- a real browser extension, Office host, unified Office package, or certificate
  trust path;
- a live Pathumma, Tokenmind, TNER, or official AI for Thai call;
- deployment, resource/soak behavior, retry ownership, or platform logs;
- optional ML/OCR execution; or
- an external Python caller that mutates, copies, or pickles the newly
  immutable records or the lock-bearing vault.

The HTTP v1 response still exposes direct or reconstructable mapping fields.
Text-based residual findings can still be warning-only on local/provider
paths. Seeded-vault audit hygiene, localhost process identity, general
request-driven expiry sweeping and client session continuity, shared provider
orchestration, explicit-TNER whole-request failure, and exact PDF
entity-to-box alignment all remain open. Published Desktop 2.5.0 predates this
transaction and audit-correlation change.
