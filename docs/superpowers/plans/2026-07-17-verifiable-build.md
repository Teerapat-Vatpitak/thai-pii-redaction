# Verifiable Windows Build Implementation Plan (Horizon-2 #11)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pin every build input (Python deps with hashes, PyInstaller, GitHub Actions by commit SHA), publish SHA256SUMS + GitHub build provenance on releases, and automate the winget/scoop manifest bump — per spec `docs/superpowers/specs/2026-07-17-verifiable-build-design.md`.

**Architecture:** Two hash-pinned lockfiles (compiled with `uv pip compile --universal --generate-hashes`) feed CI and the release build; a new `checksums-and-attest` job in release.yml hashes + attests the actual release assets; a stdlib-only local script rewrites the 4 packaging manifests from a published release's SHA256SUMS.

**Tech Stack:** uv (lock compiler, dev-time only), pip `--require-hashes`, GitHub Actions, `actions/attest-build-provenance`, Python stdlib (`urllib`, `re`, `json`), pytest.

## Global Constraints

- Work on a feature branch (suggested: `feat/h2-11-verifiable-build`), PR to `main`. Never commit to `main` directly.
- **Never touch `CLAUDE.md`** — the controller syncs it after merge (workflow convention).
- Windows dev box: run Python as `.\.venv\Scripts\python.exe` with `$env:PYTHONUTF8='1'` set first. Test commands below write `python` for brevity — substitute the venv path.
- Commit messages: conventional style, **no Co-Authored-By trailer of any kind**.
- `requirements.txt` / `requirements-web.txt` keep their `>=` floors unchanged — locks are additive files.
- CI job `pytest-core-only` stays on unpinned `requirements.txt` **by design** (it guards the end-user `pip install` path). Do not switch it to a lock.
- Action SHA pins (resolved 2026-07-17, do not re-resolve — these are the reviewed values):
  - `actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5 # v4.3.1`
  - `actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065 # v5.6.0`
  - `actions/setup-node@49933ea5288caeca8642d1e84afbd3f7d6820020 # v4.4.0`
  - `dtolnay/rust-toolchain@4cda84d5c5c54efe2404f9d843567869ab1699d4 # stable branch, 2026-07-16` — **must add `with: toolchain: stable`** (this action normally reads the toolchain from the `@ref`; a SHA ref breaks that)
  - `swatinem/rust-cache@c19371144df3bb44fab255c43d04cbc2ab54d1c4 # v2.9.1`
  - `tauri-apps/tauri-action@84b9d35b5fc46c1e45415bdb6144030364f7ebc5 # v0.6.2`
  - `actions/attest-build-provenance@0f67c3f4856b2e3261c31976d6725780e5e4c373 # v4.1.1`
- The `checksums-and-attest` job (Task 3) **cannot run before the next real tag** — same UNTESTED status as release.yml's mac/linux legs. Do not claim it verified; the header comment in release.yml must say so.

---

### Task 1: Lockfiles, generator script, coverage tests, build_sidecar consumption

**Files:**
- Create: `requirements-build.txt`
- Create: `scripts/lock_deps.py`
- Create: `requirements.lock` (generated), `requirements-build.lock` (generated)
- Create: `tests/test_lock_coverage.py`
- Modify: `scripts/build_sidecar.py:81` (the `pip install pyinstaller` line)

