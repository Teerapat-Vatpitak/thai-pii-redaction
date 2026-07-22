# Project status

Updated: 2026-07-22

This is the acceptance ledger for the current roadmap. It distinguishes code
existence from evidence on the real delivery path.

## Status vocabulary

- **Verified** - implemented and covered on its intended automated/runtime path.
- **Acceptance pending** - implemented, but a real provider, browser, package,
  or platform run is still required.
- **Blocked externally** - the remaining step needs an account/spec or another
  external state change.
- **Optional** - supported only when an explicit extra is installed/configured;
  absence must fail clearly.
- **Deferred** - intentionally after feature and platform acceptance.

## Core and API

| Feature | Status | Evidence / remaining gate |
|---|---|---|
| Structured + Thai NER detection | Verified | Shared `detect_all` path, regression tests, Docker smoke. Accuracy improvement is deferred, not functional completion. |
| Token and surrogate sanitization | Verified | Local session and stateless worker paths; residual structured-PII guard. |
| Local multi-turn re-identification | Verified | In-memory session vault, TTL/LRU, collision and concurrency tests. |
| Stateless hosted sanitization | Verified | Worker operation; mapping omitted by default. |
| Protected provider roundtrip | Verified | Repeatable live Pathumma acceptance passed on 2026-07-22: raw synthetic PII stayed out of provider-visible text and every returned token restored. Official hosted deployment remains a separate platform gate. |
| PDPA JSON analysis | Verified | Shared analyzer and API tests. |
| Thai PDPA PDF report | Verified | Whitelisted PII-free renderer and end-to-end tests. |
| PDF redaction and preview | Verified | Text-layer path is covered end to end and flattened; the optional scanned/OCR path also passed in the Python 3.13 full-acceptance environment. |
| Prompt-injection signals | Verified | Thai/English explicit rules plus a bounded normalization/intent layer; the five previously recorded bypasses are now passing regressions with ordinary-language negative controls. Canonical behavior remains warn-only. |
| HTTP API authentication | Verified | Optional local compatibility; required in hosted configuration. |
| PII-free public errors/logs | Verified | Contract and worker safety tests; official platform-visible log scan remains part of platform acceptance. |

## Integrations and storefronts

| Feature | Status | Evidence / remaining gate |
|---|---|---|
| Pathumma provider | Verified | Repeatable live completion and protected-roundtrip checks pass; marker preservation is recorded as quality telemetry because a generative response need not repeat every entity. |
| AI for Thai TNER engine | Verified | Live service shape and end-to-end `PER/LOC/ORG/DTM` mapping passed on 2026-07-22; decoder is pinned to the live parallel `words`/`POS`/`tags` contract. |
| Browser extension | Acceptance pending | Versioned ZIP packaging and 43 JS/DOM tests pass. Chrome had no candidate extension loaded and automation cannot install it, so current-site mask/restore still requires the owner to load the exact candidate. |
| Desktop app | Acceptance pending | The first rehearsal UI passed token/surrogate restore, PDPA analysis, PDF upload/preview/download, theme, PII-free audit view, and updater check, while exposing four defects now fixed with regressions. A fresh isolated build from exact commit `58bb6ab` produced a verified NSIS installer/shell/sidecar and passed 19 Rust tests without touching the running old process. It must still be opened to verify the fixed report/PDF UI plus hotkeys and close/reopen; CI Node-22/updater signing remains separate. |
| CLI | Verified | Sanitize/report and end-to-end pipeline tests. |
| Demo playground | Acceptance pending | Live token/surrogate roundtrip, guard warning, 800 px/1366 px layouts, report generation, and corrected offline failure state pass. Browser download/open and PDF file-chooser flow remain blocked by the current Chrome automation permission. |
| Scanned-PDF OCR | Optional | Python 3.13 full environment, focused OCR/PDF tests, and real Thai PaddleOCR inference pass; the extra remains excluded from the packaged exe and hosted core image. |
| WangchanBERTa/union and semantic detector | Optional | Requires ML extras; never selected silently. |

## Platform and delivery

| Feature | Status | Evidence / remaining gate |
|---|---|---|
| Docker image | Verified | Builds/boots in CI as non-root with the offline CRF model baked in. |
| Resource profile | Verified locally | Current image displays about 465 MB; measured high-water physical memory about 198 MB on the feature workload. Request profile: 1 vCPU, 1 GB RAM, 10 GB disk, no GPU. Re-measure on official infrastructure. |
| Queue handler operations | Verified | Detect, sanitize, analyze, restore, and roundtrip contract tests. |
| Queue transport/envelope | Blocked externally | HTTP-poll transport is an adapter placeholder until the platform sends its actual spec/account. |
| Official AI for Thai deployment | Blocked externally | Account/username, registry, and deployment contract have not been issued. |
| Load/soak and retry acceptance | Acceptance pending | Emulator and official-platform acceptance suite must be completed before feature freeze. |
| Version/tag/release pipeline | Acceptance pending | v2.4.0 is published. The npm lockfile drift gap and yanked build dependency were fixed, but GitHub reports no configured `main` protection and the next version must not be cut until storefront acceptance closes. |

## Internal-plan differences resolved here

- `block_on_guard=true` appeared in a working design but is not part of the
  submitted proposal or current API contract. Warn-only is the accepted design.
- Local `/api/reidentify` remains stateful by design. Hosted queue roundtrip is
  the preferred restoration flow because it consumes the mapping inside one
  job.
- The hosted service does not claim raw PII remains on the user's device.
- Benchmark expansion and accuracy tuning are Deferred until the feature and
  platform acceptance gates in [ROADMAP.md](../ROADMAP.md).
