# Project status

Updated: 2026-07-24

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
| Microsoft 365 Add-in | Verified locally | TypeScript task pane, HTTPS localhost proxy, Word/Excel/PowerPoint adapters, stale-selection guards, memory-only session state, atomic writeback checks, safe error disclosure, manifest validation, and Node 22 CI lane are implemented. All 65 Office tests pass. Synthetic-PII local XML real-host acceptance passed for Word, Excel, and PowerPoint: Word Preview/Apply/Restore, table/multiple-paragraph Copy-only, failure handling, and protected Pathumma response insertion; Excel text-only Apply/Restore with byte-for-byte formula preservation and stale-range cancellation; and PowerPoint selected-text Apply/Restore plus isolation/capability fail-closed cases. The three-host unified manifest passes authoritative schema validation, packages deterministically, and its exact 2.5.0 acquisition metadata exposes Document, Workbook, and Presentation hosts. Custom ribbon activation on the packaged transport was not independently observable during Office client cache refresh, so this is not a Marketplace or broad Office-distribution claim. |
| CLI | Verified | Sanitize/report and end-to-end pipeline tests. |
| Demo playground | Verified | The 2026-07-23 browser run passed live token/surrogate roundtrip, protected Pathumma, guard warning, 800 px/1366 px layouts, report download/open, PDF upload/previews/redacted download, and corrected offline failure state. The downloaded redacted PDF opened with zero extractable text and no fixture value. |
| Scanned-PDF OCR | Optional | Python 3.13 full environment, focused OCR/PDF tests, and real Thai PaddleOCR inference pass; the extra remains excluded from the packaged exe and hosted core image. |
| WangchanBERTa/union and semantic detector | Optional | Requires ML extras; never selected silently. |

## Platform and delivery

| Feature | Status | Evidence / remaining gate |
|---|---|---|
| Docker image | Verified | Builds/boots non-root with the offline CRF model baked in. The 2026-07-24 local image was 115,898,138 bytes; non-service `tmp`, Office, output, and acceptance paths are excluded and pinned by a regression test. |
| Resource profile | Verified locally | Under 1 CPU/1 GiB, the local workload completed with a 177.2 MiB post-workload sample; token sanitize plus restore was 29.8 ms and PDF redact 256.5 ms. Request profile remains 1 vCPU, 1 GB RAM, 10 GB disk, no GPU. Re-measure peak/p95 on official infrastructure. |
| Queue handler operations | Verified | Detect, sanitize, analyze, restore, and roundtrip contract tests; the internal envelope is explicitly contract version 1 with safe identifier, serialization, version, and configurable provisional-size validation. |
| Queue transport/envelope | Blocked externally | HTTP-poll transport is an adapter placeholder until the platform sends its actual delivery/result contract. Onboarding staff reported that a GitLab user was emailed and the deployment repository was being prepared, but no wire specification has been verified. |
| Official AI for Thai deployment | Blocked externally | The owner can sign in to the NECTEC GitLab instance. No project, pending to-do, or repository was visible on the verified Home page; project membership, repository URL, CI/deploy procedure, and official runtime contract remain pending. |
| Platform LLM endpoint | Acceptance pending | Staff stated that a separate endpoint without the normal participant-account limit will be supplied. Endpoint URL, authentication, request/response shape, timeout, and acceptable-use/logging policy have not yet been received. Ordinary Pathumma/Arnthai/Partii calls still consume the participant account limit. |
| Retry/failure emulator | Verified locally | The repeatable local runner passes duplicate/conflict, failed submit, same-process provider idempotency, malformed/version/size, provider-timeout, handler-crash, concurrency, and honeytoken cases. It does not claim cross-process exactly-once or official ack/nack semantics. |
| Load/soak and official retry acceptance | Blocked externally | Meaningful platform soak, crash recovery, retry ownership, and platform-visible log/resource evidence require the issued account and contract. |
| Version/tag/release pipeline | Verified | v2.5.0 is published as Latest from exact merge commit `24914ab`. PR, main CI, cross-platform smoke, release metadata preflight, Windows/macOS/Linux builds, checksums, and provenance all passed. All 10 files listed in `SHA256SUMS` matched locally and verified against GitHub build provenance. The exact Windows installer upgraded the registered app to 2.5.0; binary/API versions agreed; token, surrogate, and fake-provider roundtrips passed; and closing Desktop released its sidecar and port. The unpublished v2.4.1 draft/tag remains superseded and is not moved or reused. Packaging metadata now points at the published v2.5.0 installer and its release checksum. |

## Internal-plan differences resolved here

- `block_on_guard=true` appeared in a working design but is not part of the
  submitted proposal or current API contract. Warn-only is the accepted design.
- Local `/api/reidentify` remains stateful by design. Hosted queue roundtrip is
  the preferred restoration flow because it consumes the mapping inside one
  job.
- The hosted service does not claim raw PII remains on the user's device.
- Benchmark expansion and accuracy tuning are Deferred until the feature and
  platform acceptance gates in [ROADMAP.md](../ROADMAP.md).
