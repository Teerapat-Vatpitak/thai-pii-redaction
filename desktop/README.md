# AI Guard Desktop

AI Guard Desktop is a Tauri 2 shell with a static HTML/CSS/JavaScript UI. The
current package routes Desktop and Extension product data through separate
authenticated connections to one native broker:

```text
webview -> typed Tauri command -+
                               +-> typed Rust Desktop broker client
global hotkey -----------------+   -> authenticated native IPC
                                   -> shared broker
                                   -> private authenticated HTTP-v2 backend
                                   -> shared Python core
Chrome -> registered native host -> extension-role broker connection ---+
```

The webview uses only operation-specific Tauri commands. Hotkeys call the same
typed Rust client directly; they do not pass through the webview. Neither path
implements provider, detector, vault, PDF, or backend logic. Production
Desktop contains no direct backend/data-plane HTTP client, port scan, Python
launcher, or localhost fallback. The updater remains a separate Rust-side
client for its fixed HTTPS release host.

The Rust process is admitted under the existing protocol-v1 `desktop` role.
Each window gets its own `desktop_ui` scope and global hotkeys use a separate
`desktop_hotkey` scope. The webview may retain an opaque broker session handle
for continuity. It never receives a Python session ID, mapping, backend
address or credential, native endpoint detail, provider credential, or TNER
credential.

The installed Desktop/native-broker profile is credential-free and
deterministic. It supports only local `thainer`; the managed backend's provider
allowlist is `fake` solely for internal conformance, and no provider command is
registered for the webview. Any explicit detector other than `thainer` fails as
`ner_unavailable`, and any explicit provider allowlist other than `fake` fails
as `provider_configuration`, before broker connection or launch. A rejected
attach never reaches or poisons an already-running warm broker.

At both Desktop-to-broker and broker-to-backend child seams, the native policy
constructs an environment from a fixed allowlist of ordinary runtime-variable
names. It never queries or copies AI for Thai, Anthropic, Tokenmind,
detector/provider selector, transport-control, fine-tuned model, or inherited
broker API/control values, and it pins `AIGUARD_NER_ENGINE=thainer` and
`AIGUARD_PROVIDERS=fake`. Desktop and broker no longer take independent remote
configuration snapshots. Parent environment variables therefore cannot
silently enable remote TNER or a credential-requiring provider.

Credential-requiring providers and remote TNER for installed Desktop are
deferred. Adding them requires a separate owner-approved ADR covering credential
ownership, provisioning, permissions, storage, rotation, configuration
identity/epoch, broker restart/reconfiguration semantics, upgrade, uninstall,
attestation, and cross-platform behavior. No credential store is added by Slice
4 or Slice 5, and broader core, CLI, HTTP, hosted, and worker capabilities are
unchanged.

The webview can invoke only the typed commands registered in
`src-tauri/src/lib.rs`. There is no raw broker send, arbitrary operation,
arbitrary JSON/URL/HTTP client, shell command, filesystem escape hatch, or
localhost fallback. Rust validates each request and response with the shared
machine-readable protocol-v1 policy before a value reaches the UI, clipboard,
or filesystem. PDF extraction/redaction, mappings, and HTTP-v2 behavior stay in
the Python backend and shared core. The native protocol retains a conformance
roundtrip path, but Desktop rejects a non-`fake` provider before backend
submission and the installed UI cannot invoke that operation. Broader Python
interfaces retain their explicit provider and remote-TNER behavior outside the
installed Desktop profile.

```text
src/            Static UI and strict native-result validators
src-tauri/      Typed Tauri commands, Desktop broker client, tray, hotkeys,
                updater, and lifecycle cleanup
tests/          Frontend contract, lifecycle, write-safety, package, and XSS tests
```

## Lifecycle and failures

The first PII-free health request connects to an existing broker or uses the
Slice 2 single-owner startup path. Simultaneous Desktop starts converge on one
broker and one private backend. A broker/backend restart creates a new
generation; old handles do not survive it.

Desktop never replays a submitted data operation. A disconnect, timeout,
malformed response, uncertain mutation, or failed cleanup clears affected
local authority. If explicit session/scope cleanup cannot be confirmed, Rust
disconnects so broker connection cleanup is the fail-closed fallback. Closing
a window closes only that window's scope; app quit closes UI and hotkey scopes
without issuing global broker stop. Renderer generations and the terminal
restart-required state prevent stale queued work from publishing after reload,
close, or broker invalidation.

