# Phase 2: Tray + Global Hotkey + Audit Viewer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax. Heavy builds (`cargo`/`tauri`) and GUI checks are the human/executor's machine; automated checks (pytest, `cargo test`, `cargo build`) run headless.

**Goal:** Add three things to the phase-1 desktop app: (1) a backend audit trail — `POST` endpoints emit PII-free `write_process_log` records and a new `GET /api/audit-log` returns them; (2) a Tauri system tray with Show/Hide/Quit (Quit stops the sidecar cleanly); (3) a global hotkey that masks/restores whatever is on the clipboard against the local backend — the desktop analog of the mobile share-sheet, working in any app. Plus an in-app Audit viewer screen.

**Architecture:** Backend gains `_get_audit_log_dir()` + `write_process_log` calls in the 4 endpoints + `GET /api/audit-log` (reuses `pii_redactor/audit.py` unchanged). Rust gains two plugins (`tauri-plugin-global-shortcut`, `tauri-plugin-clipboard-manager`), the `tray-icon` tauri feature, a `tray.rs`, and a `hotkey.rs`; hotkey handlers spawn async tasks that call the backend via `reqwest` and read/write the clipboard, storing the last mask `session_id` in shared state so the restore hotkey can reverse it. Frontend gains an Audit viewer tab.

**Tech Stack:** Existing (Tauri v2, FastAPI, `pii_redactor/audit.py`) + `tauri-plugin-global-shortcut` 2.x, `tauri-plugin-clipboard-manager` 2.x, `reqwest` 0.12, tauri `tray-icon` feature.

## Global Constraints

- On-device only: hotkey handlers call only `http://127.0.0.1:8000`. The vault stays in the backend.
- Audit logs are PII-free by construction (`audit.py` only writes counts/steps/timestamps/flags with entity_ids). The `GET /api/audit-log` response must filter to those safe fields only — never echo request text.
- Reuse `pii_redactor/audit.py` unchanged. Existing endpoints keep their current response shapes; only add audit-write side effects + the new route.
- Verified `audit.py` signature: `write_process_log(session_id: str, step: str, entity_count: int, validation_result: str, flags: list[str], latency_ms: float, output_dir: str = ".") -> Path`. Record fields: `type,session_id,step,timestamp (float epoch),entity_count,validation_result,flags,latency_ms`. File name: `audit_{session_id}_{process|security}.jsonl`.
- Tray "Quit" and window-close must both stop the sidecar via `sidecar::kill` (from phase 1) — never `std::process::exit(0)`, which orphans the 150MB backend and leaves the in-memory vault process alive.
- Windows-first. Work on a branch off main; finish with a PR.

---

### Task 1: Audit log directory helper + wire audit-write into the 4 endpoints

**Files:**
- Modify: `app/server.py`
- Test: `tests/test_step11_api.py`

**Interfaces:**
- Produces: `_get_audit_log_dir() -> str` (frozen exe → `%APPDATA%/AI Guard/logs`, source → `./logs`); each of `/api/sanitize`, `/api/reidentify`, `/api/analyze`, `/api/redact-pdf` writes exactly one `write_process_log` record.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_step11_api.py`:

```python
def test_sanitize_writes_one_audit_record(tmp_path, monkeypatch):
    import app.server as server
    monkeypatch.setattr(server, "_get_audit_log_dir", lambda: str(tmp_path))

    from fastapi.testclient import TestClient
    client = TestClient(server.app)
    resp = client.post("/api/sanitize", json={"text": "ผมชื่อสมชาย ใจดี เบอร์ 0812345678", "mode": "token"})
    assert resp.status_code == 200

    logs = list(tmp_path.glob("audit_*_process.jsonl"))
    assert len(logs) == 1
    import json
    rec = json.loads(logs[0].read_text(encoding="utf-8").splitlines()[0])
    assert rec["type"] == "process"
    assert rec["step"] == "api_sanitize"
    assert rec["entity_count"] >= 1
    # PII-free: the record must not contain the original phone number
    assert "0812345678" not in logs[0].read_text(encoding="utf-8")
```

- [ ] **Step 2: Run it — expect FAIL** (`_get_audit_log_dir` missing, no log written)

```powershell
$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe -m pytest tests/test_step11_api.py::test_sanitize_writes_one_audit_record -v
```

- [ ] **Step 3: Add the helper + the sanitize audit-write**

In `app/server.py`, add imports near the top: `import sys` (if missing), `import time` (present), `from pii_redactor.audit import write_process_log`. Add the helper after `_schedule_exit`:

```python
def _get_audit_log_dir() -> str:
    """Audit log directory. Frozen exe -> %APPDATA%/AI Guard/logs; source -> ./logs."""
    if getattr(sys, "frozen", False):
        log_dir = Path.home() / "AppData" / "Roaming" / "AI Guard" / "logs"
    else:
        log_dir = Path.cwd() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return str(log_dir)
