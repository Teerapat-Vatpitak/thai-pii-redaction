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
| PDF redaction | Paints selected word boxes and flattens the result so covered source text is not recoverable from a text layer. Entity-to-box association is currently heuristic; exact repeated-value coverage and untouched negative controls remain open. |
| PDPA analysis | Reports direct PII, Section 26 signals, and re-identification risk without including raw values in the generated report. |
| Protected AI roundtrip | Masks a prompt, fail-closes on structured, text-based, or independent 6+ digit residuals, calls a configured provider such as Pathumma, and restores the answer. Current source uses strict HTTP-v2 projections and first-party validators; shared retry orchestration and fresh packaged/live-provider acceptance remain hardening gates. |
| Prompt-injection signals | Flags known Thai and English attacks with explicit rules plus bounded normalization/intent features. It warns; it is not a complete defense. |

## Two deployment contexts

AI Guard has one core but two different trust boundaries. They must not be
described as if they were the same deployment.

| Context | Privacy boundary |
|---|---|
| Local desktop, browser extension, and Office Add-in | The default detector, pseudonymization, and canonical mapping run on the user's device. Current backend source rejects outbound residuals before returning masked text or making an AI Guard-controlled provider call. Explicit remote TNER sends raw pre-mask chunks to AI for Thai. Current source uses strict HTTP v2 without mapping DTOs; package acceptance and localhost process identity remain open. |
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

Other gates remain open. Current source removes mapping-oriented HTTP fields,
uses strict v2 validators in browser, Desktop, and Office, and combines a
vault-generation namespace with an unpredictable nonce for each newly minted
token. Regressions show stale and guessed tokens remain foreign in the
exercised lifecycle cases. The random 64-bit generation tag plus approximately
94-bit per-token nonce makes accidental identity reuse and future-token preplay
computationally impractical; this is probabilistic separation, not
impossibility.
Fixed-port clients still do not authenticate the localhost process. Historical
release, storefront, packaged-runtime, and live-provider evidence remains valid
for the exact named artifacts, but the published 2.5.0 backend predates these
transaction, outbound-policy, HTTP-v2, and token-identity changes. Those paths
require fresh acceptance; source tests do not promote the new behavior into an
accepted package or official hosted deployment. Review high-risk output before
submitting it to an external AI.

## Storefronts

- Browser extension: in-page Mask/Restore for supported AI sites plus a docked
  side panel.
- Desktop app: bundled Tauri shell and local FastAPI sidecar.
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
| `desktop/` | Tauri shell, static UI, and packaged-sidecar integration. |
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

Requirements are Python 3.11+ and Git. Node 22 is required for the Office
Add-in and JavaScript test harness; Rust is required only to build the desktop
shell. Windows is the primary local development platform.

The quickest local start is:

```powershell
$env:PYTHONUTF8='1'
./run.ps1
```

`run.ps1` creates `.venv` and installs the core plus web dependencies on first
run. The equivalent Git Bash/Linux/macOS command is `./run.sh`. The backend
serves `http://localhost:8000`; check `http://localhost:8000/api/health` before
starting a storefront.

For a manual setup, install the same dependencies with:

```powershell
$env:PYTHONUTF8='1'
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-web.txt
```

Use [`.env.example`](.env.example) as the safe configuration reference. Keep
provider keys and the local boot/API tokens in the environment of the backend;
the canonical vault belongs in backend memory. Clients necessarily handle
submitted and returned text, and may retain a security-sensitive `session_id`.
Current HTTP v2 returns no explicit mapping DTO or backend-projected
original/token pairs; first-party clients reject unknown or missing safety
fields.

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
  backend is running; see [extension/README.md](extension/README.md).
- Desktop: run `python scripts/build_sidecar.py`, then `cd desktop`, `npm ci`,
  and `npm run tauri dev`; see [desktop/README.md](desktop/README.md).
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
checks, and packaged-runtime smoke gates. See
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

Dated acceptance remains evidence for the exact local storefront candidates
named in those records. Current source has open privacy/security/correctness
hardening gates, and Office still has eight real-host/package items in the
acceptance checklist. Detection accuracy remains the declared normal Track A
priority; the owner-approved eight-phase hardening campaign is an explicit
temporary exception, not completion of Track A. Accuracy numbers live in
generated benchmark reports with corpus size and limitations — do not infer a
public accuracy claim from prose.

The exact current candidate now has automated local transport evidence: a
newly built packaged sidecar served strict-v2 health, token sanitize, and
reidentify directly and through the Office HTTPS development proxy. The proxy
reused pre-existing trusted development certificates and left them unchanged.
This did not execute an Office client or host, install Desktop, sideload or
activate a unified manifest, call a live provider, release, or deploy anything.
Real-browser, installed Desktop, storefront, live-provider, and all eight
Office real-host/package gates remain open. The sibling
hosted port now pins current core `8c6efef`, applies its public aliases to
strict contract 2, and has immutable local commit `e075ca4`. That commit passed
the BusyBox check and provider-free deploy; independent review found no further
static blocker. Live-provider/soak evidence predates the final commit. Its
one-page OCR route passes locally but takes 221 seconds, nearly saturates its
two-core allowance, and reaches the 6 GiB memory limit, so the advertised
20-page/300-second PDF ceiling is not deploy-ready. Tokenmind credential
rotation, public HTTPS/browser routing, authoritative PDF entity-to-box
coverage, a protected/isolated production runner, first push, and platform
acceptance remain. The worker envelope
remains version 1, and shared provider orchestration, broker/auth, lifecycle,
real-host, and official-platform gates remain open.

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
