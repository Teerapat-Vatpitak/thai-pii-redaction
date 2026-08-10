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
| Protected AI roundtrip | Masks a prompt, fail-closes on structured, text-based, or independent 6+ digit residuals, calls a configured provider such as Pathumma, and restores the answer. Current source uses strict HTTP-v2 projections and first-party validators; shared retry orchestration and fresh packaged/live-provider acceptance remain hardening gates. |
| Prompt-injection signals | Flags known Thai and English attacks with explicit rules plus bounded normalization/intent features. It warns; it is not a complete defense. |

## Two deployment contexts

AI Guard has one core but two different trust boundaries. They must not be
described as if they were the same deployment.

| Context | Privacy boundary |
|---|---|
| Local Desktop | The installed webview uses typed commands and authenticated native IPC to a shared broker, which owns the private authenticated HTTP-v2 backend. Mappings, backend endpoint/credentials, provider credentials, and Python session IDs never reach the webview. The installed Desktop/native-broker profile is deliberately credential-free: it fixes detection to local `thainer`, admits only `fake` as an internal backend conformance provider, and exposes no provider command to the webview. Unsupported explicit engine/provider selectors fail before broker connection or launch with `ner_unavailable` or `provider_configuration`; broker and backend children receive a name-allowlisted runtime environment that never queries provider/TNER credential values and pins `thainer`/`fake`. Remote TNER and credential-requiring providers remain available only outside this installed-product boundary. Slice 4 is integrated; Slice 5 has not started. |
| Browser extension and Office Add-in | The default detector, pseudonymization, and canonical mapping run on the user's device. Current backend source rejects outbound residuals before returning masked text or making an AI Guard-controlled provider call. Explicit remote TNER sends raw pre-mask chunks to AI for Thai. These storefronts still use strict direct HTTP v2 without mapping DTOs; fresh package acceptance and localhost process identity remain open. |
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
from the fixed-port Extension and Office path, and those clients validate strict
HTTP-v2 DTOs. Desktop instead validates broker protocol v1 through typed Tauri
commands; backend HTTP details and Python session IDs do not reach its webview.
All three paths use a vault-generation namespace with an unpredictable nonce
for each newly minted token. Regressions show stale and guessed tokens remain
foreign in the exercised lifecycle cases. The random 64-bit generation tag plus
approximately 94-bit per-token nonce makes accidental identity reuse and
future-token preplay computationally impractical; this is probabilistic
separation, not impossibility.
The Extension and Office fixed-port clients still do not authenticate the
localhost process. Historical
release, storefront, packaged-runtime, and live-provider evidence remains valid
for the exact named artifacts, but the published 2.5.0 backend predates these
transaction, outbound-policy, HTTP-v2, and token-identity changes. Those paths
require fresh acceptance; source tests do not promote the new behavior into an
accepted package or official hosted deployment. Review high-risk output before
submitting it to an external AI.

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

Download the installer for your platform from the
[latest release](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/releases/latest):

| Platform | File |
|---|---|
| Windows | `AI.Guard_<version>_x64-setup.exe` |
| macOS (Apple Silicon) | `AI.Guard_<version>_aarch64.dmg` |
| Linux | `.AppImage` or `.deb` |

The installer bundles the backend, so no Python setup is required. It is
unsigned by design. Verify the checksum and GitHub build provenance before
installing; see [SECURITY.md](SECURITY.md).

To add the in-page browser bar to a published install, use the extension from
the matching release candidate. The current source extension requires the
current source HTTP-v2 backend; load `extension/` unpacked only with that
matching backend. See [extension/README.md](extension/README.md).

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
`http://localhost:8000/api/health` before starting the Extension, Office Add-in,
demo, or another direct HTTP client. Desktop does not use or supply that
fixed-port backend: Desktop reaches the shared broker over native IPC, and the
broker alone uses a private authenticated random-loopback listener to reach the
frozen backend.

For a manual setup, install the same dependencies with:

```powershell
$env:PYTHONUTF8='1'
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-web.txt
```

Use [`.env.example`](.env.example) as the safe configuration reference for the
fixed-port developer backend. Keep provider keys and the local boot/API tokens
in that backend's environment; the canonical vault belongs in backend memory.
Extension and Office necessarily handle submitted and returned text, and may
retain a security-sensitive `session_id`. Current HTTP v2 returns no explicit
mapping DTO or backend-projected original/token pairs; those clients reject
unknown or missing safety fields. Desktop's broker-backed configuration boundary
is separate: provider/TNER credentials are not passed to broker/backend children
or used as installed-product configuration, and unsupported explicit selectors
fail closed before broker connection or launch.

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

- Extension: load `extension/` unpacked in `chrome://extensions` while the
  separately started fixed-port backend is running; see
  [extension/README.md](extension/README.md). Launching Desktop does not provide
  this backend.
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

Every release asset is listed in `SHA256SUMS` and carries GitHub build
provenance:

```bash
sha256sum -c SHA256SUMS --ignore-missing
gh attestation verify <file> -R Teerapat-Vatpitak/thai-pii-redaction
```

This verifies origin and integrity. It is not a claim of bit-for-bit
reproducibility.

## Current status and limitations

Dated acceptance remains evidence only for the exact candidate and evidence
class named in each record. Current truth is deliberately split as follows:

- **Source tests:** current Python, JavaScript, Rust, Office, protocol, and
  packaging-contract tests can establish source behavior. They do not install a
  product or exercise a live host/provider.
- **Packaged tests:** the Desktop harness uses production package JavaScript,
  typed Tauri commands, the native broker, and the frozen backend. Its evidence
  classes are an isolated Windows NSIS installed root, a relocated macOS app
  layout, a directly extracted DEB layout, independent AppImage byte
  extraction, and exact outer AppImage `--appimage-extract-and-run` followed by
  a re-attested warm `AppRun`. They are not interchangeable. The AppImage path
  does not prove normal FUSE/double-click behavior or an installed lifecycle.
- **Installed real-host tests:** the published 2.5.0 Desktop/browser/Office
  records remain historical pre-broker/HTTP-v2 evidence. They do not certify the
  current candidate. Current Extension live-site, Office-host, package
  upgrade/uninstall, and complete installed cross-platform acceptance remain
  open unless a dated exact-candidate record says otherwise.
- **Live or external tests:** live Pathumma/TNER, official hosted-platform,
  signing/notarization, store submission, release publication, and deployment
  evidence remain separate. A mock, schema check, package build, or local
  provider-free run cannot close them.

Desktop source now crosses broker protocol v1 and has no webview localhost
fallback. Its installed profile is fixed to local `thainer`; `fake` is the only
backend provider admitted for internal conformance, and no provider operation is
exposed to the webview. Unsupported remote/credential-backed configuration
fails closed, including when a Desktop process finds a warm broker. Slice 4
integration is complete. The Extension
and Office remain fixed-port HTTP-v2 clients; Slice 5 is specifically the
Extension Chrome Native Messaging migration to the existing shared broker, and
Slice 6 is cross-platform package/install/relocation/updater/upgrade,
interrupted-upgrade, stale-cleanup, and uninstall recertification. New tag
publication is intentionally preflight-blocked until those delivery gates are
complete.
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
