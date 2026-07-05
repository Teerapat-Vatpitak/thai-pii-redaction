# Phase 4-5: Distribution + Cross-platform Verification — Design

- Date: 2026-07-05
- Status: Approved (brainstorming complete). Decomposes into three implementation plans.
- Supersedes the phase 4-5 roadmap sketch in `2026-07-04-phase3-5-decisions-roadmap.md` (which explicitly deferred "plan later"). Phase 3 landed (Apache-2.0 + flatten-to-image), so this turns the remaining roadmap into executable plans.

## Context

The product (engine + desktop app phases 1-3) is complete: 262 pytest green, `cargo check` green, v2.0.0 published on GitHub with Windows/macOS/Linux installers built by CI. What remains is distribution and cross-platform confidence, none of which are product functions:

- No auto-updater (`Cargo.toml` has no `tauri-plugin-updater`; `tauri.conf.json` has no `plugins.updater`).
- winget/scoop manifests were prepared (`packaging/`, this session) but not yet wired for upgrade-matching or release automation.
- `release.yml` builds and drafts a release but does not sign updater artifacts or emit `latest.json`.
- macOS/Linux installers build in CI but have never run: the F1 orphan-port watchdog (`launcher.py:_watch_parent_and_exit`) is portable-by-design but unverified at runtime on real unix kernels.

## Locked decisions (from brainstorming)

1. **Structure:** one spec (this doc) → three implementation plans, run in sequence by auto mode: (A) auto-updater, (B) packaging + release CI, (C) mac/linux CI smoke-test.
2. **Updater signing key:** the user generates the Tauri minisign keypair, provides the PUBLIC key (embedded in `tauri.conf.json`), and sets the PRIVATE key + password as GitHub Actions secrets (`TAURI_SIGNING_PRIVATE_KEY`, `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`). This is separate from OS code-signing.
3. **Update UX:** prompt-style. Check on startup + a manual button in Settings; show version + release notes; download/install only on user confirm. No silent auto-install.
4. **mac/linux verification:** add a CI smoke-test on macOS + Linux runners that exercises the sidecar lifecycle and the F1 watchdog. GUI/tray/hotkey still require physical hardware and stay documented as manual.
5. **OS code-signing:** ship unsigned; document the SmartScreen "More info -> Run anyway" bypass. Revisit a paid cert only if adoption warrants.
6. **winget/scoop publishing:** manual submit (finalize manifests + documented steps); no CI automation / no PAT secret.

Baseline invariant across all three plans: **262 pytest + `cargo check` stay green**; commit only on green; one PR per plan.

---

## Component A — Auto-updater

**Design choice:** the desktop frontend is vanilla JS served statically with `withGlobalTauri: true` and no bundler. Driving the updater from the JS plugin bindings would need bundler/global-injection plumbing this app does not have. So the updater logic lives in **Rust**, exposed as two commands the frontend invokes with `window.__TAURI__.core.invoke(...)` — the same pattern as the existing `quit_app` command. Rejected: JS-side `@tauri-apps/plugin-updater`.

### Files and changes

- `desktop/src-tauri/Cargo.toml`: add `tauri-plugin-updater = "2"`.
- `desktop/src-tauri/src/updater.rs` (new):
  - `#[tauri::command] async fn update_check(app) -> Result<UpdateInfo, String>` where `UpdateInfo { available: bool, version: String, notes: String }`. Uses `app.updater()?.check().await`; maps `Some(update)` to available with `update.version` and `update.body`, `None` to unavailable, `Err` to a stringified error.
  - `#[tauri::command] async fn update_install(app) -> Result<(), String>`: re-checks, `download_and_install(...)`, then `app.restart()`.
- `desktop/src-tauri/src/lib.rs`: `mod updater;`; register `.plugin(tauri_plugin_updater::Builder::new().build())`; add `updater::update_check, updater::update_install` to `generate_handler!`.
- `desktop/src-tauri/tauri.conf.json`:
  - `bundle.createUpdaterArtifacts: true`
  - `plugins.updater.endpoints: ["https://github.com/Teerapat-Vatpitak/thai-pii-redaction/releases/latest/download/latest.json"]`
  - `plugins.updater.pubkey: "<USER PUBLIC KEY>"`
