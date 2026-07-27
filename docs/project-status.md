# Project status

Updated: 2026-07-27

This is the acceptance ledger for the current roadmap. It distinguishes code
existence from evidence on the real delivery path.

This document answers one question: **what is actually finished, and what is the
evidence**. It is not the code map ([CLAUDE.md](../CLAUDE.md)) and it does not set
priority or order ([ROADMAP.md](../ROADMAP.md)). Every storefront named in the
code map must have a row here; `tests/test_docs_coverage.py` enforces that.

## Status vocabulary

- **Verified** - implemented and covered on its intended automated/runtime path.
- **Verified locally** - passed a repeatable local runtime or emulator check,
  but is not evidence from the release transport or hosted platform.
- **Acceptance pending** - implemented, but a real provider, browser, package,
  or platform run is still required.
- **Blocked externally** - the remaining step needs a project, confirmed
  contract, provider/platform state, or another external change.
- **Optional** - supported only when an explicit extra is installed/configured;
  absence must fail clearly.
- **Deferred** - intentionally out of current scope; the list lives in
  [ROADMAP.md](../ROADMAP.md).

## Core and API

| Feature | Status | Evidence / remaining gate |
|---|---|---|
| Structured + Thai NER detection | Verified | Shared `detect_all` path, regression tests, Docker smoke. Accuracy improvement proceeds under the roadmap's detection-accuracy track (Track A). |
| Detection benchmark | Verified | `python -m benchmark` scores synthetic and hand-authored gold corpora (including a negative slice) at entity, character, and exact-boundary level, plus an engine/strategy comparison and an external LLM baseline. Reports are generated locally and gitignored. |
| Token and surrogate sanitization | Verified | Local session and stateless worker paths; residual structured-PII guard. A consistency-scan defect that could destroy an already-written pseudonym and lose the original text was found and fixed on 2026-07-26; the round-trip is covered by three non-random regression tests plus a 400-iteration repeat run. |
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
| Desktop app | Verified | The published Windows `2.5.0` installer passed the exact installed-artifact checklist on Windows 11 build 26200: API/UI version agreement, token and surrogate exact restore, global hotkeys, aggregate-only PDPA report, flattened PDF with zero extractable text, settings/audit/updater, and close/reopen with complete port release. Artifact hashes and scope are in the [dated run](acceptance/2026-07-24-desktop-2.5.0-run.md). |
| Microsoft 365 Add-in | Acceptance pending | The shared task pane, host adapters, memory-only session state, safe writeback guards, manifest validation, and all 65 automated Office tests pass. Local XML real-host evidence covers Word health/read-only Detect/Analyze, uniform Preview/Apply/Restore, stale-selection cancellation, mixed-format and multiple-paragraph Copy-only, protected Pathumma Preview/Insert, and unused-token warning; Excel mixed-range text-only write, formula preservation, stale-range cancellation, and per-cell Restore; and PowerPoint uniform selected-text Mask/Restore plus mixed-format/no-selection fail-closed behavior. Still open are Word table plus missing-key/provider/expired-session cases; Excel changed-value/formula cancellation and Pathumma Copy-only; PowerPoint full unselected-content isolation, missing API 1.5, and Pathumma Copy-only. The exact packaged three-host unified manifest still needs one real-host run proving ribbon/task-pane activation; schema, acquisition metadata, and local XML transports do not close that distribution gate. |
| CLI | Verified | Sanitize/report and end-to-end pipeline tests. |
| Demo playground | Verified | The 2026-07-23 browser run passed live token/surrogate roundtrip, protected Pathumma, guard warning, 800 px/1366 px layouts, report download/open, PDF upload/previews/redacted download, and corrected offline failure state. The downloaded redacted PDF opened with zero extractable text and no fixture value. |
| Scanned-PDF OCR | Optional | Python 3.13 full environment, focused OCR/PDF tests, and real Thai PaddleOCR inference pass; the extra remains excluded from the packaged exe and hosted core image. |
| WangchanBERTa/union and semantic detector | Optional | Requires ML extras; never selected silently. |

