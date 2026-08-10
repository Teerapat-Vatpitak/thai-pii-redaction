# Running from source

The installer on the [releases page](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/releases/latest)
bundles everything and needs no Python. This page covers two different developer
paths: the fixed-port HTTP-v2 backend used by the current Extension, Office
Add-in, API, and demo; and the broker-backed Desktop package.

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
Extension, Office Add-in, API, and demo development paths. Current Desktop does
not connect to this fixed port or make it available to those storefronts. Its
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
The Extension and Office clients validate the matching response header and
exact DTO before using a result. Those fixed-port clients still do not
authenticate the localhost process. Desktop instead validates broker protocol
v1 through typed Tauri commands and has no direct backend HTTP fallback.
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

The current source extension requires the matching fixed-port current-source
backend started with `run.ps1` or `run.sh`. Launching or building Desktop does
not supply that endpoint. The extension is not compatible with the published
Desktop 2.5.0/HTTP-v1 backend, and its Chrome Native Messaging migration to the
shared broker remains Slice 5.

1. Open `chrome://extensions` in any Chromium browser.
2. Turn on **Developer mode**.
3. Click **Load unpacked** and select the `extension/` folder.
4. Pin the AI Guard extension. Its icon opens the docked side panel; the in-page
   bar activates on `chatgpt.com`, `claude.ai`, `gemini.google.com`, `grok.com`,
   `perplexity.ai`, and `chat.z.ai` / `chatglm.cn`.

Using it: type a prompt containing PII, click **Mask PII**, review the result,
send with the site's own Send button, then click **Restore PII** on the reply.
Raw text typed in the site's composer is already in provider-controlled DOM;
use the side panel for the stronger raw-entry boundary.

See [extension/README.md](../extension/README.md) for details.

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
npm run tauri -- build --bundles deb,appimage --ci --no-sign \
  --config '{"bundle":{"createUpdaterArtifacts":false}}'

# Tauri/linuxdeploy changes ELF bytes after beforeBundle. Seal the completed
# AppDir with the checksum-pinned output tool before using the AppImage.
appimage_root="src-tauri/target/release/bundle/appimage"
test "$(find "$appimage_root" -maxdepth 1 -type f -name '*.AppImage' | wc -l | tr -d ' ')" = "1"
test "$(find "$appimage_root" -maxdepth 1 -type d -name '*.AppDir' | wc -l | tr -d ' ')" = "1"
appimage=$(find "$appimage_root" -maxdepth 1 -type f -name '*.AppImage' -print -quit)
appdir=$(find "$appimage_root" -maxdepth 1 -type d -name '*.AppDir' -print -quit)
tool_dir=$(mktemp -d)
trap 'rm -rf "$tool_dir"' EXIT
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
  --appimage-plugin "$plugin" \
  --appimage-arch x86_64
```

The `{}` placeholders exist only so a clean Rust build can discover every
allowlisted Tauri resource. The `beforeBundle` hook replaces the relevant
platform placeholder with `native-components-v1.json`. NSIS, macOS, and DEB
digests cover their direct bundle inputs, including Tauri's bundle-type patch.
AppImage deliberately retains `{}` until the finalizer hashes the completed
post-`linuxdeploy` AppDir and repacks it. For this pinned, scrubbed
no-sign/no-update path, the finalizer parses both little-endian x86-64 ELF64
runtime prefixes, permits only appimagetool's single non-executable,
non-overlapping 16-byte `.digest_md5` rewrite, and requires every other prefix
byte to match before it executes the repacked runtime to confirm its offset,
re-extracts it, and checks all three native components plus the manifest. An
invalid placeholder is never accepted by the runtime. Output lands in
`desktop/src-tauri/target/release/bundle/`. A successful build is package
evidence only, not an install, upgrade/uninstall, signing/notarization, or
release-publication result.

## Troubleshooting

| Symptom | Fix |
|---|---|
| "Backend offline" in the extension | The fixed-port backend is not running — start `run.ps1` or `run.sh`. Desktop does not supply this endpoint. |
| Port 8000 already in use | Stop the process using it, or a previous fixed-port developer-backend instance. Desktop uses a broker-private random listener instead. |
| SmartScreen blocks the installer | Expected for an unsigned build: **More info → Run anyway**. |
| Extension bar does not appear | Reload the chat tab after loading the extension. |
| Thai text shows as `?` in the terminal | Set `PYTHONUTF8=1`. |
