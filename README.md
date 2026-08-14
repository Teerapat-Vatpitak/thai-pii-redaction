<p align="center">
  <img src="assets/logo.png" alt="AI Guard logo" width="140" />
</p>

<h1 align="center">AI Guard</h1>

<p align="center">
  Thai PII detection, anonymization, PDF redaction, and PDPA risk analysis<br />
  for local AI workflows and AI for Thai services.
</p>

<p align="center">
  <a href="https://github.com/Teerapat-Vatpitak/thai-pii-redaction/releases/latest"><img src="https://img.shields.io/github/v/release/Teerapat-Vatpitak/thai-pii-redaction?label=release" alt="Latest release" /></a>
  <a href="https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/workflows/ci.yml"><img src="https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/workflows/ci.yml/badge.svg" alt="CI" /></a>
  <img src="https://img.shields.io/badge/runtime-local%20%7C%20container-4455aa" alt="Local and container runtimes" />
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-blue" alt="License: Apache 2.0" /></a>
</p>

AI Guard is designed to find Thai personal data before the user submits it to a
downstream AI model. It combines
regex and checksum validation for structured identifiers with Thai NER and
context rules for names and addresses. It can replace detected values with
session-namespaced tokens such as
`[ชื่อ_<generation-tag>_<token-nonce>_1]` or realistic
surrogates, restore them while the selected lifecycle still holds the
mapping—the backend vault for session flows, or an explicit caller-supplied
`prior_mapping` at the stateless core boundary—permanently cover selected PDF
word boxes, and produce a PDPA-oriented risk report.

## What is included

| Capability | What it does |
|---|---|
| Thai PII detection | Detects structured PII, names, addresses, dates, and selected quasi-identifiers. |
| Mask and restore | Token or surrogate anonymization with an in-memory mapping and outbound leak checks. |
| PDF redaction | Carries authoritative half-open source intervals into word boxes, paints only intersecting boxes, and flattens the result so covered source text is not recoverable from a text layer. Optional live OCR and physical-scan acceptance remain separate gates. |
| PDPA analysis | Reports direct PII, Section 26 signals, and re-identification risk without including raw values in the generated report. |
| Protected AI roundtrip | Masks a prompt, fail-closes on structured, text-based, or independent 6+ digit residuals, calls a configured provider such as Pathumma, and restores the answer. The 3.0.0 source uses strict HTTP-v2 projections and first-party validators; live-provider and official hosted acceptance remain separate gates. |
| Prompt-injection signals | Flags known Thai and English attacks with explicit rules plus bounded normalization/intent features. It warns; it is not a complete defense. |

## Two deployment contexts

AI Guard has one core but two different trust boundaries. They must not be
described as if they were the same deployment.

| Context | Privacy boundary |
|---|---|
| Local Desktop | The installed webview uses typed commands and authenticated native IPC to a shared broker, which owns the private authenticated HTTP-v2 backend. Mappings, backend endpoint/credentials, provider credentials, and Python session IDs never reach the webview. The installed Desktop/native-broker profile is deliberately credential-free: it fixes detection to local `thainer`, admits only `fake` as internal backend conformance support, and exposes no provider command. Slices 4--6 are integrated and ship in Desktop 3.0.0. |
| Browser Extension | The MV3 service worker owns one registered Chrome Native Messaging port to the same shared broker. Content scripts and side panels never receive mappings, Python session IDs, backend endpoints/credentials, or native transport access. Installed detection is fixed to local `thainer`; no provider, remote TNER, credential, localhost permission, HTTP client, or fallback is exposed. Slices 5--6, owner-approved production ID `kdjmkknedgmfphpkjhjdhmjadaelgggm`, exact-ID unpacked Chromium, and installed-companion gates pass. The manually installable 3.0.0 ZIP is attached to the GitHub Release; Chrome Web Store publication remains pending. |
| Office Add-in | Office remains outside broker protocol v1 and retains its separately documented strict fixed-port HTTP-v2 development path. Explicit remote TNER outside the installed Desktop/Extension boundary sends raw pre-mask chunks to AI for Thai. Fresh Office host/package acceptance and localhost process identity remain open. |
| Hosted platform service | The raw request reaches the platform-hosted AI Guard container. The selected sibling port is request-stateless, gates business routes with a signed caller cookie, proxies its public aliases to strict contract 2, and returns minimized projections without mapping DTOs. Main's `app.hosted` session routes remain a generic reference, not the selected deployment. The exact sibling commit passes provider-free local check/deploy; exact live-provider, public-proxy, and platform acceptance remain open. |