## Platform and delivery

| Feature | Status | Evidence / remaining gate |
|---|---|---|
| Docker image | Verified | Builds/boots non-root with the offline CRF model baked in. The 2026-07-24 local image was 115,898,138 bytes; non-service `tmp`, Office, output, and acceptance paths are excluded and pinned by a regression test. |
| Resource profile | Verified locally | Under 1 CPU/1 GiB, the local workload completed with a 177.2 MiB post-workload sample; token sanitize plus restore was 29.8 ms and PDF redact 256.5 ms. Request profile remains 1 vCPU, 1 GB RAM, 10 GB disk, no GPU. Re-measure peak/p95 on official infrastructure. |
| Queue worker operations (provisional) | Verified locally | Detect, sanitize, analyze, restore, and roundtrip contract tests pass through the internal version-1 envelope. This remains a local emulator/compatibility boundary, not the official participant delivery path. |
| Provisional queue transport/envelope | Deferred | The HTTP-poll transport and job envelope are retained for local failure/retry evidence only. The official participant guide selects an HTTP/FastAPI service behind a same-origin reverse proxy, so queue polling is not being promoted into the platform adapter. |
| Official platform HTTP adapter | Acceptance pending | The guide establishes FastAPI behind an `/api` reverse proxy that strips the prefix, an unprefixed `/health`, `root_path="/api"` for docs, loopback-only host publication, bounded logs, masked CI variables, and Compose deployment from `main`. The current server still declares `/api/*`, restricts trusted hosts to localhost, and does not yet have a deliberately allowlisted/authenticated hosted operation surface. Only this adapter/configuration delta should change after the remaining contract answers arrive. |
| Official AI for Thai deployment | Acceptance pending | GitLab sign-in and group membership are verified, and the participant guide plus service-access materials have arrived. The group currently has no deployment project or repository, so project/template ownership, repository URL, CI variables, first deployment, and platform acceptance evidence remain open. |
| Platform LLM endpoint | Acceptance pending | The platform issued an endpoint, model identifier, and secret out of band. No secret or account identifier is stored here. Request/response compatibility, authentication placement, timeout, quota, acceptable-use/logging policy, and one protected live roundtrip still require confirmation and acceptance. |
| Retry/failure emulator | Verified locally | The repeatable local runner passes duplicate/conflict, failed submit, same-process provider idempotency, malformed/version/size, provider-timeout, handler-crash, concurrency, and honeytoken cases. It does not claim cross-process exactly-once or official ack/nack semantics. |
| Load/soak and official failure acceptance | Blocked externally | Meaningful platform soak, restart behavior, platform-visible log/resource evidence, and any retry ownership require the deployment project and accepted HTTP contract. |
| Version/tag/release pipeline | Verified | v2.5.0 is published as Latest from exact merge commit `24914ab`. PR, main CI, cross-platform smoke, release metadata preflight, Windows/macOS/Linux builds, checksums, and provenance all passed. All 10 files listed in `SHA256SUMS` matched locally and verified against GitHub build provenance. The exact Windows installer upgraded the registered app to 2.5.0; binary/API versions agreed; token, surrogate, and fake-provider roundtrips passed; and closing Desktop released its sidecar and port. The unpublished v2.4.1 draft/tag remains superseded and is not moved or reused. Packaging metadata now points at the published v2.5.0 installer and its release checksum. |

## Internal-plan differences resolved here

- `block_on_guard=true` appeared in a working design but is not part of the
  submitted proposal or current API contract. Warn-only is the accepted design.
- Local `/api/reidentify` remains stateful by design. Hosted HTTP roundtrip is
  the preferred restoration flow because it consumes the mapping within one
  request and does not export it.
- The hosted service does not claim raw PII remains on the user's device.
- Benchmark and detection-accuracy work is active under the roadmap's Track A
  in [ROADMAP.md](../ROADMAP.md); the remaining Office and platform items are
  acceptance gates tracked above, not deferred scope.
