# Running from source

The published 2.5.0 installer on the
[releases page](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/releases/latest)
predates the current broker-backed Desktop/Extension package. This page covers two distinct
developer paths: the fixed-port HTTP-v2 backend used by Office, API, and demo;
and the broker-backed Desktop/Extension package source path. Slice 6 is
integrated through its recorded exact-tree protocol; these developer commands
are not installed-package or 3.0.0 release-artifact acceptance.

## Requirements

Python 3.11+ and git.

## Start the fixed-port developer backend

```bash
git clone https://github.com/Teerapat-Vatpitak/thai-pii-redaction.git
cd thai-pii-redaction
```

```powershell
./run.ps1     # Windows (PowerShell)
```

```bash
./run.sh      # Linux / macOS / git-bash
```

The script creates a virtual environment and installs dependencies on first run
(a few minutes). The first Thai NER run downloads a ~2 MB model, so it needs
internet once. The backend then listens on `http://localhost:8000` for the
Office Add-in, API, and demo development paths. Current Desktop and Extension
do not connect to this fixed port or make it available to those storefronts. Their
native broker owns a private random loopback listener and its per-boot
credentials, and transfers the listener plus credentials to the frozen backend
child through an inherited channel. None of them reaches the webview.

Check it: open `http://localhost:8000/api/health`. Current source returns
`status`, `version`, `contract_version: 2`, and the
`control_token_required`/`api_key_required` capability booleans, together with
the matching v2 response header. Interactive API docs are at
`http://localhost:8000/docs`.

Current source uses strict HTTP contract v2. It removes mapping-oriented
response fields, separates control- and data-plane capability flags, and
requires `X-AIGuard-Contract-Version: 2` on every API operation except health.
The Office client validates the matching response header and exact DTO before
using a result. That fixed-port client still does not authenticate the
localhost process. Desktop and Extension instead validate broker protocol v1
and have no direct backend HTTP fallback.
Outbound-capable local sanitization plus CLI, HTTP, and worker
provider boundaries fail closed on the shared residual policy from source-level
automated evidence; packaged, real-host, live-provider, and official hosted
evidence remains open. The default detector is local; explicitly selecting
`AIGUARD_NER_ENGINE=tner` sends raw pre-mask chunks to AI for Thai. See the
[current status](project-status.md) before using this checkout.

## Local hosted-container candidate

The Docker image runs `app.hosted`, not the broad local `app.server` surface.
It refuses to boot unless both `AIGUARD_API_KEY` and `AIGUARD_PROVIDERS` are
nonempty, then hard-allows exactly health, detect, analyze, guard, sanitize,
reidentify, and roundtrip. Document, audit, demo, shutdown, and session-disposal
routes are absent. This is a generic local candidate, not the confirmed
official AI for Thai contract. Keep the Compose profile loopback-only:

```bash
export AIGUARD_API_KEY='replace-with-a-long-random-secret'
export AIGUARD_PROVIDERS='fake'
docker compose up --build ai-guard
```

Send that value in `X-AIGuard-Key` on protected data-plane calls and send
`X-AIGuard-Contract-Version: 2` on every API operation except health. `health`
remains unauthenticated for contract discovery. `fake` is suitable only for a
local smoke. Provider credentials are validated when that provider is used,
not at container boot. Do not expose this candidate as a production hosted
surface. The official reverse-proxy route/auth boundary and remaining external
gates are documented in
[AI for Thai integration](platform/ai-for-thai.md).

The sanitize/reidentify pair retains its canonical mapping in the serving
process until service-managed eager expiry at the exact `age >= TTL` boundary,
LRU eviction, or restart; the hosted allowlist has no explicit disposal route.
Roundtrip instead consumes a request-transient mapping. Current v2 responses
project only sanitized/restored text and safe counts/metadata. Token mode
combines a non-secret random vault-generation tag with an unpredictable nonce
for each newly minted token. Exercised regressions keep stale and guessed
tokens foreign; the random 64-bit tag plus approximately 94-bit nonce makes
accidental reuse and preplay computationally impractical, not impossible.
Neither component is a credential. API process-audit callers use fresh
non-authorizing operation UUIDs instead of live restoration session IDs; the
legacy audit field remains named
`session_id`, and local files have no timed retention policy. Source automation
is not packaged Desktop or official-platform acceptance and does not authorize
sticky multi-instance routing around this candidate.

## Browser extension

Current source uses only Chrome Native Messaging. It requires an Extension
candidate and Desktop companion built with the same exact public identity,
component manifest, and version. Starting `run.ps1`/`run.sh` does not supply an
Extension endpoint, and there is no HTTP fallback.

Production packaging uses the owner-approved unpublished Chrome Web Store
identity in `config/chrome-extension-identity.json`. Its public key derives
Item ID `kdjmkknedgmfphpkjhjdhmjadaelgggm`; no private key is stored or needed.
The identity fixture under `tests/fixtures/native_host/` is deterministic and
public-only but classified `synthetic_test_only`; use it only with the explicit
test-acceptance build flag. It must never be presented as a production or Web
Store identity.

