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
| Protected provider roundtrip | Acceptance pending | Fake-provider path and failure modes are tested; Pathumma wire probe succeeded, but the competition demo/platform path needs a repeated live acceptance run. |
| PDPA JSON analysis | Verified | Shared analyzer and API tests. |
| Thai PDPA PDF report | Verified | Whitelisted PII-free renderer and end-to-end tests. |
| PDF redaction and preview | Verified | Text-layer path covered end to end; output flattened. |
| Prompt-injection signals | Verified | Thai/English rule corpus and documented bypass cases. Canonical behavior is warn-only. |
| HTTP API authentication | Verified | Optional local compatibility; required in hosted configuration. |
| PII-free public errors/logs | Verified | Contract and worker safety tests; official platform-visible log scan remains part of platform acceptance. |

## Integrations and storefronts

| Feature | Status | Evidence / remaining gate |
|---|---|---|
| Pathumma provider | Acceptance pending | Live form-data probe preserved sample tokens; expand to a repeatable provider acceptance corpus. |
| AI for Thai TNER engine | Acceptance pending | Client and opt-in engine are tested with fixtures; run the live service on the acceptance corpus. |
| Browser extension | Acceptance pending | JS/DOM fixtures cover declared sites; manual current-site smoke and live demo rehearsal remain. |
| Desktop app | Acceptance pending | Rust/JS tests and packaged Windows sidecar smoke pass; final candidate install/update rehearsal remains. |
| CLI | Verified | Sanitize/report and end-to-end pipeline tests. |
| Demo playground | Acceptance pending | All endpoints are tested; live Pathumma, projector layout, PDF download, and offline fallback need rehearsal. |
| Scanned-PDF OCR | Optional | Requires OCR extras and returns an explicit unavailable error when absent; not included in the hosted core image. |
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
| Version/tag/release pipeline | Acceptance pending | v2.4.0 built successfully; docs/release governance are being reset and the next candidate must prove the revised process. |

## Internal-plan differences resolved here

- `block_on_guard=true` appeared in a working design but is not part of the
  submitted proposal or current API contract. Warn-only is the accepted design.
- Local `/api/reidentify` remains stateful by design. Hosted queue roundtrip is
  the preferred restoration flow because it consumes the mapping inside one
  job.
- The hosted service does not claim raw PII remains on the user's device.
- Benchmark expansion and accuracy tuning are Deferred until the feature and
  platform acceptance gates in [ROADMAP.md](../ROADMAP.md).