```

In the `sanitize` handler, wrap the core work with a timer and write the log before returning:

```python
    start = time.time()
    # ... existing tokenize + _store_session ...
    write_process_log(
        session_id=sid,
        step="api_sanitize",
        entity_count=len(result["entities"]),
        validation_result="pass",
        flags=[],
        latency_ms=(time.time() - start) * 1000,
        output_dir=_get_audit_log_dir(),
    )
    return { ... }  # unchanged
```

- [ ] **Step 4: Run the test — expect PASS**

```powershell
$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe -m pytest tests/test_step11_api.py::test_sanitize_writes_one_audit_record -v
```

- [ ] **Step 5: Repeat the audit-write for the other three endpoints**

Add the same pattern (timer + `write_process_log`) to `reidentify` (`step="api_reidentify"`, `entity_count=len(replaced)`, `validation_result="warn" if leftover else "pass"`, `flags=[f"leftover:{t}" for t in leftover]`), `analyze` (`step="api_analyze"`, `entity_count=report...direct_pii_count`, new `session_id=str(uuid.uuid4())`), and `redact_pdf` (`step="api_redact_pdf"`, `entity_count=len(entities)`, `flags=[f"source_type:{source_type}"]`, new `session_id=str(uuid.uuid4())`). `uuid` is already imported.

- [ ] **Step 6: Full suite green**

```powershell
$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe -m pytest -q
```
Expected: all pass (count = prior + 1).

- [ ] **Step 7: Commit**

```powershell
git add app/server.py tests/test_step11_api.py
git commit -m "feat(api): write PII-free audit records from the four processing endpoints"
```

---

### Task 2: `GET /api/audit-log` route

**Files:**
- Modify: `app/server.py`
- Test: `tests/test_step11_api.py`

**Interfaces:**
- Consumes: the JSONL logs written in Task 1; `_get_audit_log_dir()`.
- Produces: `GET /api/audit-log?limit&offset` → `{status, total_count, limit, offset, logs[]}` newest-first, safe fields only.

- [ ] **Step 1: Write the failing test**

```python
def test_audit_log_endpoint_returns_safe_records(tmp_path, monkeypatch):
    import app.server as server
    monkeypatch.setattr(server, "_get_audit_log_dir", lambda: str(tmp_path))
    from fastapi.testclient import TestClient
    client = TestClient(server.app)
    client.post("/api/sanitize", json={"text": "ผมชื่อสมชาย เบอร์ 0812345678", "mode": "token"})

    resp = client.get("/api/audit-log?limit=10&offset=0")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_count"] >= 1
    rec = data["logs"][0]
    assert rec["type"] == "process"
    assert "step" in rec and "entity_count" in rec and "timestamp" in rec
    assert "0812345678" not in resp.text  # no PII in the audit response
```

- [ ] **Step 2: Run it — expect FAIL** (404, route missing)

- [ ] **Step 3: Implement the route**

Add near the other routes in `app/server.py` (add `import glob` and `from fastapi import Query`):

```python
@app.get("/api/audit-log")
def get_audit_log(limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0)):
    log_dir = _get_audit_log_dir()
    records = []
    for path in glob.glob(f"{log_dir}/audit_*.jsonl"):
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        r = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    safe = {"type": r.get("type"), "session_id": r.get("session_id"), "timestamp": r.get("timestamp")}
                    if r.get("type") == "process":
                        safe.update(step=r.get("step"), entity_count=r.get("entity_count"),
                                    validation_result=r.get("validation_result"),
                                    latency_ms=r.get("latency_ms"), flags=r.get("flags", []))
                    elif r.get("type") == "security":
                        safe.update(layer=r.get("layer"), pii_scan_result=r.get("pii_scan_result"),
                                    retry_count=r.get("retry_count"), error_type=r.get("error_type"),
                                    rollback_occurred=r.get("rollback_occurred"))
                    records.append(safe)
        except OSError:
            continue
    records.sort(key=lambda r: r.get("timestamp") or 0, reverse=True)
    total = len(records)
    return {"status": "ok", "total_count": total, "limit": limit, "offset": offset,
            "logs": records[offset:offset + limit]}