**Interfaces:**
- Produces: `requirements.lock` (pins core+web, consumed by ci.yml Task 2), `requirements-build.lock` (pins core+web+pyinstaller, consumed by ci.yml/smoke/release Tasks 2-3 and `build_sidecar.py`), `scripts/lock_deps.py` with module-level `LOCKS: list[tuple[str, list[str]]]` and `compile_args(output: str, inputs: list[str]) -> list[str]`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_lock_coverage.py`:

```python
"""Name-level guard that the lockfiles stay in sync with their .txt sources.

Not a resolver: it only checks that every package declared in the source
requirements appears pinned (`name==`) in the lock, so a
forgot-to-regenerate mistake fails fast. Hash correctness is enforced by
pip --require-hashes in CI, not here.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

_spec = importlib.util.spec_from_file_location("lock_deps", ROOT / "scripts" / "lock_deps.py")
lock_deps = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lock_deps)


def _norm(name: str) -> str:
    # PEP 503 name normalization
    return re.sub(r"[-_.]+", "-", name).lower()


def _source_names(*req_files: str) -> set[str]:
    names = set()
    for fname in req_files:
        for line in (ROOT / fname).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("-"):
                continue
            m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)", line)
            if m:
                names.add(_norm(m.group(1)))
    return names


def _locked_names(lock_file: str) -> set[str]:
    path = ROOT / lock_file
    if not path.is_file():
        pytest.fail(f"{lock_file} missing -- run: python scripts/lock_deps.py")
    text = path.read_text(encoding="utf-8")
    return {
        _norm(m.group(1))
        for m in re.finditer(r"(?m)^([A-Za-z0-9][A-Za-z0-9._-]*)==", text)
    }


def test_requirements_lock_covers_core_and_web():
    missing = _source_names("requirements.txt", "requirements-web.txt") - _locked_names(
        "requirements.lock"
    )
    assert not missing, (
        f"missing from requirements.lock: {sorted(missing)} -- "
        "regenerate with: python scripts/lock_deps.py"
    )


def test_build_lock_covers_sources_and_pyinstaller():
    locked = _locked_names("requirements-build.lock")
    missing = _source_names(
        "requirements.txt", "requirements-web.txt", "requirements-build.txt"
    ) - locked
    assert not missing, (
        f"missing from requirements-build.lock: {sorted(missing)} -- "
        "regenerate with: python scripts/lock_deps.py"
    )
    assert "pyinstaller" in locked


def test_lock_deps_compile_args():
    outputs = [o for o, _ in lock_deps.LOCKS]
    assert outputs == ["requirements.lock", "requirements-build.lock"]
    args = lock_deps.compile_args(*lock_deps.LOCKS[0])
    for flag in ("--universal", "--generate-hashes", "--python-version"):
        assert flag in args, f"{flag} missing from uv invocation"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_lock_coverage.py -v`
Expected: FAIL at import time — `FileNotFoundError` loading `scripts/lock_deps.py` (doesn't exist yet).

- [ ] **Step 3: Create `requirements-build.txt`**

```
# Build tooling for the packaged sidecar (scripts/build_sidecar.py).
# Source of the PyInstaller floor; the exact pinned version + hashes live in
# requirements-build.lock (regenerate with scripts/lock_deps.py).
pyinstaller>=6.0
```

- [ ] **Step 4: Create `scripts/lock_deps.py`**

```python
#!/usr/bin/env python3
"""Regenerate the dependency lockfiles (requirements.lock, requirements-build.lock).

