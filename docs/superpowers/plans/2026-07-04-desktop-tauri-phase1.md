# AI Guard Desktop (Tauri) — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a working Windows desktop app (Tauri v2) that launches the existing AI Guard Python engine as a bundled sidecar and drives it through a native window with four screens (status, text mask/restore, PDF redaction, PDPA report).

**Architecture:** Tauri v2 shell (Rust) bundles the existing `AIGuard.exe` (PyInstaller onefile) as an `externalBin` sidecar. On launch the Rust core spawns the sidecar (FastAPI on `127.0.0.1:8000`) and kills its process tree on exit. A vanilla HTML/CSS/JS frontend (no framework, no bundler) polls `/api/health` until ready, then calls the existing `/api/*` endpoints via `fetch()`. No engine rewrite — the Python core and its 259 tests are reused unchanged.

**Tech Stack:** Tauri v2 (`tauri` 2.x, `tauri-plugin-shell` 2.x, `tauri-plugin-single-instance` 2.x), Rust (MSVC toolchain), vanilla ES-module JS, existing Python 3 / FastAPI backend, PyInstaller.

## Global Constraints

- On-device only: sidecar binds `127.0.0.1:8000`; the frontend calls only `http://127.0.0.1:8000` / `http://localhost:8000`. Never call a remote host.
- Reuse the engine: do NOT modify `pii_redactor/` or existing endpoints except the one additive `POST /api/shutdown` route in Task 2.
- No PII to disk from the desktop layer: the frontend keeps nothing on disk; the vault stays in the backend's memory.
- Thai text is UTF-8 everywhere; the sidecar is already built with `X utf8=1`.
- Windows-first. The `externalBin` target triple for this phase is `x86_64-pc-windows-msvc`.
- License note: this phase still bundles PyMuPDF (AGPL) via the existing `.exe`; the Apache-2.0 relicense + `pypdfium2` swap is a later phase and is out of scope here.
- New desktop code lives under `desktop/`. The sidecar binary lives at `desktop/src-tauri/binaries/aiguard-x86_64-pc-windows-msvc.exe` and is git-ignored (built artifact).
- Exact API field names come from `app/server.py`; copy them verbatim in the frontend.

---

### Task 1: Scaffold the Tauri v2 vanilla app

**Files:**
- Create: `desktop/` (whole Tauri project, generated)
- Create: `desktop/.gitignore` additions (or root `.gitignore`)
- Modify: root `.gitignore`

**Interfaces:**
- Produces: a runnable Tauri project at `desktop/` with `desktop/src/` (static frontend) and `desktop/src-tauri/` (Rust). Later tasks assume `frontendDist` = `../src`.

- [ ] **Step 1: Install prerequisites (one-time, manual)**

Confirm the toolchain (run each; all must succeed):

```powershell
rustc --version          # need 1.77+ ; if missing, install from https://rustup.rs (MSVC host)
rustc --print host-tuple # must print x86_64-pc-windows-msvc (older rustc used the flag name "host-triple")
node --version           # Node LTS — needed only for the scaffolder/CLI, not by end users
```

WebView2 is preinstalled on Windows 10 1803+/Windows 11. If `rustc` host triple is not `x86_64-pc-windows-msvc`, install the MSVC toolchain: `rustup default stable-x86_64-pc-windows-msvc`.

- [ ] **Step 2: Scaffold the vanilla template into `desktop/`**

Run **non-interactively** from the repo root (this step is done by the controller / a human, not a code subagent, since scaffolders can prompt):

```powershell
npm create tauri-app@latest -- desktop --template vanilla --manager npm --yes
```

This yields `desktop/index.html`, `desktop/src/`, `desktop/package.json`, and `desktop/src-tauri/` (with `Cargo.toml`, `tauri.conf.json`, `src/main.rs`, `src/lib.rs`, `build.rs`, `capabilities/`, `icons/`). If the CLI still prompts, choose: language JavaScript, template Vanilla, flavor JavaScript, manager npm.

- [ ] **Step 3: Verify the skeleton runs**

```powershell
cd desktop
npm install
npm run tauri dev
```

Expected: a native window titled with the scaffold's default name opens and shows the template page. Close it. If it fails to compile, resolve toolchain errors before continuing.

- [ ] **Step 4: Git-ignore build artifacts**

Add to the root `.gitignore`:

```gitignore
# Tauri desktop build artifacts
desktop/src-tauri/target/
desktop/src-tauri/binaries/
desktop/node_modules/
desktop/dist/
```

- [ ] **Step 5: Commit**

```powershell
git add desktop .gitignore
git commit -m "feat(desktop): scaffold Tauri v2 vanilla app shell"
```

---

### Task 2: Add `POST /api/shutdown` to the backend

Clean shutdown lets the Tauri app stop the sidecar gracefully before force-killing the process tree. This is a backend-only, independently testable change.

**Files:**
- Modify: `app/server.py` (add route near the other routes)
- Test: `tests/test_step11_api.py` (append a test)

**Interfaces:**
- Produces: `POST /api/shutdown` → `{"status": "shutting_down"}` (HTTP 200). Schedules process exit shortly after responding so the HTTP response is flushed first.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_step11_api.py`:

```python
def test_shutdown_endpoint_returns_ack(monkeypatch):
    """POST /api/shutdown acknowledges and schedules an exit without killing the test process synchronously."""
    import app.server as server

    called = {}

    def fake_schedule_exit():
        called["scheduled"] = True

    monkeypatch.setattr(server, "_schedule_exit", fake_schedule_exit)

    from fastapi.testclient import TestClient
    client = TestClient(server.app)
    resp = client.post("/api/shutdown")

    assert resp.status_code == 200
    assert resp.json() == {"status": "shutting_down"}
    assert called.get("scheduled") is True