```

- [ ] **Step 4: Run the test — expect PASS**; then full suite green; then commit.

```powershell
$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe -m pytest tests/test_step11_api.py -q
git add app/server.py tests/test_step11_api.py
git commit -m "feat(api): add GET /api/audit-log (paginated, PII-free)"
```

---

### Task 3: Rust deps + tray (Show/Hide/Quit routing through sidecar::kill)

**Files:**
- Modify: `desktop/src-tauri/Cargo.toml`
- Create: `desktop/src-tauri/src/tray.rs`
- Modify: `desktop/src-tauri/src/lib.rs`
- Modify: `desktop/src-tauri/capabilities/default.json`

**Interfaces:**
- Consumes: `sidecar::kill` (phase 1).
- Produces: `tray::setup(app: &tauri::App) -> tauri::Result<()>`; a tray icon with Show/Hide/Quit.

- [ ] **Step 1: Cargo.toml — enable the tray feature + add deps**

In `[dependencies]`, change the `tauri` line to enable the tray feature and add the two plugins + reqwest:

```toml
tauri = { version = "2", features = ["tray-icon"] }
tauri-plugin-global-shortcut = "2"
tauri-plugin-clipboard-manager = "2"
reqwest = { version = "0.12", features = ["json"] }
```
Keep the existing `tauri-plugin-shell`, `tauri-plugin-single-instance`, `serde`, `serde_json`, `log`.

> Correction vs research: the HTTP client is the Rust crate `reqwest` (NOT `httpx`, which is Python). Do not add `"shell-open"`/`"single-instance"` to tauri's feature list — those are provided by the plugins already present, not tauri core features.

- [ ] **Step 2: Create `tray.rs`**

```rust
use tauri::menu::{Menu, MenuItem};
use tauri::tray::TrayIconBuilder;
use tauri::Manager;

/// Build the system tray. Quit routes through sidecar::kill so the backend
/// process tree is reaped (never std::process::exit, which orphans it).
pub fn setup(app: &tauri::App) -> tauri::Result<()> {
    let show = MenuItem::with_id(app, "show", "Show", true, None::<&str>)?;
    let hide = MenuItem::with_id(app, "hide", "Hide", true, None::<&str>)?;
    let quit = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&show, &hide, &quit])?;

    TrayIconBuilder::new()
        .icon(app.default_window_icon().unwrap().clone())
        .tooltip("AI Guard")
        .menu(&menu)
        .on_menu_event(|app, event| match event.id.as_ref() {
            "show" => {
                if let Some(w) = app.get_webview_window("main") {
                    let _ = w.show();
                    let _ = w.set_focus();
                }
            }
            "hide" => {
                if let Some(w) = app.get_webview_window("main") {
                    let _ = w.hide();
                }
            }
            "quit" => {
                crate::sidecar::kill(app);
                app.exit(0);
            }
            _ => {}
        })
        .build(app)?;
    Ok(())
}
```

- [ ] **Step 3: Register in `lib.rs`**

Add `mod tray;` near `mod sidecar;`. In `run()`'s `.setup(|app| { ... })`, after the sidecar spawn, add:

```rust
            tray::setup(app)?;
```
(The setup closure's `app` is `&mut App`; `tray::setup` takes `&App` — pass `app` directly, it coerces.)

- [ ] **Step 4: Capability — add tray permission**

In `desktop/src-tauri/capabilities/default.json` `permissions`, add `"tray:default"` (alongside the existing `core:default` + the shell sidecar scope from phase 1).

- [ ] **Step 5: Compile check (headless OK)**

```powershell
cd desktop; cargo build --manifest-path src-tauri/Cargo.toml
```
(Needs the placeholder `src-tauri/binaries/aiguard-x86_64-pc-windows-msvc.exe` to exist for tauri-build; create an empty one if absent, as in phase 1's verification.) Expected: compiles. Then commit `Cargo.toml`, `src/tray.rs`, `src/lib.rs`, `capabilities/default.json` with message `feat(desktop): system tray (Show/Hide/Quit via sidecar::kill)`.

---

### Task 4: Global hotkey mask/restore against the clipboard

**Files:**
- Create: `desktop/src-tauri/src/hotkey.rs`
- Modify: `desktop/src-tauri/src/lib.rs`
- Modify: `desktop/src-tauri/capabilities/default.json`

**Interfaces:**
- Consumes: the backend `/api/sanitize` + `/api/reidentify`.
- Produces: `hotkey::setup(app: &tauri::App) -> tauri::Result<()>`; a `HotkeyState { last_session: Mutex<Option<String>> }` managed on the app; Ctrl+Shift+M masks the clipboard, Ctrl+Shift+R restores it.

**Flow (there is no cross-platform "get selected text" API):** user selects text and presses Ctrl+C, then Ctrl+Shift+M → read clipboard → `POST /api/sanitize` (mode `token`) → store `session_id` → write masked text back to clipboard (paste into any AI app). Ctrl+Shift+R → read clipboard → `POST /api/reidentify` with the stored `session_id` → write restored text back.

- [ ] **Step 1: Create `hotkey.rs`**

```rust
use std::sync::Mutex;
use tauri::{AppHandle, Manager};
use tauri_plugin_clipboard_manager::ClipboardExt;
use tauri_plugin_global_shortcut::{Code, GlobalShortcutExt, Modifiers, Shortcut, ShortcutState};