The hosted statement is intentionally narrower than the local statement. AI
Guard does not claim that raw PII stays on the user's device when the user calls
a hosted service.

The browser's in-page Mask flow starts after raw text has been typed into an AI
site's provider-controlled DOM. That page's code can observe or transmit the
draft before AI Guard acts. Use the extension side panel for raw entry and
paste only the reviewed masked result when that stronger isolation boundary is
required.

Current source is under an owner-approved hardening campaign. Local sanitize
now stages a detached session/vault graph through response rendering and a
correlation-only `prepared` process-audit write before one publication. For
non-expiry pre-publication failures, the published mapping, ordinals, and
capacity/LRU state remain unchanged. Current API process-audit callers use
fresh non-authorizing operation UUIDs instead of live restoration session IDs,
although the legacy field remains named `session_id` and file-mode logs have no
timed retention policy.

The same current source now rejects structured FP findings, text-based TB
findings, detector-independent contiguous runs of six or more digits,
anonymization failures, and missing replacement records. A caller-supplied
pseudonym is reused only when it is nonempty, does not contain its original,
and did not already occur in the current source text. The CLI rescans before
each outer `provider.complete()` invocation; a provider that owns its retries
receives one outer validation before resending the same immutable masked text.
HTTP and worker roundtrip rescan immediately before their direct calls. The
inspection endpoints `/api/detect`, `/api/analyze`, and `/api/guard` remain
report/warn paths, not outbound-use blockers.

Other gates remain open. Current source removes mapping-oriented HTTP fields
from the fixed-port Office path. Desktop and Extension instead validate broker
protocol v1 through typed Tauri or Native Messaging boundaries; backend HTTP
details and Python session IDs do not reach either storefront. All three paths
use a vault-generation namespace with an unpredictable nonce
for each newly minted token. Regressions show stale and guessed tokens remain
foreign in the exercised lifecycle cases. The random 64-bit generation tag plus
approximately 94-bit per-token nonce makes accidental identity reuse and
future-token preplay computationally impractical; this is probabilistic
separation, not impossibility.
The Office fixed-port client still does not authenticate the localhost process.
The released Extension package admits only the owner-approved exact registered
origin and browser process context before joining the broker. The downloadable
3.0.0 ZIP is for manual/developer installation; exact-ID unpacked Chromium is
not Web Store installation. Published 3.0.0 package evidence applies only to
the exact tagged source and named assets. It does not establish Office-host,
Web Store, live-provider, or official hosted-deployment acceptance. Review
high-risk output before submitting it to an external AI.

## Storefronts

- Browser extension: in-page Mask/Restore for supported AI sites plus a docked
  side panel.
- Desktop app: Tauri shell using typed native commands, authenticated broker
  IPC, and a broker-private FastAPI backend.
- Microsoft 365 Add-in: one Thai task pane with Word, Excel, and PowerPoint
  adapters. Current-source automated checks pass. A dated partial local XML
  real-host functional slice predates the HTTP-v2/token candidate and remains
  historical evidence only. The current unified release manifest is Word-only;
  Excel and PowerPoint remain acceptance-only until their host gates and the
  packaged three-host ribbon/task-pane activation pass. Schema and acquisition
  metadata are not a Marketplace or broad Office-distribution claim.
- HTTP API: detection, sanitization, re-identification, analysis, reporting,
  guard, PDF, and demo endpoints.
