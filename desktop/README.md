# AI Guard desktop shell

A [Tauri 2](https://tauri.app) shell around the Python backend. The Rust side
spawns the packaged backend as a sidecar and owns the tray icon, global hotkeys
and the updater; the UI in `src/` is vanilla HTML/CSS/JS with no build step.

```
src/            UI screens (text, redact, report, audit, settings)
src-tauri/      Rust: sidecar lifecycle, tray, hotkeys, updater
```

The Rust shell and web UI call the sidecar on `127.0.0.1:8000`; they do not
directly call a remote provider. The sidecar can call configured providers, and
explicit `AIGUARD_NER_ENGINE=tner` sends raw pre-mask chunks to AI for Thai.
The canonical token-to-original vault stays in backend memory, but contract-v1
response objects carry direct or reconstructable mapping fields into the UI,
and residual warnings do not block every clipboard/provider path. Contract v2
and mandatory outbound blocking are open hardening gates.

If something already owns port 8000 at startup, the shell checks the owning
process's image name: its own orphaned `aiguard` backend (from a crashed shell)
is killed and respawned with a fresh boot token; anything else makes the shell
refuse to start (a native alert explains why) rather than send clipboard/UI
data to an unknown process. To attach to a from-source dev backend
(`uvicorn` under python.exe), set `AIGUARD_ALLOW_ATTACH=1` before launching —
that restores the legacy attach behavior with no identity check.

An image-name check is not cryptographic server identity. Packaged operation is
planned to move to an attested native broker with a random port and per-boot
authority; current fixed-port operation requires recertification. Session-bearing
audit filenames/entries also retain the live security-sensitive session ID
until audit correlation is hardened.

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
