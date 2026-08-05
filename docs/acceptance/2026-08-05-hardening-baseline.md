# AI Guard hardening baseline

- Baseline finalized (UTC): `2026-08-05T07:16:15Z`
- Repository commit: `93a7108093c3999ff20963b6e06b634a211e1e91`
- Branch/upstream at measurement time: `main...origin/main`
- Product version: `2.5.0`
- Python: `3.13.14`
- Node used for JavaScript and Office gates: `22.23.2`
- Rust: `1.97.0`

This record preserves the clean control for the security, privacy, and
correctness hardening campaign. It is not new storefront, live-provider,
real-host, or release acceptance. The checkout was clean before and after the
commands, `HEAD` equaled its upstream, and `git diff --check` passed.
PII-bearing test values were synthetic. The suite also contains sanitized,
page-only copies of official blank forms; it does not contain completed real
forms. No request text, entity value, mapping, pseudonym, credential, provider
body, restored answer, or private absolute path was recorded here.

## Automated baseline

| Gate | Result |
|---|---|
| `python -m pytest -q -rs` | PASS — 1,677 passed, 5 skipped, 1 warning in 197.49 seconds |
| `python -m ruff check .` | PASS |
| `python -m ruff format --check .` | PASS — 217 files already formatted |
| `python scripts/check_version.py` | PASS — synchronized at `2.5.0` |
| `python scripts/check_release_readiness.py` | PASS |
| `git diff --check` | PASS |
| Root `npm ci` and `npm run test:js` | PASS — 12 files, 60 tests |
| Desktop JavaScript syntax checks | PASS |
| Office install, manifest validation, upstream validation, manifest packaging, typecheck, tests, and build | PASS — 9 files, 68 tests; 13 modules built |
| `cargo test` in `desktop/src-tauri` | PASS — 19 tests; binary and documentation targets contained no additional tests |
| Sidecar artifact and `scripts/smoke_exe.py` | PASS — packaged health, synthetic sanitize, process-tree termination, and port release |

Commands were run from the repository root unless a push-location says
otherwise:

```powershell
git status --short --branch
git rev-parse HEAD
git rev-parse '@{upstream}'
git diff --check

$env:PYTHONUTF8='1'
.\.venv\Scripts\python.exe -m pytest -q -rs
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe scripts\measure_perf.py
.\.venv\Scripts\python.exe scripts\check_version.py
.\.venv\Scripts\python.exe scripts\check_release_readiness.py

nvm use 22.23.2
npm ci
npm run test:js
node --check desktop\src\app.js
node --check desktop\src\api.js

Push-Location office-addin
npm ci --ignore-scripts --no-audit --no-fund
npm run validate:manifest
npm run validate:manifest:upstream
npm run package:manifest
npm run typecheck
npm test
npm run build
Pop-Location

Push-Location desktop\src-tauri
cargo test
Pop-Location

.\.venv\Scripts\python.exe scripts\build_sidecar.py
Copy-Item -LiteralPath dist\AIGuard.exe `
  -Destination desktop\src-tauri\binaries\aiguard-x86_64-pc-windows-msvc.exe
.\.venv\Scripts\python.exe scripts\smoke_exe.py
```

The five skips were
`tests/test_ocr.py:533`, `tests/test_ocr.py:542`,
`tests/test_ocr.py:611`, `tests/test_ocr.py:634`, and
`tests/test_ocr.py:643`. Each skipped because the optional `cv2` dependency was
not installed. They do not verify the OpenCV OCR path.

The Python suite emitted one `StarletteDeprecationWarning`: using `httpx` with
`starlette.testclient` is deprecated in favor of `httpx2`. Root dependency
installation reported one moderate vulnerability plus deprecation and
postinstall-allowlist warnings. Office installation reported six deprecated
packages. The supported Node 22 line was used for the recorded JavaScript and
Office results; the shell was returned to its pre-existing Node 24 selection
afterward.

The coordinator invocation of `build_sidecar.py` timed out while its child
PyInstaller process continued. PyInstaller completed and produced the ignored
`dist/AIGuard.exe`; its hash matched the explicitly staged ignored Tauri
sidecar before the smoke ran. The smoke did not install or open the Desktop
application. Port 8000 was free afterward. The artifact result is recorded;
the timed-out coordinator invocation is not described as a clean command exit.

## Performance control

The formal `scripts/measure_perf.py` invocation on unchanged `main` exited
nonzero:

| Operation | Measured | Committed baseline | Change | Gate |
|---|---:|---:|---:|---|
| Detect | 5.52 ms | 5.73 ms | -3.7% | PASS |
| Sanitize | 10.29 ms | 10.08 ms | +2.1% | PASS |
| Restore | 0.40 ms | 0.28 ms | +42.9% | FAIL |
| PDF redact | 69.87 ms | 67.67 ms | +3.3% | PASS |
| Resident memory | 152.7 MiB | 151.4 MiB | +0.9% | PASS |

Seven additional unchanged-tree controls were run in the same environment.
Two warm runs were broadly slower. The five later recorded runs measured:

| Run | Detect | Sanitize | Restore | PDF redact |
|---|---:|---:|---:|---:|
| 3 | 6.50 ms | 11.69 ms | 0.45 ms | 76.59 ms |
| 4 | 6.08 ms | 11.13 ms | 0.43 ms | 73.81 ms |
| 5 | 6.12 ms | 11.10 ms | 0.44 ms | 76.60 ms |
| 6 | 6.39 ms | 11.46 ms | 0.43 ms | 74.43 ms |
| 7 | 5.95 ms | 10.90 ms | 0.43 ms | 73.43 ms |

Restore remained above the committed 0.28 ms anchor despite no source change;
the absolute difference was about 0.15 ms. Resident memory remained within its
budget. This is evidence that the committed local timing anchor is currently
environment-sensitive, not evidence of a hardening regression and not
permission to move the baseline. A runtime branch must still run the formal
gate, compare against a same-session unchanged control, and carry its own
numbers.

## Evidence boundaries

The baseline does not verify:

- the optional OpenCV/PaddleOCR and ML environments;
- live Pathumma, Tokenmind, TNER, or official AI for Thai calls;
- an installed Desktop application, installer, or updater;
- an Office real host, unified production package, certificate trust, or
  sideload;
- a real browser extension against current external sites;
- an official platform deployment, resource/soak behavior, or platform logs;
- physical scans, handwriting, or broader real-form PDF accuracy.

Historical dated acceptance remains evidence for the exact named candidates.
The hardening campaign introduces additional response-minimization,
fail-closed, lifecycle, backend-identity, provider-parity, TNER-failure, and PDF
alignment gates. Any affected path requires fresh evidence after its behavior
changes.