- Hosted HTTP adapter: `app.hosted` is a main-repository HTTP-v2 candidate with
  a fixed seven-route allowlist and required API-key/provider configuration.
  It is not the confirmed official route contract. The separate
  `aiguard-aift` repository is the selected platform port: its public
  unversioned and `/v1` aliases proxy current shared core under strict HTTP
  contract 2 and return minimized DTOs. It has no independent service-version
  source; its inherited development `2.5.0` metadata is not a hosted release
  claim. Owner-gated first push and official platform acceptance remain
  pending.
- Provisional job worker: stateless operations retained as a local
  failure/retry emulator, not the official platform delivery path.
- CLI: scripted sanitize/report workflows and an end-to-end demo pipeline.

All storefronts call the same core under `pii_redactor/`; they do not maintain
separate detection implementations.

## Repository structure

| Path | Responsibility |
|---|---|
| `pii_redactor/` | Shared detection, masking, vault, provider, restore, validation, report, and PDF logic. |
| `app/` | FastAPI and provisional worker adapters; no separate detection or vault implementation. |
| `ai_guard.py` / `demo_cli.py` | Supported CLI entry points for reports, sanitization, compliance tools, and the end-to-end demo. |
| `extension/` | Chrome MV3 storefront and site adapters. |
| `desktop/` | Tauri shell, static UI, typed broker client, lifecycle guards, ordinary package layout, and a feature-gated package-smoke harness. Evidence stays qualified by its exact path: isolated Windows NSIS installation, relocated macOS app, extracted DEB, independently extracted AppImage bytes, or finalized outer AppImage extract-and-run plus verified warm `AppRun`. Only the first is installation evidence. |
| `office-addin/` | Word, Excel, and PowerPoint task pane and host adapters. |
| `demo/` | Opt-in browser playground. |
| `benchmark/` / `research/` / `training/` | Synthetic evaluation, privacy-reviewed evidence, and optional training material. |
| `scripts/` | Build, acceptance, performance, dependency-lock, version, and release helpers. |
| `tests/` | Core, adapter, privacy, benchmark, packaging, and release contract tests. |
| `docs/` | Current operating documents and historical decision records. |

Generated reports, runtime logs, local environments, model caches, and build
output are intentionally not part of the published source tree. The committed
benchmark locks, synthetic gold data, sanitized government-form inputs, and
privacy-reviewed evidence are reproducibility inputs and remain versioned.

## Install the local product

Download Desktop 3.0.0 from the
[published release](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/releases/tag/v3.0.0):

| Platform | Direct download |
|---|---|
| Windows x64 | [`AI.Guard_3.0.0_x64-setup.exe`](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/releases/download/v3.0.0/AI.Guard_3.0.0_x64-setup.exe) |
| macOS Apple silicon | [`AI.Guard_3.0.0_aarch64.dmg`](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/releases/download/v3.0.0/AI.Guard_3.0.0_aarch64.dmg) |
| Linux amd64 | [`AI.Guard_3.0.0_amd64.AppImage`](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/releases/download/v3.0.0/AI.Guard_3.0.0_amd64.AppImage) or [`AI.Guard_3.0.0_amd64.deb`](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/releases/download/v3.0.0/AI.Guard_3.0.0_amd64.deb) |

Each Desktop package bundles the backend, so no Python setup is required.
Windows packages do not carry an Authenticode publisher signature. macOS
packages are unsigned and not notarized. Tauri updater signatures authenticate
updater bytes but do not replace operating-system publisher signing. Verify the
checksum, GitHub build provenance, download URL, and your organization's policy
before installing; see [SECURITY.md](SECURITY.md). Do not proceed if a warning
is unexpected or you cannot establish trust in the download.

### Install the Browser Extension manually

Chrome Web Store publication is pending. For manual/developer installation:

1. Install the matching Desktop 3.0.0 package above so its Native Messaging
   companion is available.
2. Download
   [`aiguard-extension-3.0.0.zip`](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/releases/download/v3.0.0/aiguard-extension-3.0.0.zip)
   and verify its SHA-256 as described below.