For the approved production identity:

1. Build the Extension and companion from the same checkout, passing
   `config/chrome-extension-identity.json` to the package scripts.
2. Install the companion so its native-host manager registers the exact
   manifest and origin. Chrome can run the Extension without the Desktop GUI.
3. Open `chrome://extensions`, enable Developer mode, and load the built
   candidate directory. Confirm its derived ID exactly matches registration.
4. Pin the icon for the docked side panel. The in-page bar activates on
   ChatGPT, Claude, Gemini, Grok, Perplexity, and GLM/Z.ai.

Using it: type a prompt containing PII, click **Mask PII**, review the result,
send with the site's own Send button, then click **Restore PII** on the reply.
Raw text typed in the site's composer is already in provider-controlled DOM;
use the side panel for the stronger raw-entry boundary.

See [extension/README.md](../extension/README.md) for details.

On Linux DEB, native-host registration is owned by the package-manager hooks
under `/etc`; repair requires reinstalling or repairing that package with the
same administrative boundary. An ordinary user GUI launch never mutates those
root-owned files. AppImage registration is per-user and its transient startup
repairs the staged stable component root. macOS startup repairs its per-user
registration; Windows registration is owned by the NSIS hooks.

Install, repair, update, and remove must go through the owning package path.
The package first activates a fixed verified maintenance barrier, then its
manifest-admitted manager drains the broker/backend before bytes are replaced.
Do not copy individual native executables between installs: every runtime
requires the exact complete manifest set, fixed owner/mode/link state, and
matching embedded build markers/digests. An interrupted repair either restores
one complete set or remains fail-closed; it never restores an old mapping.
Since 3.0.0 no DEB or AppImage is published, so the two Linux paths below apply
only to a 3.0.0 install or to a package you build yourself from this source.
Running from source on Linux is unaffected and stays supported.

Windows uses the NSIS installer/uninstaller, DEB uses `dpkg`, and AppImage uses
its transient `AppRun` or explicit unregister path. Manually calling the
manager is an internal package/test operation, not a supported substitute for
those owners. The in-app updater is enabled only on Windows, where Tauri
verifies the artifact and launches NSIS. macOS, DEB, and AppImage reject update
check/install before updater access; use an external/user-owned package
replacement followed by the documented repair path.

## Command line

```bash
python ai_guard.py report examples/prompts/02_medical_consult.txt
python ai_guard.py sanitize examples/prompts/01_sick_leave_email.txt
python demo_cli.py
```

Issue a PDPA section 39 processing receipt for a file, then check it later:

```bash
python ai_guard.py receipt issue mydoc.pdf -o mydoc.receipt.json --pdf mydoc.receipt.pdf \
  --purpose "screening before sending to an AI assistant" --controller "HR department"
python ai_guard.py receipt verify mydoc.receipt.json mydoc.pdf
```

The receipt records what was processed — counts, types, the file's hash, the
system version and NER engine — and never a value from the document. `verify`
runs the same pipeline again and compares digests, so it exits 0 only when the
file is the same file and the system still finds the same things in it. A
version or engine change is reported alongside the result, because that is
usually the explanation. `--purpose` and `--controller` are yours to state;
the tool leaves them out rather than inventing them. `issue` will not write
over an existing receipt unless you pass `--overwrite`.

Sample inputs live in `examples/`.

## Optional: semantic sensitive detector

PDPA Section 26 categories are found by keyword scan by default. An optional
MiniLM sentence-embedding pass catches free-form phrasing the keywords miss:

```bash
pip install -r requirements-ml.txt
```

It is non-generative — it only flags spans already present in your text, so it
cannot invent PII. Without it, the keyword scan runs alone and nothing breaks.

The same extra enables the opt-in WangchanBERTa and `union` NER engines
(`AIGUARD_NER_ENGINE`); see
[docs/decisions/2026-07-15-ner-engine-strategy-decision.md](decisions/2026-07-15-ner-engine-strategy-decision.md)
for why the CRF engine is the default.

## Tests

```bash
python -m pytest        # Python
npm run test:js         # extension harness (vitest + jsdom)
cd desktop/src-tauri && cargo test    # Tauri shell
```

On Windows, set `PYTHONUTF8=1` first so Thai text is not mangled by the console
code page.

## Build the desktop app

Desktop requires Node 22, Rust 1.97, and a Python 3.13 environment containing
the hash-locked build dependencies. From a clean checkout, prewarm the pinned
model, build and stage both native components, and create deliberately invalid
resource placeholders before invoking Tauri. On Windows PowerShell, set
`$env:PYTHONUTF8='1'` before the Python commands:

```bash
python -m pip install pip==26.1.2
python -m pip install --require-hashes -r requirements-build.lock
python scripts/prewarm_ner.py
python scripts/build_sidecar.py
python scripts/build_native_broker.py
python scripts/prepare_desktop_native_package.py --build-placeholders
cd desktop
npm ci
```