- `desktop/src-tauri/capabilities/default.json`: add `updater:default`.
- Frontend:
  - `desktop/src/screen-settings.js`: a "Check for updates" button → `invoke('update_check')`; render "up to date" / "couldn't check" / an update card with version + notes and an "Update now" button → `invoke('update_install')`.
  - `desktop/src/app.js`: a one-shot startup check that shows a dismissable banner when an update is available (never blocks the UI).
  - `desktop/src/api.js`: thin wrappers `checkUpdate()` / `installUpdate()` over `invoke`.

### Error handling

- No network / endpoint unreachable: `update_check` returns an error string; startup shows no banner; Settings shows "couldn't check for updates". Never crashes.
- Signature mismatch: the updater plugin refuses the artifact (this is the security guarantee the pubkey provides).
- Already latest: `available: false` → "You're up to date."

### Tests

- Rust: `cargo check` / `cargo test` compiling the new module is the primary gate; a trivial unit test constructs `UpdateInfo` to keep the module covered.
- Python config-assertion test (`tests/test_desktop_updater_config.py`): parse `tauri.conf.json`, assert `plugins.updater.endpoints` non-empty, `plugins.updater.pubkey` non-empty, and `bundle.createUpdaterArtifacts` is true. This guards against a later edit silently disarming the updater.
- Live end-to-end (two published releases, prompt appears, install+relaunch) is **manual** — documented, not automated.

### Key/secret nuance for auto mode

`cargo check` and dev builds do **not** need the signing key; only the release `tauri build` with `createUpdaterArtifacts` needs `TAURI_SIGNING_PRIVATE_KEY`. So auto mode can wire, compile, test, and commit Component A without the secret. The `pubkey` value is needed for the updater to *verify* updates in production but any string compiles; if the user's real pubkey is not yet available at execution time, the plan inserts a clearly marked placeholder and flags that the updater is non-functional until the real key replaces it. Signing secrets matter only in the release CI (Component B).

---

## Component B — Packaging + release CI

### Files and changes

- `.github/workflows/release.yml`: add to the `tauri-apps/tauri-action` step `env`:
  - `TAURI_SIGNING_PRIVATE_KEY: ${{ secrets.TAURI_SIGNING_PRIVATE_KEY }}`
  - `TAURI_SIGNING_PRIVATE_KEY_PASSWORD: ${{ secrets.TAURI_SIGNING_PRIVATE_KEY_PASSWORD }}`
  With `createUpdaterArtifacts` on, tauri-action generates and attaches `latest.json` + per-installer `.sig` files to the release (`includeUpdaterJson` defaults true). Keep `releaseDraft: true`.
- `packaging/winget/Teerapat-Vatpitak.AIGuard.installer.yaml`: add an `AppsAndFeaturesEntries` block now that `bundle.publisher` is real:
  ```yaml
  AppsAndFeaturesEntries:
    - DisplayName: AI Guard
      Publisher: Teerapat Vatpitak
      DisplayVersion: 2.0.0
  ```
  so `winget upgrade` matches future versions. Values are best-effort (the ARP entry only exists after installing a build carrying the new publisher); confirm against a real install when convenient. Re-run `winget validate` after the edit.
- `packaging/README.md`: finalize the manual submit steps (winget-pkgs PR path, scoop install-from-repo) and the SmartScreen/unsigned note; add the per-release hash+version bump checklist (already present, verify it covers `latest.json`).

### Dependency to surface

The updater endpoint `releases/latest/download/latest.json` only resolves once the draft release is **published** and marked "Latest". Publishing stays a manual user step (the CI drafts; the classifier blocks automated publish anyway). Until published, the updater simply reports "couldn't check", which is safe.

### Tests

