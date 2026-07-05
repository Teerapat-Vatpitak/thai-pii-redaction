# Phase 5: mac/linux Sidecar Smoke CI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically verify, on real macOS + Linux CI runners, that the packaged sidecar serves the API and that the F1 orphan-port watchdog frees port 8000 when the sidecar's parent is force-killed.

**Architecture:** A PyInstaller onefile runs as a bootloader parent plus a forked python child; on unix, `SIGKILL` to the bootloader (what Tauri does) does not reach the child, so `launcher.py:_watch_parent_and_exit` reaps it by watching `getppid()`. The smoke script reproduces exactly this: start the staged sidecar, confirm `/api/health`, kill the bootloader, assert port 8000 frees. A new workflow runs it on macOS + Linux.

**Tech Stack:** Python stdlib (subprocess/socket/urllib), pytest for the testable helpers, GitHub Actions matrix.

## Global Constraints

- The behavioral assertion is unix-only (the watchdog no-ops on Windows, where `taskkill /T` reaps the tree). The script refuses to run on `win32`.
- The script's first real run is on CI: a Windows dev box cannot exercise the unix watchdog. Local verification covers the testable helpers + the win32 refusal only.
- GUI, tray, and global-hotkey on mac/linux are out of scope here (need a real desktop session); they stay documented as manual verification.
- Sidecar binary is staged by `scripts/build_sidecar.py` at `desktop/src-tauri/binaries/aiguard-<rust-target-triple>` (no `.exe` on unix).
- No emoji. Commit messages: no `Co-Authored-By` trailer. Baseline `pytest` stays green.

## File Structure

- `scripts/smoke_sidecar.py` (new) — the lifecycle + watchdog smoke check, with small pure helpers.
- `tests/test_smoke_sidecar.py` (new) — unit tests for the helpers + the win32 refusal (run cross-platform).
- `.github/workflows/smoke-crossplatform.yml` (new) — macOS + Linux matrix that builds the sidecar and runs the smoke check.

---

### Task 1: The smoke script + unit tests

**Files:**
- Create: `scripts/smoke_sidecar.py`
- Test: `tests/test_smoke_sidecar.py`

**Interfaces:**
- Produces: `find_sidecar()`, `port_is_free(host, port)`, `main()` (refuses on win32). Consumed by the workflow in Task 2.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_smoke_sidecar.py`:

```python
import importlib.util
import socket
from pathlib import Path

import pytest

SPEC_PATH = Path(__file__).resolve().parent.parent / "scripts" / "smoke_sidecar.py"
_spec = importlib.util.spec_from_file_location("smoke_sidecar", SPEC_PATH)
smoke = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(smoke)


def test_port_is_free_false_when_bound():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        assert smoke.port_is_free("127.0.0.1", port) is False


def test_port_is_free_true_when_unbound():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    assert smoke.port_is_free("127.0.0.1", port) is True


def test_find_sidecar_raises_when_missing(monkeypatch):
    monkeypatch.setattr(smoke, "BIN_GLOB", "/no/such/dir/aiguard-*")
    with pytest.raises(FileNotFoundError):
        smoke.find_sidecar()


def test_main_refuses_on_win32(monkeypatch):
    monkeypatch.setattr(smoke.sys, "platform", "win32")
    with pytest.raises(SystemExit):
        smoke.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe -m pytest tests/test_smoke_sidecar.py -v`
Expected: FAIL at import (`scripts/smoke_sidecar.py` does not exist yet).

- [ ] **Step 3: Write the smoke script**

Create `scripts/smoke_sidecar.py`:

```python
#!/usr/bin/env python3
"""Cross-platform smoke test for the packaged sidecar's runtime lifecycle.

Runs on macOS/Linux CI to verify the F1 orphan-port watchdog on real kernels:
start the packaged sidecar, confirm it serves /api/health, then SIGKILL its
PyInstaller bootloader parent (as Tauri does on unix) and assert the orphaned
child exits and frees port 8000. Windows reaps the whole tree via `taskkill /T`,
so this check is unix-only and refuses to run on win32.
"""
import glob
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOST = "127.0.0.1"
PORT = 8000
BIN_GLOB = str(ROOT / "desktop" / "src-tauri" / "binaries" / "aiguard-*")


def find_sidecar():
    matches = sorted(m for m in glob.glob(BIN_GLOB) if not m.endswith(".d"))
    if not matches:
        raise FileNotFoundError(
            f"no staged sidecar matching {BIN_GLOB}; run scripts/build_sidecar.py first"
        )
    return matches[0]