The UI shows only fixed safe guidance. It does not display socket names, pipe
paths, ports, credentials, internal IDs, or Rust/Python exception strings.

## Develop and compile

Run frontend commands from the repository root:

```powershell
npm ci
npm run test:js
node --check desktop\src\app.js
node --check desktop\src\api.js
```

Run Rust checks from the repository root as well:

```powershell
cargo fmt --manifest-path desktop\src-tauri\Cargo.toml -- --check
cargo clippy --locked --manifest-path desktop\src-tauri\Cargo.toml `
  --all-targets --all-features -- -D warnings
cargo test --locked --manifest-path desktop\src-tauri\Cargo.toml --all-features
cargo test --locked --manifest-path native-broker\Cargo.toml --test slice4
```

The native runtime requires `native-components-v1.json` beside the installed
Desktop, broker, Chrome adapter, native-host manager, and backend executables.
`tauri dev` does not assemble that
layout and is not an accepted runnable path; there is no `AIGUARD_ALLOW_ATTACH`,
direct-Uvicorn, or localhost escape hatch.

## Build and installed-package smoke

The ordinary Tauri bundle hook creates final direct-bundle manifests for
Windows NSIS, macOS app, and Linux DEB layouts. AppImage deliberately receives
an invalid pre-manifest because linuxdeploy mutates ELF bytes after that hook.
Before linuxdeploy runs, the cross-platform workflow preserves the exact
PyInstaller backend in a private runner path. The finalizer requires its frozen
archive cookie, atomically restores that backend after linuxdeploy, writes the
manifest from the restored final AppDir bytes, and repacks with a
checksum-pinned plugin. For the pinned,
scrubbed no-sign/no-update path, it permits only appimagetool's single
non-executable, non-overlapping 16-byte `.digest_md5` rewrite and requires every
other x86-64 ELF64 runtime-prefix byte to match before it executes, re-extracts,
and verifies the candidate components/manifest. Only then does it atomically
replace the AppImage. Evidence from an installed Windows NSIS root, a relocated
macOS app, an extracted Linux DEB layout, and the finalized outer AppImage must
be reported separately. Relocation and DEB extraction are not installation
evidence. The AppImage job independently extracts one layout to attest its
bytes, then launches the exact finalized outer file with
`--appimage-extract-and-run`; a later warm repetition re-attests the retained
live root and launches its `AppRun`. That is executable-package evidence, not a
normal FUSE/double-click launch, an installation, a raw inner-binary launch, or
two outer-AppImage launches.

The `package-smoke` feature is absent from default builds. When explicitly
compiled, it adds a native-start marker plus bounded readiness/success/failure
evidence commands and loads `src/package-smoke.js`. Every smoke mode passes a
separately precreated, canonical private mode-0700 evidence directory through
`AIGUARD_DESKTOP_PACKAGE_SMOKE_ROOT`; direct-layout evidence is not written
into the package working directory. An invalid supplied root fails without a
package-directory fallback. Rust accepts only the four fixed marker names,
publishes complete files without overwriting an existing entry, and removes
only each writer's own temporary file. The script uses the production `api.js`
path and actual typed Tauri commands for health, analyze,
fresh and continuation sanitize, native validated masked copy, reidentify,
report, PDF, audit, session dispose, and scope reset. It does not exercise
detect, guard, roundtrip, a live provider, or live TNER.

Build the Windows acceptance installer from the repository root:

```powershell
.\.venv\Scripts\python.exe scripts\build_sidecar.py
.\.venv\Scripts\python.exe scripts\build_native_broker.py
.\.venv\Scripts\python.exe scripts\prepare_desktop_native_package.py `
  --build-placeholders `
  --extension-identity path\to\owner-approved-public-identity.json
Push-Location desktop
npm ci
npm run tauri -- build --bundles nsis --features package-smoke --ci --no-sign `
  --config '{"bundle":{"createUpdaterArtifacts":false}}'
Pop-Location
```

The placeholder step is required on a clean tree so Tauri can discover every
configured resource. It writes deliberately invalid `{}` files. For this NSIS
command, the ordinary `beforeBundleCommand` replaces the selected placeholder
with a manifest for the bytes installed by that direct bundle. AppImage keeps
its invalid pre-manifest until the explicit post-linuxdeploy finalizer described
above. A placeholder is never a runnable manifest.