3. Extract the ZIP to a local directory.
4. Open `chrome://extensions` in Google Chrome and enable **Developer mode**.
5. Choose **Load unpacked**, then select the extracted directory that contains
   `manifest.json`.

This is not Chrome Web Store installation. The Extension fails closed when its
matching Desktop/native companion is unavailable. The fixed-port developer
backend does not supply an Extension endpoint. See
[extension/README.md](extension/README.md).

To develop or sideload the Windows Office task pane, see
[office-addin/README.md](office-addin/README.md). It reuses the running local
backend and does not ship in the current installer.

## Develop from source

Requirements are Python 3.11+ and Git. Node 22 is required for the JavaScript
test harness, Office Add-in, and Desktop packaging; Rust 1.97 is required to
build the native broker and Desktop shell. Windows is the primary local
development platform.

The quickest local start is:

```powershell
$env:PYTHONUTF8='1'
./run.ps1
```

`run.ps1` creates `.venv` and installs the core plus web dependencies on first
run. The equivalent Git Bash/Linux/macOS command is `./run.sh`. This developer
backend serves `http://localhost:8000`; check
`http://localhost:8000/api/health` before starting the Office Add-in, demo, or
another direct HTTP client. Desktop and Extension do not use or supply that
fixed-port endpoint: both reach the shared broker over authenticated native
IPC, and the broker alone uses a private authenticated random-loopback listener
to reach the frozen backend.

For a manual setup, install the same dependencies with:

```powershell
$env:PYTHONUTF8='1'
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-web.txt
```

Use [`.env.example`](.env.example) as the safe configuration reference for the
fixed-port developer backend. Keep provider keys and the local boot/API tokens
in that backend's environment; the canonical vault belongs in backend memory.
Extension and Office necessarily handle submitted and returned text. Office may
retain a security-sensitive HTTP `session_id`; Extension content/panel code
receives no session handle, while its service worker retains only opaque
connection/scope-bound broker authority. Current HTTP v2 returns no explicit
mapping DTO or backend-projected original/token pairs. The installed Desktop/
Extension broker boundary never reads or passes provider/TNER credentials and
rejects unsupported explicit selectors before broker connection or launch.

### API and CLI

The broad local FastAPI adapter exposes `/api/health`, `/api/detect`, `/api/sanitize`,
`/api/reidentify`, `/api/roundtrip`, `/api/analyze`, `/api/analyze-report`,
`/api/guard`, and `/api/redact-pdf`. Local introspection and lifecycle routes
also include `GET /api/audit-log`, `DELETE /api/session/{session_id}`, and
`POST /api/shutdown`; audit-log uses the data-plane API key when configured,
session deletion uses a short-lived, target-bound authorization derived from
the configured control token, and shutdown uses the control token directly.
Stateful local use pairs `sanitize` with `reidentify`; `/api/roundtrip` masks,
calls the selected provider, and restores inside one request without retaining
the mapping. Health is open for contract discovery; every other current
`/api/*` operation requires
`X-AIGuard-Contract-Version: 2`, and callers must validate the matching
response header before using a result.

Interactive API documentation is available at `http://localhost:8000/docs`.
The CLI keeps the file-oriented path reproducible:

```powershell
.\.venv\Scripts\python.exe ai_guard.py sanitize examples/prompts/01_sick_leave_email.txt
.\.venv\Scripts\python.exe ai_guard.py report examples/prompts/02_medical_consult.txt
.\.venv\Scripts\python.exe demo_cli.py
```

Use synthetic fixtures from `examples/` for demonstrations and acceptance.

### Storefront development

- Extension: build and register the matching Desktop companion and Extension
  with one exact public identity, then load the candidate in
  `chrome://extensions`; see [extension/README.md](extension/README.md). The
  deterministic repository identity is test-only, and the fixed-port backend
  is never an Extension fallback.