CI config has no unit tests; verification is a real workflow run producing `latest.json` + `.sig` assets, plus `winget validate` on the edited manifest and a YAML parse check on `release.yml`.

---

## Component C — mac/linux CI smoke-test

Verifies the exact phase-5 risk (orphan-port zombie after the sidecar's parent is killed) on real macOS + Linux kernels, without physical hardware.

### Files and changes

- `scripts/smoke_sidecar.py` (new):
  1. Locate the staged sidecar binary (the `externalBin` target `desktop/src-tauri/binaries/aiguard-<triple>` produced by `scripts/build_sidecar.py`).
  2. Spawn it under a short-lived intermediate parent process.
  3. Poll `http://127.0.0.1:8000/api/health` until 200 (timeout ~30s) and do one `/api/sanitize` call to prove the engine runs on that OS.
  4. `kill -9` the intermediate parent to orphan the sidecar; assert the F1 watchdog exits the child and port 8000 is free within ~5s.
  5. Exit non-zero with a clear message on any failure.
  Unix-only by nature (the watchdog no-ops on Windows); the script guards/refuses on `win32` so a stray local run fails loudly rather than pretending to pass.
- `.github/workflows/smoke-crossplatform.yml` (new): matrix `macos-latest` + `ubuntu-latest`; steps mirror `release.yml`'s setup (python, deps, pre-download NER, `scripts/build_sidecar.py`), then run `scripts/smoke_sidecar.py`. Triggers: `push` to `main` + `workflow_dispatch`, so it self-verifies on merge with no tag/publish needed.

### Explicit limits

- GUI, tray, and global-hotkey behavior on mac/linux still need a real desktop session and are **not** covered here — they remain documented as manual verification before dropping "experimental" from release notes.
- The smoke script's first real execution is on CI: a Windows dev box cannot exercise the unix-only watchdog. Auto mode verifies the script imports/lints on Windows and that the workflow YAML parses; the behavioral assertion runs when the user pushes/merges (or triggers `workflow_dispatch`).

---

## Sequencing for auto mode

Run the three plans in order, each: implement → `pytest` (262 baseline) + `cargo check` → commit on green → open a PR.

1. **Plan A (updater):** Rust commands + plugin + config + capability + frontend + config-assertion test. Verifiable locally via `cargo check` + pytest without any secret.
2. **Plan B (packaging + CI):** release.yml signing env, winget `AppsAndFeaturesEntries`, README. Verifiable via `winget validate` + YAML parse.
3. **Plan C (smoke CI):** `smoke_sidecar.py` + `smoke-crossplatform.yml`. Verifiable via lint/parse locally; behavioral run on CI.

## Manual steps owned by the user

- **Before the updater is live:** generate the keypair (`npm run tauri -- signer generate -w …`), paste the PUBLIC key for `tauri.conf.json`, set `TAURI_SIGNING_PRIVATE_KEY` + `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` secrets.
- **Each release:** publish the draft release so `latest.json` becomes reachable.
- **Distribution:** submit the winget-pkgs PR; publish/point users at the scoop manifest.
- **Deferred/roadmap:** OS code-signing cert; physical mac/linux GUI/tray/hotkey verification.

## Risks

- Updater is non-functional until the user supplies the real pubkey + secrets; a placeholder compiles but cannot verify updates. Mitigated by the config-assertion test flagging an empty/placeholder pubkey and by clear docs.
- winget `AppsAndFeaturesEntries` values are best-effort until confirmed against a real install; a wrong value degrades `winget upgrade` matching (does not break install).
- mac/linux GUI path stays unverified (no hardware); only the backend lifecycle is covered by CI.
- Building the sidecar on every push to `main` in the smoke workflow adds minutes to those runs; acceptable given release/merge cadence, tunable to `workflow_dispatch`-only if noisy.

## Out of scope

OS code-signing certificate; Presidio bridge; winget CI-automation (wingetcreate/PAT); silent auto-update; physical-hardware mac/linux GUI verification; any change to the engine (`pii_redactor/`) or the browser extension.