Uses `uv pip compile --universal --generate-hashes` so a single lock serves
every platform. pip-tools would resolve for the compiling platform only and
silently drop e.g. uvloop (uvicorn[standard]'s Linux-only extra) when run on
Windows; uv's --universal mode keeps the environment markers instead.

Run after editing any requirements*.txt, then review the lock diff:

    python scripts/lock_deps.py

CI installs the locks with `pip install --require-hashes`, which is why the
hashes matter: a tampered or swapped wheel fails the install outright.
uv itself is installed ad hoc (not pinned) -- the compile is a dev-time
action whose output is always reviewed as a diff before committing.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# (output lockfile, source .txt inputs) -- order matters for test_lock_coverage.
LOCKS: list[tuple[str, list[str]]] = [
    ("requirements.lock", ["requirements.txt", "requirements-web.txt"]),
    (
        "requirements-build.lock",
        ["requirements.txt", "requirements-web.txt", "requirements-build.txt"],
    ),
]


def compile_args(output: str, inputs: list[str]) -> list[str]:
    """The uv invocation for one lockfile (separate function so tests can pin
    the flags without running uv). Relative paths + cwd=ROOT keep the
    autogenerated header identical no matter which machine regenerates."""
    return [
        sys.executable, "-m", "uv", "pip", "compile",
        "--universal", "--generate-hashes",
        "--python-version", "3.13",
        "--output-file", output,
        *inputs,
    ]


def main() -> None:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", "uv"])
    for output, inputs in LOCKS:
        print(f"compiling {output} <- {', '.join(inputs)}")
        subprocess.check_call(compile_args(output, inputs), cwd=ROOT)
    print("done -- review the lock diff before committing")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Generate the locks**

Run: `python scripts/lock_deps.py`
Expected: prints `compiling requirements.lock <- ...` then `compiling requirements-build.lock <- ...` then `done`; `requirements.lock` and `requirements-build.lock` appear at repo root. Open `requirements.lock` and eyeball: every entry is `name==X.Y.Z \` followed by `--hash=sha256:...` lines; Linux-only entries (e.g. `uvloop`) carry a `; sys_platform ...` marker.

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_lock_coverage.py -v`
Expected: 3 passed.

- [ ] **Step 7: Point `build_sidecar.py` at the build lock**

In `scripts/build_sidecar.py`, replace the first line of `main()`:

```python
    subprocess.check_call([PY, "-m", "pip", "install", "--quiet", "pyinstaller"])
```

with:

```python
    # Hash-pinned build tooling (Horizon-2 #11): same PyInstaller as CI/release.
    subprocess.check_call([
        PY, "-m", "pip", "install", "--quiet", "--require-hashes",
        "-r", str(ROOT / "requirements-build.lock"),
    ])
```

- [ ] **Step 8: Sanity-check the lock installs under --require-hashes**

Run: `python -m pip install --dry-run --require-hashes -r requirements-build.lock`
Expected: resolves without a hash error (output ends with `Would install ...` or `Requirement already satisfied` lines; downloads once, may take a few minutes). If pip reports a hash mismatch or "requires all requirements to be hashed", the lock is malformed — stop and fix before committing.

- [ ] **Step 9: Commit**

```bash
git add requirements-build.txt requirements.lock requirements-build.lock scripts/lock_deps.py scripts/build_sidecar.py tests/test_lock_coverage.py
git commit -m "build: hash-pinned dependency lockfiles via uv universal compile (Horizon-2 #11)"
```

---

### Task 2: SHA-pin ci.yml + smoke-crossplatform.yml, install from locks, dependabot

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `.github/workflows/smoke-crossplatform.yml`
- Create: `.github/dependabot.yml`

**Interfaces:**
- Consumes: `requirements.lock`, `requirements-build.lock` from Task 1.
- Produces: nothing downstream; Task 3 applies the same pin values to release.yml (SHAs listed in Global Constraints).

- [ ] **Step 1: Pin every action in `ci.yml`**

Apply these exact replacements (every occurrence — `actions/checkout@v4` appears 7x, `actions/setup-python@v5` 4x, `actions/setup-node@v4` 2x, `dtolnay/rust-toolchain@stable` 2x, `swatinem/rust-cache@v2` 1x):

| old | new |
|---|---|
| `uses: actions/checkout@v4` | `uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5 # v4.3.1` |
| `uses: actions/setup-python@v5` | `uses: actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065 # v5.6.0` |
| `uses: actions/setup-node@v4` | `uses: actions/setup-node@49933ea5288caeca8642d1e84afbd3f7d6820020 # v4.4.0` |
| `uses: dtolnay/rust-toolchain@stable` | `uses: dtolnay/rust-toolchain@4cda84d5c5c54efe2404f9d843567869ab1699d4 # stable branch, 2026-07-16` |
| `uses: swatinem/rust-cache@v2` | `uses: swatinem/rust-cache@c19371144df3bb44fab255c43d04cbc2ab54d1c4 # v2.9.1` |

Both `dtolnay/rust-toolchain` uses need the toolchain input added. The `rust` job's step becomes:

```yaml
      - name: Set up Rust
        uses: dtolnay/rust-toolchain@4cda84d5c5c54efe2404f9d843567869ab1699d4 # stable branch, 2026-07-16
        with:
          toolchain: stable
```

and the `windows-exe-smoke` job's step becomes:

```yaml
      - name: Set up Rust (build_sidecar reads the host triple from rustc)
        uses: dtolnay/rust-toolchain@4cda84d5c5c54efe2404f9d843567869ab1699d4 # stable branch, 2026-07-16
        with:
          toolchain: stable
```

- [ ] **Step 2: Switch the `pytest` job to the lock**

In ci.yml's `pytest` job, replace:

```yaml
        with:
          python-version: "3.13"
          cache: pip

      - name: Install deps (core + web)
        run: python -m pip install --upgrade pip -r requirements.txt -r requirements-web.txt
```

with:

```yaml
        with:
          python-version: "3.13"
          cache: pip
          cache-dependency-path: requirements*.lock

      - name: Install deps (locked core + web)
        run: |
          python -m pip install --upgrade pip
          python -m pip install --require-hashes -r requirements.lock
```

- [ ] **Step 3: Keep `pytest-core-only` unpinned, say so explicitly**

In the `pytest-core-only` job, replace:

```yaml
      - name: Install deps (core only)
        run: python -m pip install --upgrade pip -r requirements.txt
```

with:

```yaml
      - name: Install deps (core only, deliberately UNpinned)
        # This job guards the end-user `pip install -r requirements.txt` path,
        # so it must keep resolving the loose `>=` floors -- do not switch it
        # to a lockfile (Horizon-2 #11 pins every other install).
        run: python -m pip install --upgrade pip -r requirements.txt
```

- [ ] **Step 4: Switch `windows-exe-smoke` to the build lock**

In the `windows-exe-smoke` job, replace:

```yaml
        with:
          python-version: "3.13"
          cache: pip

      - name: Install deps (core + web, for the sidecar build)
        run: python -m pip install --upgrade pip -r requirements.txt -r requirements-web.txt
```

with:

```yaml
        with:
          python-version: "3.13"
          cache: pip
          cache-dependency-path: requirements*.lock

      - name: Install deps (locked, incl. the PyInstaller pin)
        run: |
          python -m pip install --upgrade pip
          python -m pip install --require-hashes -r requirements-build.lock
```

- [ ] **Step 5: Same treatment for `smoke-crossplatform.yml`**

Pin its three actions per the table in Step 1 (`actions/checkout@v4` 1x, `actions/setup-python@v5` 1x, `dtolnay/rust-toolchain@stable` 1x — add `with: toolchain: stable`), and replace:

```yaml
      - name: Install Python deps (for the sidecar build)
        run: python -m pip install --upgrade pip -r requirements.txt -r requirements-web.txt
```

with:

```yaml
      - name: Install Python deps (locked, incl. the PyInstaller pin)
        run: |
          python -m pip install --upgrade pip
          python -m pip install --require-hashes -r requirements-build.lock
```

- [ ] **Step 6: Create `.github/dependabot.yml`**

```yaml
# Keeps the SHA-pinned actions fresh (Horizon-2 #11): dependabot PRs bump the
# pinned commit + version comment together. Python deps are NOT managed here --
# regenerate the lockfiles by hand via scripts/lock_deps.py.
version: 2
updates:
  - package-ecosystem: github-actions
    directory: /
    schedule:
      interval: weekly
```

- [ ] **Step 7: Verify the YAML still parses**

Run: `python -c "import yaml, glob; [yaml.safe_load(open(f, encoding='utf-8')) for f in glob.glob('.github/workflows/*.yml') + ['.github/dependabot.yml']]; print('yaml ok')"`
(PyYAML is available via uvicorn[standard].)
Expected: `yaml ok`

- [ ] **Step 8: Verify no unpinned `uses:` remain in the two files**

Run: `git grep -nE "uses: [^#]+@(v[0-9][0-9.]*|stable|master|main)\s*$" .github/workflows/ci.yml .github/workflows/smoke-crossplatform.yml`
Expected: no output (exit code 1).

- [ ] **Step 9: Commit**

```bash
git add .github/workflows/ci.yml .github/workflows/smoke-crossplatform.yml .github/dependabot.yml
git commit -m "ci: SHA-pin all actions + install from hash-pinned locks (Horizon-2 #11)"
```

---

### Task 3: release.yml — pins, lock install, checksums-and-attest job, verify-ready release body

**Files:**
- Modify: `.github/workflows/release.yml` (full final content below)

**Interfaces:**
- Consumes: `requirements-build.lock` (Task 1), SHA pins (Global Constraints).
- Produces: release assets `SHA256SUMS` + provenance attestations; `scripts/update_packaging.py` (Task 4) downloads that `SHA256SUMS`; README (Task 5) documents the same two verify commands.

- [ ] **Step 1: Replace `.github/workflows/release.yml` with this exact content**

```yaml
# Build installers for Windows / macOS / Linux, attach them to a GitHub
# Release, then hash + attest everything.
#
# STATUS: the macOS/Linux legs and the checksums-and-attest job are UNTESTED
# until the next real tag (they need real GitHub-hosted runners + a real
# draft release, which can't be exercised from a Windows dev box). The
# Windows sidecar build (scripts/build_sidecar.py) and the Rust compile were
# verified locally. Review the first tagged run's logs before relying on it.
#
# Verifiability (Horizon-2 #11): every build input is pinned (lockfile with
# hashes, PyInstaller pin, actions by commit SHA), and every release asset is
# covered by SHA256SUMS + GitHub build provenance (gh attestation verify).
# This is origin + integrity verification, NOT bit-for-bit reproducibility.
#
# Trigger: push a tag like `v0.1.0`, or run manually (workflow_dispatch --
# note the checksums job resolves the release by github.ref_name, so a
# manual run from a branch will fail that job harmlessly).

name: Release

on:
  push:
    tags:
      - "v*"
  workflow_dispatch:

permissions:
  contents: write # create the Release and upload assets

jobs:
  build:
    strategy:
      fail-fast: false
      matrix:
        os: [windows-latest, macos-latest, ubuntu-latest]
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5 # v4.3.1

      - name: Linux system deps (WebKitGTK for Tauri)
        if: matrix.os == 'ubuntu-latest'
        run: |
          sudo apt-get update
          sudo apt-get install -y libwebkit2gtk-4.1-dev libappindicator3-dev librsvg2-dev patchelf

      - name: Set up Python
        uses: actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065 # v5.6.0
        with:
          python-version: "3.13"

      - name: Install Python deps (locked, incl. the PyInstaller pin)
        run: |
          python -m pip install --upgrade pip
          python -m pip install --require-hashes -r requirements-build.lock

      - name: Pre-download the offline NER model
        # build_sidecar.py bundles ~/pythainlp-data so NER works offline; importing
        # the thainer engine once fetches it into the runner's home dir.
        run: python -c "from pythainlp.tag import NER; NER(engine='thainer')"

      - name: Set up Rust
        uses: dtolnay/rust-toolchain@4cda84d5c5c54efe2404f9d843567869ab1699d4 # stable branch, 2026-07-16
        with:
          toolchain: stable

      - name: Cache cargo
        uses: swatinem/rust-cache@c19371144df3bb44fab255c43d04cbc2ab54d1c4 # v2.9.1
        with:
          workspaces: desktop/src-tauri

      - name: Set up Node
        uses: actions/setup-node@49933ea5288caeca8642d1e84afbd3f7d6820020 # v4.4.0
        with:
          node-version: "lts/*"

      - name: Build + stage the sidecar (cross-platform, single source)
        run: python scripts/build_sidecar.py

      - name: Install desktop (Tauri CLI) deps
        working-directory: desktop
        run: npm install

      - name: Build the Tauri app and publish the Release
        uses: tauri-apps/tauri-action@84b9d35b5fc46c1e45415bdb6144030364f7ebc5 # v0.6.2
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          TAURI_SIGNING_PRIVATE_KEY: ${{ secrets.TAURI_SIGNING_PRIVATE_KEY }}
          TAURI_SIGNING_PRIVATE_KEY_PASSWORD: ${{ secrets.TAURI_SIGNING_PRIVATE_KEY_PASSWORD }}
        with:
          projectPath: desktop
          tagName: ${{ github.ref_name }}
          releaseName: "AI Guard ${{ github.ref_name }}"
          releaseBody: |
            AI Guard desktop — installers for Windows / macOS / Linux.

            **Windows:** the installer is unsigned by design (trust comes from
            verifiability, not a paid certificate — see SECURITY.md). SmartScreen
            will warn on first run: choose **More info → Run anyway**.

            **Verify your download** — every asset is listed in `SHA256SUMS` and
            carries GitHub build provenance (both attached by the
            checksums-and-attest job a few minutes after the assets appear):

            - Integrity, Windows: `certutil -hashfile <file> SHA256`, compare
              against the matching line in `SHA256SUMS`
            - Integrity, macOS/Linux: `sha256sum -c SHA256SUMS --ignore-missing`
            - Provenance (proves GitHub Actions built the file from this repo at
              this tag): `gh attestation verify <file> -R Teerapat-Vatpitak/thai-pii-redaction`

            This proves origin and integrity; it is not a claim of bit-for-bit
            reproducibility.
          releaseDraft: true
          prerelease: false

  checksums-and-attest:
    # Hash + attest what users will actually download: pull every asset back
    # off the draft release, publish SHA256SUMS as another asset, and attach
    # SLSA build provenance (verify with `gh attestation verify`).
    name: checksums + attestation
    needs: build
    runs-on: ubuntu-latest
    permissions:
      contents: write # upload SHA256SUMS to the release
      id-token: write # sign the attestation (Sigstore)
      attestations: write # store the attestation
    steps:
      - name: Download all release assets
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          TAG: ${{ github.ref_name }}
        run: |
          mkdir assets
          if ! gh release download "$TAG" --repo "$GITHUB_REPOSITORY" --dir assets; then
            echo "direct download failed (draft edge case); resolving release id via API"
            rid=$(gh api "repos/$GITHUB_REPOSITORY/releases" --jq ".[] | select(.tag_name==\"$TAG\") | .id" | head -1)
            [ -n "$rid" ] || { echo "ERROR: no release found for tag $TAG"; exit 1; }
            gh api "repos/$GITHUB_REPOSITORY/releases/$rid/assets" --paginate \
              --jq '.[] | [.id, .name] | @tsv' |
            while IFS=$'\t' read -r aid name; do
              echo "downloading $name"
              gh api -H "Accept: application/octet-stream" \
                "repos/$GITHUB_REPOSITORY/releases/assets/$aid" > "assets/$name"
            done
          fi
          ls -l assets
          [ "$(ls -A assets)" ] || { echo "ERROR: zero assets downloaded for $TAG"; exit 1; }

      - name: Generate SHA256SUMS
        run: |
          cd assets
          sha256sum * > ../SHA256SUMS
          mv ../SHA256SUMS .
          cat SHA256SUMS

      - name: Upload SHA256SUMS to the release
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          TAG: ${{ github.ref_name }}
        run: gh release upload "$TAG" assets/SHA256SUMS --repo "$GITHUB_REPOSITORY" --clobber

      - name: Attest build provenance for every asset
        uses: actions/attest-build-provenance@0f67c3f4856b2e3261c31976d6725780e5e4c373 # v4.1.1
        with:
          subject-path: assets/*
```

- [ ] **Step 2: Verify the YAML parses and no unpinned `uses:` remain**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/release.yml', encoding='utf-8')); print('yaml ok')"`
Expected: `yaml ok`

Run: `git grep -nE "uses: [^#]+@(v[0-9][0-9.]*|stable|master|main)\s*$" .github/workflows/release.yml`
Expected: no output (exit code 1).

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/release.yml
git commit -m "release: SHA256SUMS + build provenance job, pinned actions and deps (Horizon-2 #11)"
```

---

### Task 4: `scripts/update_packaging.py` + tests + packaging/README checklist

**Files:**
- Create: `scripts/update_packaging.py`
- Create: `tests/test_update_packaging.py`
- Modify: `packaging/README.md` (the "Updating for a new release" section, lines 60-68)

**Interfaces:**
- Consumes: the release's `SHA256SUMS` asset (Task 3 format: `<64-hex>  <filename>` per line) and the GitHub REST release object (`published_at`).
- Produces: CLI `python scripts/update_packaging.py [vX.Y.Z]`; module functions `installer_name(version) -> str`, `parse_hash(sums_text, filename) -> str`, `plan_writes(root: Path, version: str, sha256: str, release_date: str) -> list[tuple[Path, str]]` (pure — computes every rewrite, `sys.exit`s writing nothing on any layout mismatch), `fetch_sums(tag) -> str`, `fetch_release_date(tag) -> str`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_update_packaging.py`:

```python
"""scripts/update_packaging.py: winget/scoop manifest bump (Horizon-2 #11).

Runs against a throwaway copy of packaging/ under tmp_path (same convention
as test_version_source.py) and never touches the network -- only the pure
functions (parse_hash, plan_writes) are exercised.
"""
from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

_spec = importlib.util.spec_from_file_location(
    "update_packaging", ROOT / "scripts" / "update_packaging.py"
)
up = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(up)

SHA = "ab" * 32
DATE = "2026-08-01"


@pytest.fixture()
def pkg_root(tmp_path):
    shutil.copytree(ROOT / "packaging", tmp_path / "packaging")
    return tmp_path


def _apply(root, version="9.9.9", sha=SHA, date=DATE):
    for path, text in up.plan_writes(root, version, sha, date):
        path.write_text(text, encoding="utf-8")


def _snapshot(root):
    return {
        p: p.read_text(encoding="utf-8")
        for p in sorted((root / "packaging").rglob("*"))
        if p.is_file()
    }


def test_installer_name():
    assert up.installer_name("9.9.9") == "AI.Guard_9.9.9_x64-setup.exe"


def test_parse_hash_standard_format():
    sums = f"{SHA}  AI.Guard_9.9.9_x64-setup.exe\n{'cd' * 32}  latest.json\n"
    assert up.parse_hash(sums, "AI.Guard_9.9.9_x64-setup.exe") == SHA


def test_parse_hash_binary_marker():
    sums = f"{SHA} *AI.Guard_9.9.9_x64-setup.exe\n"
    assert up.parse_hash(sums, "AI.Guard_9.9.9_x64-setup.exe") == SHA


def test_parse_hash_missing_exits():
    with pytest.raises(SystemExit):
        up.parse_hash(f"{SHA}  something-else.dmg\n", "AI.Guard_9.9.9_x64-setup.exe")


def test_rewrites_all_four_files(pkg_root):
    _apply(pkg_root)
    winget = pkg_root / "packaging" / "winget"
    for fname in (
        "Teerapat-Vatpitak.AIGuard.yaml",
        "Teerapat-Vatpitak.AIGuard.locale.en-US.yaml",
    ):
        assert "PackageVersion: 9.9.9" in (winget / fname).read_text(encoding="utf-8")
    inst = (winget / "Teerapat-Vatpitak.AIGuard.installer.yaml").read_text(
        encoding="utf-8"
    )
    assert "PackageVersion: 9.9.9" in inst
    assert "DisplayVersion: 9.9.9" in inst
    assert f"ReleaseDate: {DATE}" in inst
    assert (
        "InstallerUrl: https://github.com/Teerapat-Vatpitak/thai-pii-redaction"
        "/releases/download/v9.9.9/AI.Guard_9.9.9_x64-setup.exe" in inst
    )
    assert f"InstallerSha256: {SHA.upper()}" in inst
    scoop = json.loads(
        (pkg_root / "packaging" / "scoop" / "aiguard.json").read_text(encoding="utf-8")
    )
    assert scoop["version"] == "9.9.9"
    assert scoop["architecture"]["64bit"]["url"].endswith(
        "AI.Guard_9.9.9_x64-setup.exe#/dl.7z"
    )
    assert scoop["architecture"]["64bit"]["hash"] == SHA


def test_autoupdate_template_untouched(pkg_root):
    _apply(pkg_root)
    scoop = json.loads(
        (pkg_root / "packaging" / "scoop" / "aiguard.json").read_text(encoding="utf-8")
    )
    assert "$version" in scoop["autoupdate"]["architecture"]["64bit"]["url"]


def test_idempotent(pkg_root):
    _apply(pkg_root)
    first = _snapshot(pkg_root)
    _apply(pkg_root)
    assert _snapshot(pkg_root) == first


def test_layout_drift_exits_without_writing(pkg_root):
    inst = pkg_root / "packaging" / "winget" / "Teerapat-Vatpitak.AIGuard.installer.yaml"
    inst.write_text(
        inst.read_text(encoding="utf-8").replace("InstallerSha256:", "InstallerSHA:"),
        encoding="utf-8",
    )
    before = _snapshot(pkg_root)
    with pytest.raises(SystemExit):
        up.plan_writes(pkg_root, "9.9.9", SHA, DATE)
    assert _snapshot(pkg_root) == before
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_update_packaging.py -v`
Expected: FAIL at import time — `FileNotFoundError` loading `scripts/update_packaging.py`.

- [ ] **Step 3: Create `scripts/update_packaging.py`**

```python
#!/usr/bin/env python3
"""Bump the packaging manifests (winget + scoop) to a released version.

Downloads SHA256SUMS from the GitHub release of the given tag, pulls the
Windows installer's hash out of it, and rewrites the four manifest files
under packaging/ (winget version/installer/locale + scoop json). Pure
stdlib -- no pip install needed, same as check_version.py.

Nothing is submitted anywhere: review the diff, then validate + submit
yourself per packaging/README.md.

Usage:
    python scripts/update_packaging.py           # tag = v<contents of VERSION>
    python scripts/update_packaging.py v2.3.0    # explicit tag
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO = "Teerapat-Vatpitak/thai-pii-redaction"


def installer_name(version: str) -> str:
    return f"AI.Guard_{version}_x64-setup.exe"


def fetch_text(url: str) -> str:
    with urllib.request.urlopen(url) as resp:
        return resp.read().decode("utf-8")


def fetch_sums(tag: str) -> str:
    return fetch_text(f"https://github.com/{REPO}/releases/download/{tag}/SHA256SUMS")


def fetch_release_date(tag: str) -> str:
    """YYYY-MM-DD the release was published (winget's ReleaseDate field)."""
    body = fetch_text(f"https://api.github.com/repos/{REPO}/releases/tags/{tag}")
    published = json.loads(body).get("published_at") or ""
    if not re.match(r"^\d{4}-\d{2}-\d{2}T", published):
        sys.exit(f"ERROR: release {tag} has no published_at -- is it published (not a draft)?")
    return published[:10]


def parse_hash(sums_text: str, filename: str) -> str:
    """Find `<hash>  <filename>` (sha256sum format; `*` binary marker tolerated)."""
    for line in sums_text.splitlines():
        m = re.match(r"^([0-9a-fA-F]{64})\s+\*?(.*)$", line.strip())
        if m and m.group(2) == filename:
            return m.group(1).lower()
    sys.exit(f"ERROR: {filename} not found in SHA256SUMS")


def _sub_exactly(pattern: str, repl: str, text: str, name: str) -> str:
    """re.subn that demands exactly one match -- layout drift fails loudly
    before anything is written (plan_writes computes all rewrites first)."""
    new_text, n = re.subn(pattern, repl, text, flags=re.MULTILINE)
    if n != 1:
        sys.exit(
            f"ERROR: {name}: pattern {pattern!r} matched {n}x (expected exactly 1) "
            "-- manifest layout changed; nothing was written"
        )
    return new_text


def plan_writes(
    root: Path, version: str, sha256: str, release_date: str
) -> list[tuple[Path, str]]:
    """Compute every rewrite up front; sys.exit (writing nothing) on mismatch."""
    winget = root / "packaging" / "winget"
    scoop_path = root / "packaging" / "scoop" / "aiguard.json"
    url = f"https://github.com/{REPO}/releases/download/v{version}/{installer_name(version)}"
    writes: list[tuple[Path, str]] = []

    for fname in (
        "Teerapat-Vatpitak.AIGuard.yaml",
        "Teerapat-Vatpitak.AIGuard.locale.en-US.yaml",
    ):
        path = winget / fname
        text = _sub_exactly(
            r"^PackageVersion: .+$",
            f"PackageVersion: {version}",
            path.read_text(encoding="utf-8"),
            fname,
        )
        writes.append((path, text))

    inst_path = winget / "Teerapat-Vatpitak.AIGuard.installer.yaml"
    text = inst_path.read_text(encoding="utf-8")
    text = _sub_exactly(r"^PackageVersion: .+$", f"PackageVersion: {version}", text, inst_path.name)
    text = _sub_exactly(r"^ReleaseDate: .+$", f"ReleaseDate: {release_date}", text, inst_path.name)
    text = _sub_exactly(r"^    DisplayVersion: .+$", f"    DisplayVersion: {version}", text, inst_path.name)
    text = _sub_exactly(r"^    InstallerUrl: .+$", f"    InstallerUrl: {url}", text, inst_path.name)
    text = _sub_exactly(
        r"^    InstallerSha256: .+$",
        f"    InstallerSha256: {sha256.upper()}",
        text,
        inst_path.name,
    )
    writes.append((inst_path, text))

    data = json.loads(scoop_path.read_text(encoding="utf-8"))
    try:
        data["version"] = version
        data["architecture"]["64bit"]["url"] = url + "#/dl.7z"
        data["architecture"]["64bit"]["hash"] = sha256.lower()
    except (KeyError, TypeError):
        sys.exit(
            f"ERROR: {scoop_path.name}: expected keys missing -- manifest layout "
            "changed; nothing was written"
        )
    writes.append((scoop_path, json.dumps(data, indent=4, ensure_ascii=False) + "\n"))
    return writes


def main() -> None:
    tag = (
        sys.argv[1]
        if len(sys.argv) > 1
        else "v" + (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    )
    if not re.fullmatch(r"v\d+\.\d+\.\d+", tag):
        sys.exit(f"ERROR: tag {tag!r} does not look like vX.Y.Z")
    version = tag[1:]
    sha256 = parse_hash(fetch_sums(tag), installer_name(version))
    release_date = fetch_release_date(tag)
    for path, text in plan_writes(ROOT, version, sha256, release_date):
        path.write_text(text, encoding="utf-8")
        print(f"updated {path.relative_to(ROOT)}")
    print(f"\n{tag}: installer sha256 {sha256}")
    print("Review the diff, then validate + submit per packaging/README.md.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_update_packaging.py -v`
Expected: 8 passed.

- [ ] **Step 5: Update the checklist in `packaging/README.md`**

Replace the section:

```markdown
## Updating for a new release

On each new tagged release, per artifact:

1. Download the installer and compute its SHA256:
   `gh release download vX.Y.Z -R Teerapat-Vatpitak/thai-pii-redaction --pattern "*x64-setup.exe"`
   then `certutil -hashfile <file> SHA256`.
2. Bump `PackageVersion`/`version`, the `InstallerUrl`/`url`, and the hash in all four files.
3. Re-validate (`winget validate`, and JSON-lint the Scoop file) before submitting.
```

with:

```markdown
## Updating for a new release

On each new tagged release (after the release is published — the script reads
the release's `SHA256SUMS` asset and `published_at` date):

1. Run `python scripts/update_packaging.py vX.Y.Z` (no argument = `v` + the repo
   `VERSION` file). It rewrites all four manifest files: version, `InstallerUrl`/`url`,
   `InstallerSha256`/`hash`, and `ReleaseDate`. It fails loudly and writes nothing
   if the release or the installer entry can't be found.
2. Review the diff, then re-validate (`winget validate --manifest packaging/winget`,
   and JSON-lint the Scoop file) before submitting.
```

- [ ] **Step 6: Commit**

```bash
git add scripts/update_packaging.py tests/test_update_packaging.py packaging/README.md
git commit -m "feat: update_packaging.py bumps winget/scoop manifests from a release's SHA256SUMS (Horizon-2 #11)"
```

---

### Task 5: README "Verify your download" section

**Files:**
- Modify: `README.md` (insert after the Option A numbered list, i.e. after the line `3. The app is not code-signed. ...` at line 41, before `### Option B · From source (developer alternative)`)

**Interfaces:**
- Consumes: the verify commands established in Task 3's release body (must stay consistent with them).

- [ ] **Step 1: Insert the section**

Insert between line 41 (`3. The app is not code-signed. ...`) and the `### Option B` heading:

```markdown
#### Verify your download (optional)

Every release ships a `SHA256SUMS` file plus [GitHub build provenance](https://docs.github.com/en/actions/security-for-github-actions/using-artifact-attestations) for each asset. Two independent checks:

- **Integrity** — the file wasn't corrupted or swapped in transit:
  - Windows: `certutil -hashfile AI.Guard_<version>_x64-setup.exe SHA256`, then compare with the matching line in `SHA256SUMS`
  - macOS/Linux: `sha256sum -c SHA256SUMS --ignore-missing`
- **Provenance** — the file was built by GitHub Actions from this repository at the tagged commit (requires the [GitHub CLI](https://cli.github.com/)): `gh attestation verify AI.Guard_<version>_x64-setup.exe -R Teerapat-Vatpitak/thai-pii-redaction`

These prove origin and integrity. They are **not** a claim of bit-for-bit reproducibility — rebuilding locally produces a functionally identical but not byte-identical binary (PyInstaller and NSIS embed timestamps). The build inputs are pinned instead: hash-locked Python dependencies (`requirements*.lock`), a pinned PyInstaller, and SHA-pinned CI actions.
```

- [ ] **Step 2: Sanity-check the markdown renders (heading levels, no broken emphasis)**

Run: `git diff README.md`
Expected: one hunk, inserted between Option A and Option B; `####` nests under `### Option A`.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: verify-your-download section (SHA256SUMS + attestation) in README (Horizon-2 #11)"
```

---

### Task 6: Final verification sweep

**Files:** none new — verification only.

- [ ] **Step 1: Full Python suite**

Run: `python -m pytest -q`
Expected: everything passes (baseline before this work: 464 passed; this branch adds 11 tests across test_lock_coverage.py + test_update_packaging.py). No skips beyond the pre-existing optional-dep skips.

- [ ] **Step 2: Version drift gate still green**

Run: `python scripts/check_version.py`
Expected: exit 0 (this branch must not touch any version-bearing file).

- [ ] **Step 3: JS harness untouched**

Run: `npm run test:js`
Expected: 33 tests pass (nothing in this branch touches extension/desktop JS).

- [ ] **Step 4: No unpinned actions anywhere**

Run: `git grep -nE "uses: [^#]+@(v[0-9][0-9.]*|stable|master|main)\s*$" .github/workflows/`
Expected: no output (exit code 1).

- [ ] **Step 5: Working tree clean, history tidy**

Run: `git status --short` (expect empty) and `git log --oneline main..HEAD` (expect the 5 task commits).

---

## Post-merge (controller, not a task for implementers)

- Sync `CLAUDE.md` (requirements split section: mention the lockfiles + lock_deps.py; running section unchanged).
- Update roadmap doc status + memory.
- The `checksums-and-attest` job and the lock-based release build get their first real exercise on the next tagged release — review that run's logs (this is recorded in release.yml's header).