- Desktop: build the frozen backend and native broker, atomically stage invalid
  `{}` resource placeholders for clean-build discovery, and then build an
  ordinary Tauri bundle. The `beforeBundle` hook writes final direct-bundle
  manifests for NSIS, macOS, and DEB. AppImage stays deliberately invalid until
  the checksum-pinned post-`linuxdeploy` finalizer hashes the completed AppDir
  and repacks it. For this scrubbed no-sign/no-update path, the finalizer permits
  only appimagetool's single 16-byte `.digest_md5` rewrite in a non-executable
  ELF64 section and requires every other runtime-prefix byte to match before it
  executes and re-extracts the candidate to verify all native-component bytes.
  The feature-gated package smoke runs production webview code through real
  typed commands. Direct Windows NSIS, relocated macOS, and extracted DEB
  layouts use their package root. AppImage independently attests an extracted
  layout, starts the exact finalized outer file with
  `--appimage-extract-and-run` and a private marker root, re-attests its retained
  payload, and uses the verified `AppRun` for the warm repetition. That is not
  normal FUSE/double-click or installation evidence. `tauri dev` has no
  backend/data-plane HTTP escape path and does not assemble the manifest. See
  [desktop/README.md](desktop/README.md).
- Office: start the backend, then `cd office-addin`, `npm ci`, and `npm run dev`;
  use `start:word` for the unified Word manifest or the documented `*:local`
  commands for host-specific acceptance; see
  [office-addin/README.md](office-addin/README.md).
- Demo: set `AIGUARD_DEMO=1` before starting the backend and open `/demo`.

### Tests and development workflow

```powershell
$env:PYTHONUTF8='1'
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
npm ci
npm run test:js
```

The full Office and desktop gates are separate because they use their own
package managers and host/runtime tools:

```powershell
cd office-addin; npm ci; npm test; npm run build
cd ..\desktop\src-tauri; cargo test
```

CI also runs the core-only dependency tier, Docker-context checks, version
checks, and artifact-specific package smoke gates. Those jobs do not by
themselves prove signing, notarization, publication, upgrade, uninstall, or a
live-provider path. See
[CONTRIBUTING.md](CONTRIBUTING.md) and the [release process](docs/release-process.md)
before changing version-bearing files.

## Run the API container

```bash
export AIGUARD_API_KEY='replace-with-a-long-random-secret'
export AIGUARD_PROVIDERS='fake'
docker compose up --build ai-guard
```

The image boots `app.hosted`, refuses blank API-key or provider configuration,
and hard-allows only health, detect, analyze, guard, sanitize, reidentify, and
roundtrip. Compose publishes only to `127.0.0.1:8000`; `fake` is a local smoke
provider, not a production configuration. This is a generic hosted candidate,
not an official deployment profile. Its sanitize/reidentify pair is stateful
in process, while roundtrip uses a request-transient mapping. Exact public
routes/auth, any approved push, and official platform acceptance remain open. See
[AI for Thai integration](docs/platform/ai-for-thai.md).

Running directly from source: [docs/install-from-source.md](docs/install-from-source.md).

## Verify a release

[`SHA256SUMS`](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/releases/download/v3.0.0/SHA256SUMS)
lists the original Desktop package, updater-signature, and `latest.json` asset
set. It does not list itself or the separately attached Extension ZIP. Verify a
downloaded Desktop file with the matching checksum line and, when available,
GitHub build provenance. On Windows:

```powershell
Get-FileHash .\AI.Guard_3.0.0_x64-setup.exe -Algorithm SHA256
```

On macOS:

```bash
shasum -a 256 AI.Guard_3.0.0_aarch64.dmg
```

On Linux:

```bash
sha256sum -c SHA256SUMS --ignore-missing
```

On any platform with the GitHub CLI:

```bash
gh attestation verify <file> -R Teerapat-Vatpitak/thai-pii-redaction
```

