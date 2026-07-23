# Project status

Updated: 2026-07-23

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
| Protected provider roundtrip | Verified | Repeatable live Pathumma acceptance passed again on 2026-07-23: raw synthetic PII stayed out of provider-visible text and every returned token restored. Official hosted deployment remains a separate platform gate. |
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
| AI for Thai TNER engine | Verified | Live service shape and end-to-end `PER/LOC/ORG/DTM` mapping passed again on 2026-07-23; decoder is pinned to the live parallel `words`/`POS`/`tags` contract. |
| Browser extension | Verified | The exact unpacked candidate passed live Mask smoke on ChatGPT, Claude, Gemini, Grok, Perplexity, and GLM/Z.ai in Chrome 150; ChatGPT also passed fail-closed backend-offline, closed-shadow Restore, and two-turn token consistency checks. The run exposed and fixed current Grok Tiptap selection and Perplexity Lexical write/commit regressions; all 55 JS/DOM tests pass. The owner also completed and confirmed the manual generic side-panel Mask check on 2026-07-23. |
| Desktop app | Verified locally | Fresh packaged UI from exact commit `58bb6ab` passed token/surrogate restore, PDPA analysis and PII-free report download, PDF upload/previews/localized download with whitelisted chips, 300-DPI address coverage including `99`, global hotkey mask/restore, settings/audit/updater, and close/reopen with sidecar port release. This duplicate `2.4.0` rehearsal is not publishable; release CI must rebuild under pinned Node 22 and sign updater artifacts. |
| Microsoft 365 Add-in | Acceptance pending | TypeScript task pane, HTTPS localhost proxy, Word/Excel/PowerPoint adapters, stale-selection guards, memory-only session state, atomic writeback checks, safe error disclosure, manifest validation, and Node 22 CI lane are implemented. All 59 Office tests pass. Correcting unified `validDomains` to the host-and-port form allowed Word to acquire the AI Guard ribbon and task pane; unified Word evidence now also covers multiple-paragraph Copy-only, protected Pathumma preview, and explicit response insertion. Local XML evidence covers Word token/surrogate exact restore and mixed size/color/highlight fail-closed; Excel text-only Apply/Restore, byte-for-byte formula preservation, and stale-range cancellation; and PowerPoint selected-text Apply/Restore plus mixed/no-selection fail-closed. Word table and real-host failure scenarios, Excel/PowerPoint Ask AI, deeper PowerPoint isolation/capability fallback, and Excel/PowerPoint unified promotion remain open. Local XML results do not satisfy the unified promotion gate, and no host is fully accepted. The compatible manifest fix remains included without claiming full Office support; the owner paused this lane and the completed Office scope remains a future minor release. |
| CLI | Verified | Sanitize/report and end-to-end pipeline tests. |
| Demo playground | Verified | The 2026-07-23 browser run passed live token/surrogate roundtrip, protected Pathumma, guard warning, 800 px/1366 px layouts, report download/open, PDF upload/previews/redacted download, and corrected offline failure state. The downloaded redacted PDF opened with zero extractable text and no fixture value. |
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
| Version/tag/release pipeline | Verified | v2.4.2 is published as Latest from exact merge commit `5c7149d`. All main and tag workflow jobs passed; the complete asset set matched `SHA256SUMS`; GitHub provenance identified the expected repository/tag/commit; and the exact Windows installer passed registration, version, launch/API, token/surrogate/fake-roundtrip, close, and port-release smoke. The unpublished `v2.4.1` draft/tag remains superseded and is not moved or reused. Full Office support remains gated for v2.5.0. |

## Internal-plan differences resolved here

- `block_on_guard=true` appeared in a working design but is not part of the
  submitted proposal or current API contract. Warn-only is the accepted design.
- Local `/api/reidentify` remains stateful by design. Hosted queue roundtrip is
  the preferred restoration flow because it consumes the mapping inside one
  job.
- The hosted service does not claim raw PII remains on the user's device.
- Benchmark expansion and accuracy tuning are Deferred until the feature and
  platform acceptance gates in [ROADMAP.md](../ROADMAP.md).