def port_is_free(host=HOST, port=PORT):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1.0)
        return s.connect_ex((host, port)) != 0


def wait_for(pred, timeout, interval=0.5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(interval)
    return False


def health_ok():
    try:
        with urllib.request.urlopen(f"http://{HOST}:{PORT}/api/health", timeout=1.5) as r:
            return r.status == 200
    except Exception:
        return False


def run_smoke():
    binary = find_sidecar()
    print(f"sidecar: {binary}")
    os.chmod(binary, 0o755)
    proc = subprocess.Popen([binary])
    try:
        if not wait_for(health_ok, timeout=60):
            raise SystemExit("FAIL: sidecar did not serve /api/health within 60s")
        print("PASS: /api/health responded")
        # SIGKILL the PyInstaller bootloader parent (uncatchable, like Tauri's unix kill).
        proc.kill()
        proc.wait(timeout=10)
        # The orphaned python child's watchdog must detect the reparent and exit,
        # releasing port 8000.
        if not wait_for(port_is_free, timeout=15):
            raise SystemExit(
                "FAIL: port 8000 still bound 15s after killing the sidecar parent "
                "(watchdog did not reap the orphan)"
            )
        print("PASS: port 8000 freed after orphaning the sidecar")
    finally:
        if proc.poll() is None:
            proc.kill()


def main():
    if sys.platform == "win32":
        raise SystemExit(
            "smoke_sidecar is unix-only (the watchdog no-ops on Windows; "
            "taskkill /T handles the tree there)"
        )
    run_smoke()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe -m pytest tests/test_smoke_sidecar.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add scripts/smoke_sidecar.py tests/test_smoke_sidecar.py
git commit -m "test(ci): sidecar lifecycle + watchdog smoke check (unix) with unit tests"
```

---

### Task 2: The macOS + Linux smoke workflow

**Files:**
- Create: `.github/workflows/smoke-crossplatform.yml`

**Interfaces:**
- Consumes: `scripts/build_sidecar.py` (staging) and `scripts/smoke_sidecar.py` (Task 1).
- Produces: CI verification on `push` to `main` + `workflow_dispatch`.

- [ ] **Step 1: Write the workflow**

Create `.github/workflows/smoke-crossplatform.yml`:

```yaml
# Verify the packaged sidecar's runtime lifecycle + the F1 orphan-port watchdog
# on real macOS + Linux kernels. The Windows watchdog is a no-op (taskkill /T
# reaps the tree), so this is unix-only. Runs on merges to main + on demand.
name: Smoke (cross-platform)

on:
  push:
    branches: [main]
  workflow_dispatch:

jobs:
  smoke:
    strategy:
      fail-fast: false
      matrix:
        os: [macos-latest, ubuntu-latest]
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.13"

      - name: Install Python deps (for the sidecar build)
        run: python -m pip install --upgrade pip -r requirements.txt -r requirements-web.txt

      - name: Pre-download the offline NER model
        run: python -c "from pythainlp.tag import NER; NER(engine='thainer')"

      - name: Set up Rust (build_sidecar reads the host triple from rustc)
        uses: dtolnay/rust-toolchain@stable

      - name: Build + stage the sidecar
        run: python scripts/build_sidecar.py

      - name: Run the sidecar lifecycle + watchdog smoke check
        run: python scripts/smoke_sidecar.py
```

- [ ] **Step 2: Verify the workflow YAML parses**

Run: `$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe -m pip install --quiet pyyaml; .\.venv\Scripts\python.exe -c "import yaml; yaml.safe_load(open('.github/workflows/smoke-crossplatform.yml', encoding='utf-8')); print('ok')"`
Expected: `ok`

- [ ] **Step 3: Run the full Python suite (no regressions)**

Run: `$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe -m pytest -q`
Expected: all pass (baseline + the 4 new smoke helper tests).

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/smoke-crossplatform.yml
git commit -m "ci: macOS + Linux sidecar smoke workflow (watchdog verification)"
```

---

## Self-Review

- **Spec coverage:** `smoke_sidecar.py` reproducing the orphan-kill + port-free assertion (Task 1), the macOS+Linux workflow on push-to-main + dispatch (Task 2), the explicit GUI/tray/hotkey out-of-scope note (Global Constraints), first-run-on-CI limitation (Global Constraints). All Component-C points covered.
- **Placeholders:** none. The full script and workflow are inline.
- **Type consistency:** `find_sidecar` / `port_is_free` / `main` and the module global `BIN_GLOB` used in Task 1's tests match the script's definitions exactly. The staging path matches `scripts/build_sidecar.py` (`desktop/src-tauri/binaries/aiguard-<triple>`).