Run exactly the command for the current host, still inside `desktop/`:

```powershell
# Windows
npm run tauri -- build --bundles nsis --ci --no-sign `
  --config '{"bundle":{"createUpdaterArtifacts":false}}'
```

```bash
# macOS
npm run tauri -- build --bundles app --ci --no-sign \
  --config '{"bundle":{"createUpdaterArtifacts":false}}'
```

```bash
# Linux
tool_dir=$(mktemp -d)
trap 'rm -rf "$tool_dir"' EXIT
triple=$(rustc -vV | sed -n 's/^host: //p')
backend_source="$tool_dir/aiguard-appimage-backend"
test -f "src-tauri/binaries/aiguard-$triple"
test ! -e "$backend_source"
install -m 0755 "src-tauri/binaries/aiguard-$triple" "$backend_source"
cmp -- "src-tauri/binaries/aiguard-$triple" "$backend_source"

npm run tauri -- build --bundles deb,appimage --ci --no-sign \
  --config '{"bundle":{"createUpdaterArtifacts":false}}'

# Tauri/linuxdeploy changes ELF bytes and strips the frozen-backend overlay.
# Restore the preserved backend and seal the completed AppDir before use.
appimage_root="src-tauri/target/release/bundle/appimage"
test "$(find "$appimage_root" -maxdepth 1 -type f -name '*.AppImage' | wc -l | tr -d ' ')" = "1"
test "$(find "$appimage_root" -maxdepth 1 -type d -name '*.AppDir' | wc -l | tr -d ' ')" = "1"
appimage=$(find "$appimage_root" -maxdepth 1 -type f -name '*.AppImage' -print -quit)
appdir=$(find "$appimage_root" -maxdepth 1 -type d -name '*.AppDir' -print -quit)
plugin="$tool_dir/linuxdeploy-plugin-appimage-x86_64.AppImage"
curl --proto '=https' --tlsv1.2 --fail --location --retry 3 \
  --header 'Accept: application/octet-stream' \
  --output "$plugin" \
  'https://api.github.com/repos/linuxdeploy/linuxdeploy-plugin-appimage/releases/assets/497460911'
echo 'a45d3e227bc7f397e9cf6bfa4c9507494efa2293357b6e86690a3de2ca992e79  '"$plugin" \
  | sha256sum --check --strict
chmod 0755 "$plugin"
python ../scripts/prepare_desktop_native_package.py --finalize-appimage "$appimage" \
  --appdir "$appdir" \
  --appimage-backend-source "$backend_source" \
  --appimage-plugin "$plugin" \
  --appimage-arch x86_64
```

The `{}` placeholders exist only so a clean Rust build can discover every
allowlisted Tauri resource. The `beforeBundle` hook replaces the relevant
platform placeholder with `native-components-v1.json`. NSIS, macOS, and DEB
digests cover their direct bundle inputs, including Tauri's bundle-type patch.
AppImage deliberately retains `{}` until the finalizer hashes the completed
post-`linuxdeploy` AppDir and repacks it. Linux packaging preserves the exact
pre-`linuxdeploy` frozen backend outside the build tree because linuxdeploy
otherwise strips its PyInstaller archive overlay. The finalizer rejects a
preserved source without the frozen-archive cookie, restores it atomically,
and hashes those restored bytes into the manifest. For this pinned, scrubbed
no-sign/no-update path, the finalizer parses both little-endian x86-64 ELF64
runtime prefixes, permits only appimagetool's single non-executable,
non-overlapping 16-byte `.digest_md5` rewrite, and requires every other prefix
byte to match before it executes the repacked runtime to confirm its offset,
re-extracts it, and checks all five native components plus the manifest. A
transient AppImage Desktop then repairs and attests the stable per-user copy
and re-executes the manifest-verified stable Desktop so it shares one exact
package root with Chrome's registered adapter. Repair is serialized by a
private lock, stages verified components atomically, publishes the manifest
last, and removes only a verified owned inactive stable root. An invalid
placeholder or partial staged root is never accepted by the runtime. Output lands in
`desktop/src-tauri/target/release/bundle/`. A successful build is package
evidence only, not an install, upgrade/uninstall, signing/notarization, or
release-publication result.

## Troubleshooting

| Symptom | Fix |
|---|---|
| "Companion unavailable" in the Extension | Install or repair the matching Desktop companion and native-host registration. `run.ps1`/`run.sh` does not supply an Extension endpoint. |
| Port 8000 already in use | Stop the previous fixed-port developer backend if Office/API work needs it. Desktop and Extension use broker-private transport instead. |
| SmartScreen blocks the installer | Expected for an unsigned build: **More info → Run anyway**. |
| Extension bar does not appear | Reload the chat tab after loading the extension. |
| Thai text shows as `?` in the terminal | Set `PYTHONUTF8=1`. |