```

- [ ] **Step 2: Run it to verify it fails**

```powershell
$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe -m pytest tests/test_step11_api.py::test_shutdown_endpoint_returns_ack -v
```

Expected: FAIL — `AttributeError: module 'app.server' has no attribute '_schedule_exit'` (and no `/api/shutdown` route → 404).

- [ ] **Step 3: Implement the route**

In `app/server.py`, add near the top-level imports:

```python
import os
import threading
```

Then add these definitions after the `root()` route:

```python
def _schedule_exit() -> None:
    """Exit the process shortly after the HTTP response is flushed.

    Localhost-only control path used by the desktop shell (Tauri) to stop the
    bundled sidecar gracefully. A short delay lets the 200 response reach the
    caller before the interpreter exits.
    """
    def _die() -> None:
        time.sleep(0.3)
        os._exit(0)

    threading.Thread(target=_die, daemon=True).start()


@app.post("/api/shutdown")
def shutdown():
    _schedule_exit()
    return {"status": "shutting_down"}
```

- [ ] **Step 4: Run the test to verify it passes**

```powershell
$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe -m pytest tests/test_step11_api.py::test_shutdown_endpoint_returns_ack -v
```

Expected: PASS.

- [ ] **Step 5: Run the full suite to confirm no regressions**

```powershell
$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe -m pytest -q
```

Expected: all prior tests still pass, count increased by 1 (260 passed).

- [ ] **Step 6: Commit**

```powershell
git add app/server.py tests/test_step11_api.py
git commit -m "feat(api): add localhost POST /api/shutdown for graceful sidecar stop"
```

---

### Task 3: Bundle `AIGuard.exe` as the sidecar

**Files:**
- Create: `desktop/build-sidecar.ps1`
- Modify: `desktop/src-tauri/tauri.conf.json`
- Modify: `desktop/src-tauri/Cargo.toml`
- Modify: `desktop/src-tauri/capabilities/default.json`

**Interfaces:**
- Consumes: `dist/AIGuard.exe` produced by the existing root `build_exe.ps1`.
- Produces: `desktop/src-tauri/binaries/aiguard-x86_64-pc-windows-msvc.exe`; a sidecar named `aiguard` invokable from Rust via `app.shell().sidecar("aiguard")`.

- [ ] **Step 1: Write the sidecar build script**

Create `desktop/build-sidecar.ps1`:

```powershell
# Build the AI Guard Python backend as a PyInstaller onefile, then copy it into
# the Tauri externalBin location with the required target-triple suffix.
$ErrorActionPreference = "Stop"
Set-Location -Path (Join-Path $PSScriptRoot "..")   # repo root

Write-Host "Building dist/AIGuard.exe via build_exe.ps1 ..."
./build_exe.ps1

$triple = (rustc --print host-tuple).Trim()          # expect x86_64-pc-windows-msvc (older rustc: host-triple)
$dest = Join-Path $PSScriptRoot "src-tauri/binaries"
New-Item -ItemType Directory -Force -Path $dest | Out-Null
Copy-Item "dist/AIGuard.exe" (Join-Path $dest "aiguard-$triple.exe") -Force