#[derive(Default)]
pub struct HotkeyState {
    pub last_session: Mutex<Option<String>>,
}

const BASE: &str = "http://127.0.0.1:8000";

async fn mask(app: AppHandle) {
    let text = match app.clipboard().read_text() {
        Ok(t) if !t.trim().is_empty() => t,
        _ => return,
    };
    let client = reqwest::Client::new();
    let resp = client
        .post(format!("{BASE}/api/sanitize"))
        .json(&serde_json::json!({ "text": text, "mode": "token" }))
        .send()
        .await;
    if let Ok(r) = resp {
        if let Ok(v) = r.json::<serde_json::Value>().await {
            if let (Some(sid), Some(masked)) =
                (v["session_id"].as_str(), v["sanitized_text"].as_str())
            {
                *app.state::<HotkeyState>().last_session.lock().unwrap() = Some(sid.to_string());
                let _ = app.clipboard().write_text(masked.to_string());
            }
        }
    }
}

async fn restore(app: AppHandle) {
    let sid = app.state::<HotkeyState>().last_session.lock().unwrap().clone();
    let sid = match sid { Some(s) => s, None => return };
    let text = match app.clipboard().read_text() { Ok(t) => t, _ => return };
    let client = reqwest::Client::new();
    let resp = client
        .post(format!("{BASE}/api/reidentify"))
        .json(&serde_json::json!({ "session_id": sid, "text": text }))
        .send()
        .await;
    if let Ok(r) = resp {
        if let Ok(v) = r.json::<serde_json::Value>().await {
            if let Some(restored) = v["restored_text"].as_str() {
                let _ = app.clipboard().write_text(restored.to_string());
            }
        }
    }
}

pub fn setup(app: &tauri::App) -> tauri::Result<()> {
    app.manage(HotkeyState::default());
    let mask_sc = Shortcut::new(Some(Modifiers::CONTROL | Modifiers::SHIFT), Code::KeyM);
    let restore_sc = Shortcut::new(Some(Modifiers::CONTROL | Modifiers::SHIFT), Code::KeyR);
    let mask_id = mask_sc.clone();
    app.global_shortcut().on_shortcut(mask_sc, move |app, sc, event| {
        if event.state() == ShortcutState::Pressed {
            let app = app.clone();
            let is_mask = sc == &mask_id;
            tauri::async_runtime::spawn(async move {
                if is_mask { mask(app).await } else { restore(app).await }
            });
        }
    })?;
    app.global_shortcut().on_shortcut(restore_sc, move |app, _sc, event| {
        if event.state() == ShortcutState::Pressed {
            let app = app.clone();
            tauri::async_runtime::spawn(async move { restore(app).await });
        }
    })?;
    Ok(())
}
```

> API-verify at build time: the exact `global_shortcut().on_shortcut(shortcut, handler)` signature (vs `.register(shortcut, handler)`) varies across `tauri-plugin-global-shortcut` 2.x minors. If it doesn't compile, check the installed version's docs.rs and use its registration method (the handler body — read clipboard → POST → write clipboard — stays the same). The plugin must also be initialized in `lib.rs` (next step).

- [ ] **Step 2: Register plugins + hotkey in `lib.rs`**

Add `mod hotkey;`. In the builder, add the two plugins BEFORE `.setup(...)`:

```rust
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .plugin(tauri_plugin_clipboard_manager::init())
```
And in `.setup(|app| { ... })` after `tray::setup(app)?;` add `hotkey::setup(app)?;`.

- [ ] **Step 3: Capability — add global-shortcut + clipboard permissions**

In `capabilities/default.json` `permissions`, add:

```json
    "global-shortcut:allow-register",
    "global-shortcut:allow-unregister",
    "clipboard-manager:allow-read-text",
    "clipboard-manager:allow-write-text"