The Extension 3.0.0 ZIP has SHA-256
`feb048775ec3d2a2c57ade08b37000fc4fa035a72ffb77db201e5eb838357670`.
Verify that exact digest separately. These checks establish origin and
integrity where stated; they are not a claim of operating-system publisher
signing or bit-for-bit reproducibility.

## Current status and limitations

Dated acceptance remains evidence only for the exact candidate and evidence
class named in each record. Current truth is deliberately split as follows:

- **Source tests:** current Python, JavaScript, Rust, Office, protocol, and
  packaging-contract tests can establish source behavior. They do not install a
  product or exercise a live host/provider.
- **Packaged tests:** the Desktop harness uses production package JavaScript,
  typed Tauri commands, the native broker, and the frozen backend. Evidence
  classes include default-path and isolated Windows NSIS, relocated macOS,
  extracted DEB, real `dpkg` lifecycle, independent AppImage byte extraction,
  exact outer AppImage `--appimage-extract-and-run`, and re-attested warm
  `AppRun`. They are not interchangeable. Normal AppImage FUSE is reported only
  when the runner can mount it; extract-and-run never substitutes for FUSE.
- **Installed real-host tests:** published 2.5.0 Desktop/browser/Office records
  remain historical pre-broker/HTTP-v2 evidence. Desktop 3.0.0 is the current
  published package set. Slice 5 has production-keyed unpacked real-Chromium
  and exact CI NSIS installed-companion evidence; that is not Web Store
  installation. Office-host and other evidence classes remain open unless a
  dated exact-candidate record says otherwise.
- **Live or external tests:** live Pathumma/TNER, official hosted-platform,
  operating-system publisher signing/notarization, Chrome Web Store
  publication, Office-host acceptance, and deployment evidence remain separate.
  A mock, schema check, package build, or local provider-free run cannot close
  them.

Desktop source now crosses broker protocol v1 and has no webview localhost
fallback. Its installed profile is fixed to local `thainer`; `fake` is the only
backend provider admitted for internal conformance, and no provider operation is
exposed to the webview. Unsupported remote/credential-backed configuration
fails closed, including when a Desktop process finds a warm broker. Slices 4--6
are integrated in the source tagged and published as v3.0.0. Office remains
outside broker v1 on fixed-port HTTP v2, and Chrome Web Store publication
remains pending.
Detection accuracy remains the declared normal Track A priority; the
owner-approved hardening campaign is an explicit temporary exception, not
completion of Track A. Accuracy numbers live in generated benchmark reports
with corpus size and limitations—do not infer a public accuracy claim from
prose.

`blind-v1` is a closed historical evidence set, not an active blind evaluation:
its six-reveal budget is exhausted. Do not tune against it or present its
historical results as a new blind measurement. Any future blind evaluation must
use a newly frozen `blind-v2` dataset.

The exact WSL candidate at commit `ded67d3` passed the nine synthetic
government-form probe inputs. That historical exact-candidate evidence does not
cover the current HTTP-v2/PDF composition, physical scans, handwriting, or
broader real-form annotation; those remain incomplete. Microsoft 365 host and
packaged-manifest acceptance also remain open. Creating and pushing the GitLab
deployment project is an owner-gated outward action. Official AI-for-Thai
deployment remains gated on Tokenmind credential rotation, protected-runner
confirmation, public proxy/HTTPS evidence, the PDF capability decision, the
owner-authorized first push, and official acceptance.

- [Current feature status](docs/project-status.md)
- [Roadmap](ROADMAP.md)
- [Architecture and trust boundaries](docs/architecture.md)
- [Release process](docs/release-process.md)

AI Guard is a safety layer, not a guarantee. Review high-risk material before
sending or publishing it. It is not affiliated with or endorsed by the AI
providers named in the integration examples.

## Documentation

- [Documentation map](docs/README.md)
- [Contributing](CONTRIBUTING.md)
- [Security policy](SECURITY.md)
- [Changelog](CHANGELOG.md)
- [Decision records](docs/decisions/README.md)

## License

Apache-2.0 - see [LICENSE](LICENSE) and [NOTICE](NOTICE).