Write-Host "Sidecar staged: src-tauri/binaries/aiguard-$triple.exe"
```

- [ ] **Step 2: Run it and verify the binary exists**

```powershell
cd desktop
./build-sidecar.ps1
Test-Path src-tauri/binaries/aiguard-x86_64-pc-windows-msvc.exe
```

Expected: prints the staged path and `Test-Path` returns `True`.

- [ ] **Step 3: Declare the external binary in `tauri.conf.json`**

In `desktop/src-tauri/tauri.conf.json`, set `productName`, `identifier`, the CSP, window, and add `bundle.externalBin`. Replace the generated file's top-level fields so it reads:

```json
{
  "$schema": "https://schema.tauri.app/config/2",
  "productName": "AI Guard",
  "version": "0.1.0",
  "identifier": "th.ac.psu.aiguard",
  "build": {
    "frontendDist": "../src",
    "beforeDevCommand": "",
    "beforeBuildCommand": ""
  },
  "app": {
    "withGlobalTauri": true,
    "security": {
      "csp": "default-src 'self'; connect-src 'self' ipc: http://ipc.localhost http://127.0.0.1:8000 http://localhost:8000; img-src 'self' data: asset: http://asset.localhost; style-src 'self' 'unsafe-inline'; script-src 'self'"
    },
    "windows": [
      { "title": "AI Guard", "width": 1100, "height": 760, "resizable": true }
    ]
  },
  "bundle": {
    "active": true,
    "targets": ["nsis"],
    "externalBin": ["binaries/aiguard"],
    "icon": ["icons/32x32.png", "icons/128x128.png", "icons/icon.ico"]
  }
}
```

> Note: `withGlobalTauri: true` exposes `window.__TAURI__` so the frontend can call the `quit_app` command added in Task 4. `externalBin` uses the basename `binaries/aiguard`; Tauri resolves the `-<triple>.exe` suffix per platform at build time.

- [ ] **Step 4: Add the shell plugin dependency**

In `desktop/src-tauri/Cargo.toml`, under `[dependencies]` add:

```toml
tauri-plugin-shell = "2"
tauri-plugin-single-instance = "2"
```

- [ ] **Step 5: Grant the sidecar permission in the capability file**

Edit `desktop/src-tauri/capabilities/default.json` so `permissions` includes shell execute scoped to the sidecar (keep the existing `core:*` entries the scaffolder added):

```json
{
  "$schema": "../gen/schemas/desktop-schema.json",
  "identifier": "default",
  "description": "Capability for the main window",
  "windows": ["main"],
  "permissions": [
    "core:default",
    {
      "identifier": "shell:allow-execute",
      "allow": [{ "name": "binaries/aiguard", "sidecar": true, "args": true }]
    }
  ]
}
```

- [ ] **Step 6: Verify config compiles (no runtime spawn yet)**

```powershell
cd desktop
npm run tauri build -- --no-bundle
```

Expected: Rust compiles clean (the new deps resolve). If the capability schema errors, cross-check the sidecar scope against https://v2.tauri.app/develop/sidecar/ and fix the `allow` entry.

- [ ] **Step 7: Commit**

```powershell
git add desktop/build-sidecar.ps1 desktop/src-tauri/tauri.conf.json desktop/src-tauri/Cargo.toml desktop/src-tauri/capabilities/default.json
git commit -m "feat(desktop): bundle AIGuard.exe as tauri sidecar (externalBin + capability)"
```

---

### Task 4: Rust core — spawn sidecar, log, single-instance, kill process tree on exit

**Files:**
- Modify: `desktop/src-tauri/src/lib.rs` (Tauri v2 puts the builder here; `main.rs` calls `run()`)
- Create: `desktop/src-tauri/src/sidecar.rs`

**Interfaces:**
- Consumes: sidecar named `aiguard` (Task 3).
- Produces: on app launch the sidecar is spawned and its stdout/stderr are logged; on exit the sidecar's process tree is killed. A `quit_app` Tauri command the frontend can invoke. A pure helper `sidecar::taskkill_args(pid) -> Vec<String>` (unit-tested).

- [ ] **Step 1: Write the failing Rust unit test**

Create `desktop/src-tauri/src/sidecar.rs` with only the helper + test:

```rust
/// Build the Windows `taskkill` arguments to force-kill a process tree by PID.
/// PyInstaller onefile spawns a child; `/T` kills the whole tree, `/F` forces it.
pub fn taskkill_args(pid: u32) -> Vec<String> {
    vec![
        "/PID".to_string(),
        pid.to_string(),
        "/T".to_string(),
        "/F".to_string(),
    ]
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn taskkill_args_builds_tree_force_kill() {
        assert_eq!(
            taskkill_args(1234),
            vec!["/PID", "1234", "/T", "/F"]
        );
    }
}
```

- [ ] **Step 2: Run the test to verify it fails (module not wired)**

```powershell
cd desktop/src-tauri
cargo test taskkill_args_builds_tree_force_kill
```

Expected: FAIL to compile — `sidecar` module not declared in `lib.rs`.

- [ ] **Step 3: Declare the module so the test compiles and passes**

In `desktop/src-tauri/src/lib.rs`, add at the top (above `run()`):

```rust
mod sidecar;
```

Re-run:

```powershell
cargo test taskkill_args_builds_tree_force_kill
```

Expected: PASS.

- [ ] **Step 4: Implement spawn + kill-on-exit in `sidecar.rs`**

Append to `desktop/src-tauri/src/sidecar.rs`:

```rust
use std::sync::Mutex;
use tauri::{AppHandle, Manager, RunEvent};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

/// Holds the running sidecar child so it can be killed on exit.
#[derive(Default)]
pub struct SidecarState {
    pub child: Mutex<Option<CommandChild>>,
    pub pid: Mutex<Option<u32>>,
}

/// Spawn the `aiguard` sidecar and stream its output to the Rust log.
pub fn spawn(app: &AppHandle) -> Result<(), String> {
    let (mut rx, child) = app
        .shell()
        .sidecar("aiguard")
        .map_err(|e| format!("create sidecar: {e}"))?
        .spawn()
        .map_err(|e| format!("spawn sidecar: {e}"))?;

    let pid = child.pid();
    let state = app.state::<SidecarState>();
    *state.child.lock().unwrap() = Some(child);
    *state.pid.lock().unwrap() = Some(pid);

    tauri::async_runtime::spawn(async move {
        while let Some(event) = rx.recv().await {
            match event {
                CommandEvent::Stdout(bytes) => {
                    log::info!("[aiguard] {}", String::from_utf8_lossy(&bytes).trim_end());
                }
                CommandEvent::Stderr(bytes) => {
                    log::warn!("[aiguard] {}", String::from_utf8_lossy(&bytes).trim_end());
                }
                CommandEvent::Terminated(payload) => {
                    log::warn!("[aiguard] terminated: {:?}", payload.code);
                    break;
                }
                _ => {}
            }
        }
    });

    Ok(())
}

/// Kill the sidecar process tree. Best-effort: kill the child handle, then
/// `taskkill /T /F` on the stored PID to also reap the PyInstaller child.
pub fn kill(app: &AppHandle) {
    let state = app.state::<SidecarState>();
    if let Some(child) = state.child.lock().unwrap().take() {
        let _ = child.kill();
    }
    if let Some(pid) = state.pid.lock().unwrap().take() {
        let _ = std::process::Command::new("taskkill")
            .args(taskkill_args(pid))
            .output();
    }
}