```

- [ ] **Step 4: Compile check + commit**

```powershell
cd desktop; cargo build --manifest-path src-tauri/Cargo.toml
```
Expected: compiles. Commit `src/hotkey.rs`, `src/lib.rs`, `capabilities/default.json`, `Cargo.toml` with `feat(desktop): global hotkey mask/restore via clipboard (Ctrl+Shift+M / Ctrl+Shift+R)`.

- [ ] **Step 5: GUI acceptance (executor's machine)**

`./build-sidecar.ps1; npm run tauri dev`. In Notepad: type `ผมชื่อสมชาย เบอร์ 0812345678`, select all, Ctrl+C, then Ctrl+Shift+M → paste → tokens. Then Ctrl+Shift+R after copying the masked text → paste → originals. Tray: right-click → Show/Hide/Quit; Quit leaves no `AIGuard.exe` in Task Manager.

---

### Task 5: Audit viewer screen (frontend)

**Files:**
- Create: `desktop/src/screen-audit.js`
- Modify: `desktop/src/api.js` (add `auditLog`)
- Modify: `desktop/src/index.html` (add nav item), `desktop/src/app.js` (register screen)

**Interfaces:**
- Consumes: `GET /api/audit-log`.
- Produces: `renderAudit(root)`; a table of recent audit records.

- [ ] **Step 1: `api.js` — add the call**

```javascript
export function auditLog(limit = 100, offset = 0) {
  return j(`/api/audit-log?limit=${limit}&offset=${offset}`);
}
```

- [ ] **Step 2: `screen-audit.js`**

```javascript
import { auditLog } from "./api.js";

export function renderAudit(root) {
  root.innerHTML = `
    <h2>Audit Log</h2>
    <p>บันทึกกระบวนการ (ไม่มีข้อมูลส่วนบุคคล) — ล่าสุดก่อน</p>
    <div class="row"><button class="primary" id="au-refresh">Refresh</button> <span id="au-count"></span></div>
    <div id="au-out"></div>
    <p class="err hidden" id="au-err"></p>
  `;
  const $ = (id) => root.querySelector(id);

  async function load() {
    $("#au-err").classList.add("hidden");
    try {
      const r = await auditLog(200, 0);
      $("#au-count").textContent = `รวม ${r.total_count} รายการ`;
      $("#au-out").innerHTML = `<div class="card"><table>
        <tr><th>เวลา</th><th>step</th><th>entities</th><th>ผล</th><th>ms</th></tr>
        ${r.logs.map((x) => `<tr>
          <td>${new Date((x.timestamp || 0) * 1000).toLocaleString()}</td>
          <td class="mono">${x.step || x.layer || ""}</td>
          <td>${x.entity_count ?? ""}</td>
          <td>${x.validation_result || x.pii_scan_result || ""}</td>
          <td>${x.latency_ms != null ? x.latency_ms.toFixed(0) : ""}</td>
        </tr>`).join("")}
      </table></div>`;
    } catch (e) {
      $("#au-err").textContent = "โหลด audit log ไม่สำเร็จ: " + e.message;
      $("#au-err").classList.remove("hidden");
    }
  }
  $("#au-refresh").addEventListener("click", load);
  load();
}
```
(The audit records are PII-free by construction, so `step`/`layer` are safe to interpolate; still, they are fixed enum-like strings from the backend, not user text.)

- [ ] **Step 3: Wire the tab**

In `index.html` add `<button class="nav-item" data-tab="audit">Audit Log</button>` after the Settings nav item. In `app.js` import `renderAudit` and add `audit: renderAudit` to the `SCREENS` map.

- [ ] **Step 4: Verify via preview + commit**

Serve `desktop/src` + backend (do a couple of `/api/sanitize` calls first to generate records), open the Audit Log tab → table shows the records. Commit the four files with `feat(desktop): audit log viewer screen`.

---

## Self-Review

- **Spec coverage** (design spec phase 2 = "tray + global hotkey + audit viewer"): tray → Task 3; global hotkey → Task 4; audit viewer → Tasks 1,2,5. `/api/audit-log` (spec's decided read path) → Task 2. Audit-write wiring (the "hidden dependency" the design flagged) → Task 1.
- **Corrections applied vs research:** `reqwest` not `httpx`; tauri `tray-icon` feature only (not plugin features); tray Quit routes through `sidecar::kill`; hotkey handlers `spawn` async tasks (the handler closure is sync) and store `session_id` in `HotkeyState` so restore can reverse the last mask.
- **Type consistency:** `api.js` `auditLog` used by `renderAudit`; Rust `HotkeyState.last_session` written in `mask`, read in `restore`; `crate::sidecar::kill` used by both tray Quit and phase-1 window-close.
- **Flagged uncertainty:** the `tauri-plugin-global-shortcut` registration method name may differ by 2.x minor — verified at `cargo build` time (Task 4 Step 4), handler body unaffected.
