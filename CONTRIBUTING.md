# Contributing to AI Guard

Thanks for considering a contribution. This is a solo-maintained OSS project
(see [`ROADMAP.md`](ROADMAP.md) for direction), so please open an issue or
discussion before starting large changes — it saves everyone a rewritten PR.

## Dev setup

Prerequisites: Python 3.11+, git. Windows is the primary target platform;
Linux/macOS are supported for the core pipeline and CI.

```bash
git clone https://github.com/Teerapat-Vatpitak/thai-pii-redaction.git
cd thai-pii-redaction
```

Dependencies are split by layer — install only what you need:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt          # core (always needed)
.\.venv\Scripts\python.exe -m pip install -r requirements-web.txt      # FastAPI/uvicorn (app/server.py)
.\.venv\Scripts\python.exe -m pip install -r requirements-ml.txt       # MiniLM semantic detector + WangchanBERTa/union NER
.\.venv\Scripts\python.exe -m pip install -r requirements-ocr.txt      # PaddleOCR for scanned PDFs
```

**Windows only:** the console defaults to cp1252, which breaks on Thai/UTF-8
text. Set `PYTHONUTF8=1` before every Python invocation:

```powershell
$env:PYTHONUTF8='1'
```

`./run.ps1` (Windows) / `./run.sh` (git-bash/Linux/macOS) creates the venv,
installs deps, and starts the backend on first run — the fastest way to get
something running before you dig into a specific module.

## Running tests

```powershell
$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe -m pytest
```

Run a single test file or case the same way CI does:

```powershell
$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe -m pytest tests/test_foo.py::test_name -v
```

CI (`.github/workflows/ci.yml`) runs pytest on Windows + Linux, a
**core-only-install** job (only `requirements.txt` — every test that needs an
optional dependency must skip via `pytest.importorskip`/`skipif`, never error
at collection), Rust unit tests for the desktop shell, a JS syntax check, a
version-drift check, and a Windows packaged-exe smoke test. All of these must
pass before a PR merges.

## Repo layout (short version)

Full architecture: [`CLAUDE.md`](CLAUDE.md). In brief:

- `pii_redactor/` — the core pipeline (detection, pseudonymization, vault,
  reverse mapping, validation). Both storefronts sit on top of this.
- `app/server.py` — the FastAPI backend (`/api/*`), the browser extension's
  and desktop app's only entry point.
- `extension/` — the MV3 browser extension (primary UI).
- `desktop/` — the Tauri desktop shell (Rust + static frontend).
- `demo_cli.py`, `ai_guard.py` — the CLI storefront.
- `tests/` — one file per pipeline step, plus API/hardening/benchmark tests.
- `scripts/` — build, packaging, and release tooling (including
  `bump_version.py` / `check_version.py`, see below).

## Versioning

`VERSION` at repo root is the **single source of truth** for the product
version — `app/server.py`, the extension manifest, and the desktop app all
read from it (directly or via the bump/check scripts below). Don't hand-edit
a version string in any other file.

- To check every version-bearing file agrees with `VERSION`:
  `python scripts/check_version.py`
- To bump the version everywhere at once (maintainer-only, part of a release):
  `python scripts/bump_version.py <new-version>`

## Pull request conventions

- **Commit messages:** [Conventional Commits](https://www.conventionalcommits.org/)
  style (`feat:`, `fix:`, `docs:`, `test:`, `ci:`, `chore:`, ...), imperative
  mood, scoped where it helps (`feat(detector): ...`).
- **CI must be green** before merge — no exceptions, no `--no-verify`.
- **Tests are not optional.** New detection logic, API behavior, or scripts
  need a regression test in the same PR (TDD is the norm in this repo — see
  the existing `tests/test_step*.py` files for the pattern of one test file
  per pipeline step).
- **No hand-written volatile numbers.** Test counts, version strings, and
  platform lists drift the moment they're typed into prose by hand — cite
  them from a machine-readable source (`VERSION`, CI output) instead of
  hardcoding them in docs.
- **Recall over precision** for anything touching PII detection — when in
  doubt, a false positive (extra pseudonym) is much cheaper than a missed
  real PII leak. See "Design Invariants" in `CLAUDE.md`.
- Keep PRs scoped to one logical change; large refactors should be discussed
  first (open an issue, or check `ROADMAP.md` / `docs/superpowers/specs/` for
  an existing design doc covering the area).

## Reporting a security issue

Do not open a public issue for a vulnerability — see [`SECURITY.md`](SECURITY.md).
