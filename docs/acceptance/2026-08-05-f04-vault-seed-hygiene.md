# F-04 vault seed and audit hygiene

- Evidence date (UTC): `2026-08-05`
- Clean base commit: `7b9c3c80e05d9fb8fe6c7d00269c800ad5bf0849`
- Reviewed branch candidate: `a760c3b4d01c4a130574d1bc311e2ee7b2efa9d7`
- Product version: `2.5.0` (unchanged)
- Python: `3.13.14`

This record is current-source automated evidence for F-04 at exact candidate
`a760c3b`. It verifies the in-process vault seed/audit contract and
compatibility tests. It is not evidence of a changed public HTTP/worker wire
contract, a packaged or installed application, browser or Office real-host
behavior, a live provider, an official platform deployment, or a release.
Product version remains `2.5.0`; published v2.5.0 at `24914ab` predates this
change.

Tests used synthetic values. This record contains no request text, entity
value, mapping, pseudonym, credential, provider body, restored answer, or
private absolute path.

## Behavior established

`SessionVault.seed()` now checks a caller-held pseudonym directly under the
vault lifecycle lock:

- A new pair receives an opaque `seed:<uuid4>` entity ID, retains provenance
  through the existing `SEEDED` sentinel, and adds exactly one structural
  `seed` audit row.
- Replaying an identical pair returns the existing immutable record without
  changing table, reverse index, audit, access time, or record count.
- Reusing the pseudonym for a different original raises the constant
  `seed pseudonym collision` error before mutation. The error contains neither
  value.
- If the seed audit write fails, table, reverse index, audit rows, and access
  time roll back. Retrying then produces one complete mapping/audit pair.
- A failed seed is not visible to concurrent public lookups, exports, or
  trusted-pseudonym reads.
- A concurrent ordinary write and seed cannot both claim one pseudonym for
  different originals.

Public vault reads, writes, mapping export, trusted-pseudonym reads, audit
access, idle checks, clone, snapshot, restore, and clear now use the same
re-entrant lifecycle lock. Deterministic interleaving tests establish that
clone, snapshot, and clear wait until an ordinary write and its audit row are
complete.

`clear()` drops vault-owned table and reverse-index references. It may retain
the structural audit rows because seed IDs are now opaque. It does not and
cannot claim secure zeroization of Python immutable strings.

## Local verification

| Gate | Result |
|---|---|
| Full Python suite | PASS — 1,730 passed, 5 skipped, 1 warning in 181.42 seconds |
| Focused vault/stateless/worker/API/service matrix | PASS — 316 passed, 1 warning |
| Independent privacy/concurrency matrix | PASS — 316 passed |
| Vault contract and race tests | PASS — 45 passed |
| Documentation coverage and code-fixture checks | PASS — 30 passed |
| `python -m ruff check .` | PASS |
| `python -m ruff format --check .` | PASS — 217 files |
| Version synchronization | PASS — `2.5.0` |
| Release-readiness check | PASS |
| `git diff --check` | PASS |
| Sidecar build | PASS |
| Packaged sidecar smoke | PASS — health, synthetic sanitize, process-tree termination, and port release |
| Independent privacy/concurrency review | PASS — no remaining F-04 blocker |
| Independent current-truth documentation audit | PASS — no blocker |

The full Python warning was the existing Starlette/httpx deprecation warning.
The five skips were optional OpenCV OCR cases because `cv2` was not installed.
The sidecar build reported unavailable optional ML/OCR imports and model-cache
network warnings; the supported core artifact built and passed its smoke. The
smoke did not install or open the Desktop application.

The principal local commands were:

```powershell
$env:PYTHONUTF8='1'
.\.venv\Scripts\python.exe -m pytest `
  tests\test_step4_vault.py `
  tests\test_stateless.py `
  tests\test_stateless_leak_regression.py `
  tests\test_worker_handler.py `
  tests\test_api_demo.py `
  tests\test_restore_boundary.py `
  tests\test_models.py `
  tests\test_step3_pseudonymize.py `
  tests\test_step6_reverse.py `
  tests\test_leak_guard.py `
  tests\test_session_service.py `
  tests\test_step11_api.py `
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

The formal script remained red against the older committed timing anchor on
both this branch and an unchanged clean control. Five alternating runs in the
same environment produced these medians:

| Operation | Clean base | F-04 branch | Branch delta | Budget |
|---|---:|---:|---:|---:|
| Detect | 8.67 ms | 9.09 ms | +4.8% | within 20% |
| Sanitize | 15.39 ms | 17.26 ms | +12.2% | within 20% |
| Restore | 0.51 ms | 0.52 ms | +2.0% | within 20% |
| PDF redact | 107.37 ms | 109.84 ms | +2.3% | within 20% |
| Resident memory | 150.9 MiB | 151.4 MiB | +0.3% | within 15% |

The branch's measured runtime delta, including public-method locking, remained
inside the repository budget. The committed performance baseline was not
changed.

## Branch CI

[GitHub Actions run 31000935853](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31000935853)
passed at exact candidate `a760c3b`:

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
are not F-04 packaged-path acceptance.

## Review findings closed

Independent review found and closed three material defects before this
candidate:

1. Ordinary writes did not share the seed/lifecycle lock, allowing a
   conflicting seed and write to both succeed and allowing clone, snapshot, or
   clear to observe an incoherent graph.
2. An audit exception could leave a live seed mapping without its promised
   audit row.
3. During that failing publication, an unlocked reader could observe the
   provisional mapping and have its legitimate access/audit state erased by
   rollback.

The final regressions coordinate these interleavings with events rather than
timing sleeps.

## Compatibility and evidence boundaries

Direct Python callers will observe three intentional changes: `seed()` now
returns the existing or new `VaultRecord`, seed entity IDs are nondeterministic
`seed:<uuid4>` values rather than caller-derived text, and new-seed audit
actions are `seed` rather than `write`. No in-repository caller depends on the
old return, ID, or action, and no HTTP or worker wire schema changed.

Direct Python `write()` callers still control `entity_id`; production callers
use detector-generated UUIDs, but an arbitrary caller could supply unsafe text.
Some core paths read private vault indexes under single-threaded or
service-owned locking, so public-method locking is not a whole-pipeline
concurrency guarantee. `clear()` drops vault-owned references and does not
securely zeroize Python immutable strings.

This record does not verify:

- a packaged or installed Desktop application containing this change;
- a real browser extension, Office host, unified Office package, or certificate
  trust path;
- a live Pathumma, Tokenmind, TNER, or official AI for Thai call;
- deployment, resource/soak behavior, retry ownership, or platform logs;
- optional ML/OCR execution; or
- behavior of an unknown out-of-repository Python consumer.

HTTP v1 response minimization, mandatory text-based residual blocking, general
request-driven expiry sweeping and client session continuity, localhost
process identity, shared provider orchestration, explicit-TNER whole-request
failure, and exact PDF entity-to-box alignment remain open.