After installing that exact NSIS candidate into an isolated directory, run:

```powershell
.\.venv\Scripts\python.exe scripts\smoke_desktop_native_package.py `
  artifacts\slice4-nsis-installed --repetitions 5
```

Current evidence is deliberately split:

| Candidate/path | Evidence |
|---|---|
| historical dirty-tree Windows NSIS `7277341A62CEF70C8431BE4AEA51E9C0CA916E8C01ABDC8D0267C087869AE681` | 12 installed launches; final runs required complete positive resource evidence and every run left zero broker/backend process delta; historical only |
| clean predecessor `c6dcad1` Windows NSIS | all 14 jobs in [CI run 31325662048](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31325662048) passed, including two launches from an isolated NSIS install root; predecessor only |
| clean predecessor `0424716` macOS app | the macOS job passed a twice-smoked relocated app in [run 31326610316](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31326610316), but the overall workflow failed on Linux; not installation evidence |
| earlier predecessor `8be9523` Windows CI | all 14 jobs in [run 31327288545](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31327288545) passed, including two launches from the exact isolated NSIS installation; artifact 9042030989; installer SHA-256 `dfa777757ec9961679dcd5074fa48cffb446166fb2b229d418e1f5eb816ebc6c`; predecessor only |
| earlier predecessor `8be9523` macOS app | job 93279571751 passed the relocated app smoke in [run 31327288595](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31327288595); relocation only, not installation/notarization evidence |
| earlier predecessor `8be9523` Linux DEB/AppImage | job 93279571732 failed before Desktop launch because process inspection treated an unrelated protected same-UID process as fatal; diagnostic harness failure, no Linux package result |
| predecessor `6ad3422` local harness | reviewed Linux process-name prefilter plus exact `/proc` path/fail-closed candidate checks; 56 package/workflow tests, Ruff, format, diff-check, and a real WSL clean-parser probe passed |
| predecessor `6ad3422` Windows CI | all 14 jobs in [run 31328047804](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31328047804) passed, including two launches from the exact isolated NSIS installation; artifact 9042210975; installer SHA-256 `c014a400ae622815a94be6a4f2686e7dac900cdff10ec1fdeaa3d5c4ab56a1b3`; zero broker/backend process delta |
| predecessor `6ad3422` macOS/Linux package smoke | [run 31328047802](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31328047802) is red: relocated macOS passed (artifact 9042161197; tested-app archive SHA-256 `8d22957bba783737df954dee5c2a76a012ebeb1bb6f4c1f04886e93916245939`) and extracted DEB completed two runs, but AppImage exact-component digest verification failed before AppImage Desktop launch after packaging mutated component bytes; no AppImage, full Linux, or cross-platform pass |
| predecessor `3836024` finalizer/workflows | stages the post-linuxdeploy manifest and repacks with pinned plugin asset 497460911; [CI run 31329794579](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31329794579) passed 14/14, but [cross-platform run 31329794568](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31329794568) is red: macOS passed and Linux failed finalization before package smoke because the first prefix guard did not allow appimagetool's defined `.digest_md5` rewrite |
| predecessor `73dcca4` AppImage verifier | permits only the unique non-executable, non-overlapping 16-byte `.digest_md5` rewrite, rejects executable-segment overlap, and compares every other prefix byte before executing/re-extracting the candidate; 76 focused package/workflow tests and exact-delta independent review passed with no P0/P1/P2 |
| predecessor `73dcca4` workflows | [CI run 31345691672](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31345691672) passed 14/14 including installed Windows NSIS; [cross-platform package run 31345691667](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31345691667) is red: relocated macOS and extracted DEB passed, but the AppImage harness bypassed the outer runtime/`AppRun` and produced no marker, so it supplies no AppImage or full-Linux pass |
| predecessor `8194c23` CI and installed Windows NSIS | [CI run 31348501253](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31348501253) is red, 10/14: four Rust jobs failed only because the new canonical-root unit test used non-portable path spellings; the installed-NSIS job `93334827088` nevertheless passed two direct-layout launches with zero broker/backend process delta and uploaded artifact `9048319122`; its published digest is the GitHub artifact-wrapper digest, not an installer SHA-256 |
| predecessor `8194c23` macOS/Linux package smoke | [run 31348501256](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31348501256) passed 2/2: relocated macOS artifact `9048238724` has tested archive SHA-256 `48881bf929258fe980ff43b2dc4fa948b0a122e55cbb1508bdf9e817a533a624`; Linux artifact `9048343920` contains the directly smoked DEB (SHA-256 `5f6dde7aed7335ccb6944560fc4aecc993c09a6c6f5cbd18964b0ae2074ca127`) and the finalized AppImage (SHA-256 `0b139d9f03d88d1a2984445de8d2e08d29fe42ce6120072524dd9ed5ed8cc17d`) whose outer `--appimage-extract-and-run` launch plus verified warm `AppRun` passed with `execution_mode=outer_appimage_extract_and_run_then_verified_apprun` |
| current executable checkpoint `492dad3` local verification | retains the `8194c23` production marker-root/AppImage contract and repairs only portable canonical-path test construction; focused package/workflow Python tests pass 100 with one expected Windows Unix-mode skip; full local Rust runs of 19 default and 26 all-feature tests preceded the final portability-only edit, after which the exact private-root test passed on Windows and real WSL; exact CI confirms all 26 Desktop tests on Ubuntu, Windows, and macOS; Ruff, Python format, rustfmt, strict Clippy, and diff-check pass |
| current executable checkpoint `492dad3` installed Windows NSIS | [CI run 31349781519](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31349781519) passed 14/14, including two direct-layout launches from the exact isolated NSIS installation with zero broker/backend process delta; artifact `9048710352`; exact tested installer 70,500,529 bytes, SHA-256 `6ca6f5dc3fcdfc3dfc51c210ace1734bcede7f77298d1e3ea7019d9d8b5a425c`; the separate `961f9e8e25e150e0e5ad7e7124d56569b100e4fb671adfa7f5c51b3f4f8ab4ee` digest and 70,501,963-byte size describe the GitHub artifact ZIP |
| current executable checkpoint `492dad3` cross-platform packages | [run 31349781518](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31349781518) passed 2/2. Relocated macOS artifact `9048609980` has tested archive SHA-256 `15a64e25af00f30e288f62c837725cccb9e9588fc0f90d668a57d6d1164f0de8`. Linux artifact `9048696066` contains the directly smoked DEB, SHA-256 `7411b1c976d66a7e4e4a48f757ad751eb69ac0a8a4105d318559ab64fc30bfb7`, and finalized AppImage, SHA-256 `915d4ebb139ee69a1d9514d6fdb306ab7e2bbd02e12a858bb4deaedcf5a1f5f7`; both ran twice with zero broker/backend process delta, and AppImage recorded `execution_mode=outer_appimage_extract_and_run_then_verified_apprun` |

No row establishes live provider/TNER behavior, manual visual acceptance,
updater check/install, supported-path relocation, upgrade/drain, interrupted
upgrade, stale cleanup, uninstall, signing/notarization, release, or deployment.

The owner-selected local-only configuration boundary is integrated. The Slice
5 branch packages the Chrome adapter and registration manager, registers exact
per-platform native-host manifests for owner-approved production ID
`kdjmkknedgmfphpkjhjdhmjadaelgggm`, and lets Chrome start/join the broker
without the Desktop GUI. Production-origin package and installed-companion
evidence is green; the deterministic identity remains test-only. The Web Store
item is still Draft/unpublished, and exact-ID unpacked Chromium evidence is not
Web Store installation.
DEB registration remains package-manager/root-owned rather than pretending an
ordinary GUI launch can repair `/etc`; macOS and AppImage use their documented
per-user repair paths, and Windows uses the NSIS hooks.
Slice 6 has not started and still owns manual visual, installer/relocation,
updater, upgrade/interruption/stale-cleanup, and broad uninstall recertification.
Tag-triggered publication remains fail-closed until those gates pass.

See
[`docs/acceptance/2026-08-09-phase-8-native-broker-desktop.md`](../docs/acceptance/2026-08-09-phase-8-native-broker-desktop.md)
for the exact migration boundary, fault matrix, performance evidence, and
remaining Slice 4 gates. The Slice 5 candidate evidence is in
[`docs/acceptance/2026-08-11-phase-8-slice-5-native-messaging.md`](../docs/acceptance/2026-08-11-phase-8-slice-5-native-messaging.md).
