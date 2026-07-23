# Verification matrix

Use the narrowest focused test while editing, then run every complete lane gate
whose files or behavior changed. Set UTF-8 before Python on Windows.

## Always

```powershell
git diff --check
$env:PYTHONUTF8='1'
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
```

## Core, API, worker, PDF, or shared Python

Focused:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_relevant_file.py -q
```

Complete:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

For dependency or packaging changes, also run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_lock_coverage.py tests\test_workflow_pins.py -q
```

## Browser extension or shared root JavaScript

```powershell
npm ci
npm run test:js
```

Real-site behavior remains acceptance pending until the exact extension
candidate is exercised on each declared site.

## Desktop

```powershell
npm ci
node --check desktop\src\app.js
node --check desktop\src\api.js
npm run test:js
cd desktop\src-tauri
cargo test
```

Packaged UI, sidecar lifecycle, installer, updater, and hotkeys require the
candidate artifact; source tests cannot close those gates.

## Microsoft 365 Add-in

```powershell
cd office-addin
npm ci --ignore-scripts --no-audit --no-fund
npm run validate:manifest
npm run typecheck
npm test
npm run build
```

When network access is appropriate, run `npm run validate:manifest:local` for
Microsoft XML schema validation. Schema validation does not replace Word,
Excel, or PowerPoint real-host acceptance.

## Version, CI, release, or packaging metadata

```powershell
.\.venv\Scripts\python.exe scripts\check_version.py
.\.venv\Scripts\python.exe scripts\check_release_readiness.py
.\.venv\Scripts\python.exe -m pytest `
  tests\test_version_source.py `
  tests\test_workflow_pins.py `
  tests\test_release_readiness.py -q
```

Use `scripts\bump_version.py X.Y.Z` only for an approved release change. Update
winget/scoop metadata only after the release publishes `SHA256SUMS`.

## Documentation-only

Run `git diff --check`, verify every relative link and command touched, and
compare claims against code/tests plus `docs/project-status.md`. Documentation
that changes version, release, manifests, or acceptance status also runs the
corresponding gate above.

## Live and real-host acceptance

Use only synthetic PII and do not persist raw request/provider bodies.

```powershell
.\.venv\Scripts\python.exe scripts\run_acceptance.py
.\.venv\Scripts\python.exe scripts\run_acceptance.py --live-pathumma --live-tner
```

The live command consumes credentials/quota. Run it only when explicitly in
scope. Browser, Desktop, Office, PDF visual, and official AI for Thai checks
must follow `docs/acceptance/README.md`; record weaker evidence as partial or
provisional.