/// Hook to call from the Tauri `run` closure on every runtime event.
pub fn on_run_event(app: &AppHandle, event: &RunEvent) {
    if let RunEvent::ExitRequested { .. } = event {
        kill(app);
    }
}
```

- [ ] **Step 5: Wire it into the builder in `lib.rs`**

Replace the body of `run()` in `desktop/src-tauri/src/lib.rs` with:

```rust
#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(w) = app.get_webview_window("main") {
                let _ = w.set_focus();
            }
        }))
        .plugin(tauri_plugin_shell::init())
        .manage(sidecar::SidecarState::default())
        .invoke_handler(tauri::generate_handler![quit_app])
        .setup(|app| {
            if let Err(e) = sidecar::spawn(&app.handle()) {
                log::error!("failed to start sidecar: {e}");
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app, event| sidecar::on_run_event(app, &event));
}

#[tauri::command]
fn quit_app(app: tauri::AppHandle) {
    sidecar::kill(&app);
    app.exit(0);
}
```

Add `use tauri::Manager;` at the top of `lib.rs` if not already present (needed for `get_webview_window`).

- [ ] **Step 6: Add the `log` dependency**

In `desktop/src-tauri/Cargo.toml` under `[dependencies]`:

```toml
log = "0.4"
```

- [ ] **Step 7: Run the full desktop app against the real sidecar**

```powershell
cd desktop
./build-sidecar.ps1          # ensure binaries/aiguard-...exe is fresh
npm run tauri dev
```

Manual acceptance:
- The window opens.
- In another terminal: `Invoke-RestMethod http://127.0.0.1:8000/api/health` returns `{status; version}` (the sidecar is running).
- Close the window; re-run the health call — it should now fail (sidecar tree was killed). Confirm no stray `AIGuard.exe` in Task Manager.

- [ ] **Step 8: Commit**

```powershell
git add desktop/src-tauri/src/sidecar.rs desktop/src-tauri/src/lib.rs desktop/src-tauri/Cargo.toml
git commit -m "feat(desktop): spawn sidecar on launch, kill process tree on exit, single-instance"
```

---

### Task 5: Frontend shell — health gating + tab navigation + API helper

**Files:**
- Create: `desktop/src/index.html`
- Create: `desktop/src/styles.css`
- Create: `desktop/src/api.js`
- Create: `desktop/src/app.js`

**Interfaces:**
- Consumes: `http://127.0.0.1:8000/api/*` (exact shapes from `app/server.py`).
- Produces: `api.js` exports `health()`, `sanitize(text, mode)`, `reidentify(sessionId, text)`, `analyze(text)`, `redactPdf(file)`. `app.js` exports nothing; it boots the app, gates on health, and switches tabs. Screen modules (Tasks 6-9) export `renderX(rootEl)` and are imported by `app.js`.

- [ ] **Step 1: Write `api.js` (the single source of endpoint calls)**

Create `desktop/src/api.js`:

```javascript
const BASE = "http://127.0.0.1:8000";

async function j(path, opts) {
  const res = await fetch(BASE + path, opts);
  if (!res.ok) throw new Error(`${path} -> HTTP ${res.status}`);
  return res.json();
}

export function health() {
  return j("/api/health");
}

export function sanitize(text, mode = "token") {
  return j("/api/sanitize", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, mode }),
  });
}

export function reidentify(sessionId, text) {
  return j("/api/reidentify", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, text }),
  });
}

export function analyze(text) {
  return j("/api/analyze", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
}

export function redactPdf(file) {
  const fd = new FormData();
  fd.append("pdf_file", file);
  return j("/api/redact-pdf", { method: "POST", body: fd });
}
```

- [ ] **Step 2: Write `index.html` (shell markup)**

Create `desktop/src/index.html`:

```html
<!DOCTYPE html>
<html lang="th">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>AI Guard</title>
  <link rel="stylesheet" href="styles.css" />
</head>
<body>
  <div id="boot" class="boot">
    <div class="spinner"></div>
    <p id="boot-msg">กำลังเริ่มบริการในเครื่อง...</p>
  </div>

  <div id="app" class="app hidden">
    <nav class="sidebar">
      <div class="brand">AI Guard</div>
      <button class="nav-item" data-tab="text">Mask / Restore</button>
      <button class="nav-item" data-tab="redact">Redact PDF</button>
      <button class="nav-item" data-tab="report">PDPA Report</button>
      <button class="nav-item" data-tab="settings">Settings</button>
      <div class="status" id="status"><span class="dot"></span> <span id="status-text">online</span></div>
    </nav>
    <main class="content" id="screen"></main>
  </div>

  <script type="module" src="app.js"></script>
</body>
</html>
```

- [ ] **Step 3: Write `styles.css` (minimal, functional)**

Create `desktop/src/styles.css`:

```css
* { box-sizing: border-box; }
body { margin: 0; font-family: "Segoe UI", Tahoma, sans-serif; color: #1f2937; background: #f3f4f6; }
.hidden { display: none !important; }

.boot { display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100vh; gap: 16px; }
.spinner { width: 36px; height: 36px; border: 4px solid #d1d5db; border-top-color: #2563eb; border-radius: 50%; animation: spin 0.9s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

.app { display: grid; grid-template-columns: 220px 1fr; height: 100vh; }
.sidebar { background: #111827; color: #e5e7eb; display: flex; flex-direction: column; padding: 16px 12px; gap: 6px; }
.brand { font-weight: 700; font-size: 18px; padding: 8px 10px 16px; }
.nav-item { text-align: left; background: transparent; color: #cbd5e1; border: 0; padding: 10px 12px; border-radius: 8px; cursor: pointer; font-size: 14px; }
.nav-item:hover { background: #1f2937; }
.nav-item.active { background: #2563eb; color: #fff; }
.status { margin-top: auto; font-size: 12px; color: #9ca3af; padding: 10px; display: flex; align-items: center; gap: 6px; }
.status .dot { width: 8px; height: 8px; border-radius: 50%; background: #22c55e; }
.status.offline .dot { background: #ef4444; }

.content { padding: 24px 28px; overflow: auto; }
h2 { margin-top: 0; }
textarea { width: 100%; min-height: 140px; padding: 10px; border: 1px solid #d1d5db; border-radius: 8px; font: inherit; resize: vertical; }
button.primary { background: #2563eb; color: #fff; border: 0; padding: 10px 16px; border-radius: 8px; cursor: pointer; font-size: 14px; }
button.primary:disabled { background: #93c5fd; cursor: default; }
.row { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; margin: 12px 0; }
.card { background: #fff; border: 1px solid #e5e7eb; border-radius: 10px; padding: 16px; margin: 12px 0; }
.mono { font-family: "Cascadia Code", Consolas, monospace; white-space: pre-wrap; word-break: break-word; }
.previews { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.previews img { width: 100%; border: 1px solid #e5e7eb; border-radius: 8px; }
.err { color: #b91c1c; }
table { border-collapse: collapse; width: 100%; }
th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid #eee; font-size: 14px; }
```

- [ ] **Step 4: Write `app.js` (boot, health gate, tab router)**

Create `desktop/src/app.js`:

```javascript
import { health } from "./api.js";
import { renderText } from "./screen-text.js";
import { renderRedact } from "./screen-redact.js";
import { renderReport } from "./screen-report.js";
import { renderSettings } from "./screen-settings.js";

const SCREENS = {
  text: renderText,
  redact: renderRedact,
  report: renderReport,
  settings: renderSettings,
};

async function waitForBackend() {
  const msg = document.getElementById("boot-msg");
  for (let attempt = 1; attempt <= 40; attempt++) {
    try {
      await health();
      return true;
    } catch {
      msg.textContent = `กำลังเริ่มบริการในเครื่อง... (${attempt})`;
      await new Promise((r) => setTimeout(r, 500));
    }
  }
  msg.textContent = "เริ่มบริการไม่สำเร็จ ปิดแล้วเปิดแอปใหม่";
  return false;
}

function selectTab(name) {
  document.querySelectorAll(".nav-item").forEach((b) => {
    b.classList.toggle("active", b.dataset.tab === name);
  });
  const root = document.getElementById("screen");
  root.innerHTML = "";
  SCREENS[name](root);
}

async function main() {
  const ok = await waitForBackend();
  if (!ok) return;
  document.getElementById("boot").classList.add("hidden");
  document.getElementById("app").classList.remove("hidden");
  document.querySelectorAll(".nav-item").forEach((b) => {
    b.addEventListener("click", () => selectTab(b.dataset.tab));
  });
  selectTab("text");
}

main();
```

> Screen modules are created in Tasks 6-9. Until then `app.js` will fail to import them; that is expected — those tasks complete the imports.

- [ ] **Step 5: Commit**

```powershell
git add desktop/src/index.html desktop/src/styles.css desktop/src/api.js desktop/src/app.js
git commit -m "feat(desktop): frontend shell — health gate, tab router, api helper"
```

---

### Task 6: Text panel screen (mask / restore)

**Files:**
- Create: `desktop/src/screen-text.js`

**Interfaces:**
- Consumes: `sanitize(text, mode)`, `reidentify(sessionId, text)` from `api.js`. Response fields used: `sanitized_text`, `session_id`, `entities[]`, `restored_text`, `replaced_count`, `leftover_tokens`.
- Produces: `renderText(rootEl)`.

- [ ] **Step 1: Implement the screen**

Create `desktop/src/screen-text.js`:

```javascript
import { sanitize, reidentify } from "./api.js";

export function renderText(root) {
  const mode = localStorage.getItem("aiguard.mode") || "token";
  root.innerHTML = `
    <h2>Mask / Restore</h2>
    <p>วางข้อความที่มีข้อมูลส่วนบุคคล กด Mask เพื่อแทนด้วยโทเคน แล้วคัดลอกไปใช้กับ AI ภายนอก</p>
    <textarea id="t-input" placeholder="พิมพ์หรือวางข้อความที่นี่..."></textarea>
    <div class="row">
      <button class="primary" id="t-mask">Mask PII</button>
      <span>โหมด: <b id="t-mode">${mode}</b> (เปลี่ยนได้ที่ Settings)</span>
    </div>
    <div class="card hidden" id="t-out">
      <div class="row"><b>ผลลัพธ์ที่ปกปิดแล้ว</b> <button class="primary" id="t-copy">Copy</button></div>
      <div class="mono" id="t-masked"></div>
      <p id="t-count"></p>
      <hr />
      <p>วางคำตอบจาก AI (ที่ยังมีโทเคน) เพื่อคืนค่าจริง:</p>
      <textarea id="t-reply" placeholder="วางคำตอบจาก AI ที่นี่..."></textarea>
      <div class="row"><button class="primary" id="t-restore">Restore PII</button></div>
      <div class="mono hidden" id="t-restored"></div>
      <p class="err hidden" id="t-leftover"></p>
    </div>
    <p class="err hidden" id="t-err"></p>
  `;

  let sessionId = null;
  const $ = (id) => root.querySelector(id);

  $("#t-mask").addEventListener("click", async () => {
    const text = $("#t-input").value.trim();
    if (!text) return;
    $("#t-err").classList.add("hidden");
    try {
      const res = await sanitize(text, mode);
      sessionId = res.session_id;
      $("#t-masked").textContent = res.sanitized_text;
      $("#t-count").textContent = `ปกปิด ${res.entities.length} รายการ`;
      $("#t-out").classList.remove("hidden");
    } catch (e) {
      $("#t-err").textContent = "ปกปิดไม่สำเร็จ: " + e.message;
      $("#t-err").classList.remove("hidden");
    }
  });

  $("#t-copy").addEventListener("click", () => {
    navigator.clipboard.writeText($("#t-masked").textContent);
  });

  $("#t-restore").addEventListener("click", async () => {
    if (!sessionId) return;
    const reply = $("#t-reply").value;
    try {
      const res = await reidentify(sessionId, reply);
      $("#t-restored").textContent = res.restored_text;
      $("#t-restored").classList.remove("hidden");
      if (res.leftover_tokens && res.leftover_tokens.length) {
        $("#t-leftover").textContent =
          "โทเคนที่ยังคืนค่าไม่ได้: " + res.leftover_tokens.join(", ");
        $("#t-leftover").classList.remove("hidden");
      } else {
        $("#t-leftover").classList.add("hidden");
      }
    } catch (e) {
      $("#t-err").textContent = "คืนค่าไม่สำเร็จ: " + e.message;
      $("#t-err").classList.remove("hidden");
    }
  });
}
```

- [ ] **Step 2: Manual verification**

`npm run tauri dev` (sidecar staged). On the Mask/Restore tab: paste `สมชาย ใจดี โทร 0812345678 อีเมล test@example.com`, click **Mask PII** → tokens appear and count is > 0. Paste the masked text into the reply box, click **Restore PII** → original values return.

- [ ] **Step 3: Commit**

```powershell
git add desktop/src/screen-text.js
git commit -m "feat(desktop): text mask/restore screen"
```

---

### Task 7: Redact PDF screen

**Files:**
- Create: `desktop/src/screen-redact.js`

**Interfaces:**
- Consumes: `redactPdf(file)`. Response fields used: `entity_count`, `source_type`, `human_review`, `before_png_b64`, `after_png_b64`, `redacted_pdf_b64`, `filename`.
- Produces: `renderRedact(rootEl)`.

- [ ] **Step 1: Implement the screen**

Create `desktop/src/screen-redact.js`:

```javascript
import { redactPdf } from "./api.js";

function b64ToBlob(b64, type) {
  const bytes = atob(b64);
  const arr = new Uint8Array(bytes.length);
  for (let i = 0; i < bytes.length; i++) arr[i] = bytes.charCodeAt(i);
  return new Blob([arr], { type });
}

export function renderRedact(root) {
  root.innerHTML = `
    <h2>Redact PDF</h2>
    <p>อัปโหลด PDF เพื่อดำกล่องทับข้อมูลส่วนบุคคล (ประมวลผลในเครื่องทั้งหมด)</p>
    <div class="row">
      <input type="file" id="r-file" accept="application/pdf" />
      <button class="primary" id="r-go" disabled>Redact</button>
    </div>
    <p id="r-status"></p>
    <div class="card hidden" id="r-out">
      <p id="r-summary"></p>
      <div class="previews">
        <div><b>ก่อน</b><img id="r-before" alt="before" /></div>
        <div><b>หลัง</b><img id="r-after" alt="after" /></div>
      </div>
      <div class="row"><button class="primary" id="r-download">Download Redacted PDF</button></div>
    </div>
    <p class="err hidden" id="r-err"></p>
  `;

  const $ = (id) => root.querySelector(id);
  let redactedB64 = null;
  let outName = "redacted.pdf";

  $("#r-file").addEventListener("change", () => {
    $("#r-go").disabled = !$("#r-file").files.length;
  });

  $("#r-go").addEventListener("click", async () => {
    const file = $("#r-file").files[0];
    if (!file) return;
    $("#r-err").classList.add("hidden");
    $("#r-status").textContent = "กำลังประมวลผล...";
    try {
      const res = await redactPdf(file);
      redactedB64 = res.redacted_pdf_b64;
      outName = "redacted-" + (res.filename || file.name);
      $("#r-summary").textContent =
        `ชนิดไฟล์: ${res.source_type} · พบ PII ${res.entity_count} รายการ` +
        (res.human_review ? " · ต้องตรวจซ้ำ (OCR ความมั่นใจต่ำ)" : "");
      $("#r-before").src = "data:image/png;base64," + res.before_png_b64;
      $("#r-after").src = "data:image/png;base64," + res.after_png_b64;
      $("#r-out").classList.remove("hidden");
      $("#r-status").textContent = "";
    } catch (e) {
      $("#r-status").textContent = "";
      $("#r-err").textContent = "ปกปิด PDF ไม่สำเร็จ: " + e.message;
      $("#r-err").classList.remove("hidden");
    }
  });

  $("#r-download").addEventListener("click", () => {
    if (!redactedB64) return;
    const url = URL.createObjectURL(b64ToBlob(redactedB64, "application/pdf"));
    const a = document.createElement("a");
    a.href = url;
    a.download = outName;
    a.click();
    URL.revokeObjectURL(url);
  });
}
```

- [ ] **Step 2: Manual verification**

On the Redact PDF tab, choose a text-layer PDF containing a Thai national ID / phone / email, click **Redact** → before/after previews show black boxes over PII; **Download** saves the redacted PDF. (A scanned-only PDF returns HTTP 503 unless `requirements-ocr.txt` is installed in the sidecar build — expected; the error surfaces in the red error line.)

- [ ] **Step 3: Commit**

```powershell
git add desktop/src/screen-redact.js
git commit -m "feat(desktop): redact PDF screen with before/after preview and download"
```

---

### Task 8: PDPA report screen

**Files:**
- Create: `desktop/src/screen-report.js`

**Interfaces:**
- Consumes: `analyze(text)`. Response fields used: `overall_score`, `overall_grade`, `risk_label`, `direct_pii_count`, `reid{score,grade,qi_found,high_risk_combo}`, `section26[]`, `breakdown[]`, `recommendations[]`.
- Produces: `renderReport(rootEl)`.

- [ ] **Step 1: Implement the screen**

Create `desktop/src/screen-report.js`:

```javascript
import { analyze } from "./api.js";

export function renderReport(root) {
  root.innerHTML = `
    <h2>PDPA Risk Report</h2>
    <p>วิเคราะห์ความเสี่ยง PDPA ของข้อความ (คะแนน, re-identification, ข้อมูลอ่อนไหว ม.26)</p>
    <textarea id="a-input" placeholder="วางข้อความเพื่อวิเคราะห์..."></textarea>
    <div class="row"><button class="primary" id="a-go">Analyze</button></div>
    <div id="a-out"></div>
    <p class="err hidden" id="a-err"></p>
  `;

  const $ = (id) => root.querySelector(id);

  $("#a-go").addEventListener("click", async () => {
    const text = $("#a-input").value.trim();
    if (!text) return;
    $("#a-err").classList.add("hidden");
    try {
      const r = await analyze(text);
      $("#a-out").innerHTML = `
        <div class="card">
          <b>คะแนนรวม:</b> ${r.overall_score.toFixed(1)} (เกรด ${r.overall_grade}) — ${r.risk_label}<br/>
          <b>PII โดยตรง:</b> ${r.direct_pii_count} · <b>re-id:</b> ${r.reid.score.toFixed(1)} (เกรด ${r.reid.grade})${r.reid.high_risk_combo ? " · เสี่ยงสูงจากการรวมข้อมูล" : ""}
        </div>
        ${r.section26.length ? `<div class="card"><b>ข้อมูลอ่อนไหว ม.26 (${r.section26.length})</b><ul>${r.section26.map((s) => `<li>${s.category}: ${escapeHtml(s.text)}${s.source === "semantic" ? " (AI)" : ""}</li>`).join("")}</ul></div>` : ""}
        ${r.breakdown.length ? `<div class="card"><b>ประเภท PII ที่พบ</b><table><tr><th>ชนิด</th><th>กลุ่ม</th><th>จำนวน</th></tr>${r.breakdown.map((b) => `<tr><td>${b.data_type}</td><td>${b.redact_type}</td><td>${b.count}</td></tr>`).join("")}</table></div>` : ""}
        ${r.recommendations.length ? `<div class="card"><b>คำแนะนำ</b><ul>${r.recommendations.map((c) => `<li><b>[${c.level}]</b> ${escapeHtml(c.title)} — ${escapeHtml(c.desc)}</li>`).join("")}</ul></div>` : ""}
      `;
    } catch (e) {
      $("#a-err").textContent = "วิเคราะห์ไม่สำเร็จ: " + e.message;
      $("#a-err").classList.remove("hidden");
    }
  });

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
    );
  }
}
```

- [ ] **Step 2: Manual verification**

On the PDPA Report tab, paste a paragraph with a national ID + an address + a health mention, click **Analyze** → overall grade, re-id score, Section-26 list, breakdown table, and recommendations render.

- [ ] **Step 3: Commit**

```powershell
git add desktop/src/screen-report.js
git commit -m "feat(desktop): PDPA risk report screen"
```

---

### Task 9: Settings screen

**Files:**
- Create: `desktop/src/screen-settings.js`

**Interfaces:**
- Consumes: `window.__TAURI__.core.invoke` (the `quit_app` command from Task 4); `localStorage` key `aiguard.mode`.
- Produces: `renderSettings(rootEl)`.

- [ ] **Step 1: Implement the screen**

Create `desktop/src/screen-settings.js`:

```javascript
export function renderSettings(root) {
  const mode = localStorage.getItem("aiguard.mode") || "token";
  root.innerHTML = `
    <h2>Settings</h2>
    <div class="card">
      <b>โหมดการปกปิด</b>
      <div class="row">
        <label><input type="radio" name="mode" value="token" ${mode === "token" ? "checked" : ""}/> Token — <span class="mono">[ชื่อ_1]</span> (เห็นชัดว่าปกปิดแล้ว)</label>
      </div>
      <div class="row">
        <label><input type="radio" name="mode" value="surrogate" ${mode === "surrogate" ? "checked" : ""}/> Surrogate — ข้อมูลปลอมสมจริง (AI อ่านลื่น)</label>
      </div>
    </div>
    <div class="card">
      <b>ส่วนขยายเบราว์เซอร์</b>
      <p>สำหรับปกปิดในหน้าแชต ChatGPT / Claude โดยตรง — ติดตั้งจาก Chrome Web Store (เร็ว ๆ นี้) หรือโหลดโฟลเดอร์ <span class="mono">extension/</span> แบบ unpacked</p>
    </div>
    <div class="card">
      <b>บริการในเครื่อง</b>
      <p>API: <span class="mono">http://127.0.0.1:8000</span> · เอกสาร: <span class="mono">/docs</span></p>
      <div class="row"><button class="primary" id="s-quit">ออกจากโปรแกรม (ปิด backend)</button></div>
    </div>
  `;

  root.querySelectorAll('input[name="mode"]').forEach((el) => {
    el.addEventListener("change", () => {
      localStorage.setItem("aiguard.mode", el.value);
    });
  });

  root.querySelector("#s-quit").addEventListener("click", () => {
    window.__TAURI__.core.invoke("quit_app");
  });
}
```

- [ ] **Step 2: Manual verification**

On Settings: toggle to **Surrogate**, go to Mask/Restore, Mask → output is realistic fake data (not `[ชื่อ_1]`). Back to Settings → **ออกจากโปรแกรม** closes the window and stops the sidecar (health call fails afterward).

- [ ] **Step 3: Commit**

```powershell
git add desktop/src/screen-settings.js
git commit -m "feat(desktop): settings screen — mode toggle, quit command"
```

---

### Task 10: Production build + acceptance on a clean run

**Files:**
- Modify: `desktop/README.md` (create)

**Interfaces:**
- Consumes: everything above.
- Produces: an NSIS installer under `desktop/src-tauri/target/release/bundle/nsis/`.

- [ ] **Step 1: Build the installer**

```powershell
cd desktop
./build-sidecar.ps1
npm run tauri build
```

Expected: build completes; an installer appears at `desktop/src-tauri/target/release/bundle/nsis/AI Guard_0.1.0_x64-setup.exe`.

- [ ] **Step 2: Acceptance test on install**

Install via the produced setup.exe, launch **AI Guard** from the Start menu (do NOT run the dev server). Verify, ideally with the network disconnected (proves on-device):
- Boot spinner → main window (sidecar started).
- Mask/Restore round-trips.
- Redact a text-layer PDF → before/after + download.
- PDPA report renders.
- Quit → no `AIGuard.exe` left in Task Manager.
- Relaunch a second time while running → single-instance focuses the existing window (no second backend).

- [ ] **Step 3: Write `desktop/README.md`**

Create `desktop/README.md`:

```markdown
# AI Guard Desktop (Tauri v2)

Windows desktop shell that runs the AI Guard Python engine as a bundled
sidecar (`AIGuard.exe`) and drives it through a native window. Everything runs
on `127.0.0.1` — no data leaves the machine.

## Prerequisites
- Rust (MSVC host: `x86_64-pc-windows-msvc`)
- Node.js LTS (for the Tauri CLI only)
- WebView2 (preinstalled on Win10 1803+/Win11)

## Develop
```powershell
./build-sidecar.ps1     # builds dist/AIGuard.exe and stages it as the sidecar
npm install
npm run tauri dev
```

## Build installer
```powershell
./build-sidecar.ps1
npm run tauri build     # -> src-tauri/target/release/bundle/nsis/*-setup.exe
```
```

- [ ] **Step 4: Commit**

```powershell
git add desktop/README.md
git commit -m "docs(desktop): phase-1 build/run instructions"
```

---

## Self-Review

**Spec coverage** (against `2026-07-04-desktop-oss-release-design.md`, phase 1 = "Core shell: Tauri + sidecar + dashboard"):
- Tauri shell + sidecar lifecycle → Tasks 1, 3, 4.
- Dashboard: Redact PDF → Task 7; PDPA report → Task 8; Text panel → Task 6; Settings → Task 9; status/health gate → Task 5.
- Kill-on-exit / single-instance (spec "Rust core") → Task 4. Port-fallback, tray, global hotkey, audit viewer, auto-update are later phases (spec phases 2+) — intentionally excluded.
- `/api/audit-log` and pypdfium2 migration are later phases — excluded here (Global Constraints call this out).

**Placeholder scan:** No TBD/TODO. Every code step contains complete code. The one config with residual uncertainty (the sidecar capability scope in Task 3) has an explicit doc reference and a compile/verify step.

**Type/name consistency:** `api.js` exports (`health`, `sanitize`, `reidentify`, `analyze`, `redactPdf`) are consumed with those exact names in Tasks 6-8. Screen modules export `renderText/renderRedact/renderReport/renderSettings`, matching the imports in `app.js` (Task 5). Rust `sidecar::spawn/kill/on_run_event/SidecarState/taskkill_args` are used consistently between `sidecar.rs` and `lib.rs`. Response field names (`sanitized_text`, `session_id`, `restored_text`, `leftover_tokens`, `redacted_pdf_b64`, `before_png_b64`, `after_png_b64`, `overall_grade`, `reid.score`, `section26[].source`) match `app/server.py`.

**Known risk carried from research:** the failed `tauri-testing` research agent covered single-instance + cargo-test structure; both were filled from standard Tauri v2 APIs (`tauri-plugin-single-instance::init`, `#[cfg(test)]`). If `tauri-plugin-single-instance` init signature differs on the installed version, adjust the closure arity per its docs.
