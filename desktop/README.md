# AI Guard desktop shell

A [Tauri 2](https://tauri.app) shell around the Python backend. The Rust side
spawns the packaged backend as a sidecar and owns the tray icon, global hotkeys
and the updater; the UI in `src/` is vanilla HTML/CSS/JS with no build step.

```
src/            UI screens (text, redact, report, audit, settings)
src-tauri/      Rust: sidecar lifecycle, tray, hotkeys, updater
```

The shell never talks to a remote service. It calls the sidecar on
`127.0.0.1:8000`, and the token-to-original vault stays in that backend's memory.

## Develop

```powershell
python ../scripts/build_sidecar.py    # build the backend, stage it as the sidecar
npm install
npm run tauri dev
```

`build_sidecar.py` must run first — without a staged sidecar binary the shell has
no backend to spawn.

## Build

```powershell
npm run tauri build
```

Installers land in `src-tauri/target/release/bundle/`. Releases are produced by
CI from a `v*` tag, not by hand; see
[.github/workflows/release.yml](../.github/workflows/release.yml).

## Tests

```powershell
cd src-tauri && cargo test
```

Covers the sidecar kill sequence and the hotkey response handling.
