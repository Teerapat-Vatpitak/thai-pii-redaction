# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).
The current version lives in [`VERSION`](VERSION) — see `scripts/check_version.py` /
`scripts/bump_version.py` for how every other version-bearing file stays in sync.

Entries below v2.2.0 are a coarse backfill from git history, not a per-commit
log — see `git log` for full detail on any release.

## [Unreleased]

### Changed

- Release drafts now explicitly require release-specific changelog notes before
  publication and show platform-correct SHA256 verification commands for
  Windows, macOS, and Linux.

## [2.4.2] - 2026-07-23

Release-acceptance patch. Microsoft 365 remains paused and
acceptance-pending; this release does not claim complete Office support.

### Fixed

- Surrogate mode now preserves a two-part shape for multi-part Thai names, so
  the outbound high-recall guard no longer absorbs the following ordinary
  phrase and blocks the playground's own generated name.
- The Grok adapter now prefers the current Tiptap/ProseMirror composer over its
  visible one-character helper textarea.
- The Perplexity adapter now writes through the current Lexical editor's
  `beforeinput` path and waits for a short, bounded visible-state commit before
  reporting success. A write that never lands still raises the fail-closed
  blocking overlay.

### Verified

- The exact unpacked extension candidate masked synthetic PII on ChatGPT,
  Claude, Gemini, Grok, Perplexity, and GLM/Z.ai in Chrome 150 without sending
  a prompt. ChatGPT additionally passed backend-offline fail-closed behavior,
  closed-shadow restoration, and two-turn token consistency.
- Playground report download/open and PDF upload/preview/redacted-download
  flows passed in a real browser. The flattened output exposed no extractable
  source text.
- Repeatable live Pathumma completion/protected-roundtrip and TNER
  tagging/pipeline mapping passed on 2026-07-23.

## [2.4.1] - 2026-07-23

Compatibility and release-hardening update after v2.4.0. Microsoft 365 work
remains an acceptance-pending preview and is not claimed as a fully supported
Office distribution in this patch.

### Added

- Declared platform API contract v1 with an independently versioned health
  response and Docker smoke coverage for every declared endpoint.
- Optional `AIGUARD_API_KEY` authentication for hosted API deployments.
- Current-state documentation for architecture, feature acceptance, AI for Thai
  integration, and the version/tag/release lifecycle.
- A repeatable, PII-free functional acceptance runner and manual checklists for
  Extension, Desktop, Playground, PDF, Pathumma, and TNER.
- A Desktop action that generates and downloads the existing whitelisted Thai
  PDPA PDF report, with explicit progress, success, and error states.
- A shared Microsoft 365 task pane and Word, Excel, and PowerPoint host adapters
  for detection, PDPA analysis, masking, restoration, and protected Pathumma
  preview through the existing local backend.
- A release-readiness gate that requires version targets, tag, dated changelog
  section, and a fresh empty `Unreleased` section to agree before a tag builds.

### Changed

- Queue sanitization omits the PII-bearing mapping unless the caller supplies
  the exact boolean opt-in; protected `roundtrip` is the preferred hosted
  restoration path because it consumes the mapping inside one job.
- Packaging manifests now point at the published v2.4.0 installer.
- README, roadmap, and security policy now distinguish the local-device trust
  boundary from the hosted-platform trust boundary and place functional
  acceptance before accuracy benchmarking.
- Release jobs now run only from immutable tags, use least-privilege workflow
  permissions, install Node dependencies with `npm ci`, and refuse incomplete
  cross-platform asset sets.

### Fixed

- Account-number labels emitted by Thai NER no longer acquire a false ADDRESS
  type merely because the word `เลขที่` appears inside the label itself.
- Version bumps validate every target before writing, so a parser/layout failure
  cannot leave the repository half-bumped.
- Packaging metadata downloads now have a bounded network timeout.
- Live TNER now decodes its parallel `words`/`POS`/`tags` response correctly;
  compact labels (`PER`, `DTM`) map to AI Guard `NAME` and `DATE`
  types instead of being silently discarded.
- Demo privacy wording now remains accurate when the playground is hosted.
- Prompt-injection warnings now recover the five recorded spaced-letter,
  paraphrase, possessive-target, and Thai bare-rule bypasses through bounded
  normalization and intent features, while retaining warn-only behavior.
- Playground roundtrip failures now clear the stale provider badge and pending
  restore state instead of leaving an old result that looks in progress.
- The version drift gate and bump script now cover both npm lockfile root
  version fields; the previously stale `0.1.0` metadata now matches `VERSION`.
- The OCR extra no longer installs two distributions that both own `cv2`;
  PaddleX supplies the single OpenCV runtime used by PaddleOCR.
- Hash-pinned build/core locks now use non-yanked `pypdfium2` 5.12.1.
- Acceptance evidence now records a full commit plus dirty-worktree state and
  strips credential-bearing URL components before writing JSON.
- Desktop PDF results now render safe detector type labels instead of
  `[object Object]`, localize the download action, and describe only the chat
  sites the extension currently declares.
- House numbers after form-style address labels such as `ที่อยู่: 99` are now
  detected and blacked out; detector-span and rendered-pixel regressions pin
  the complete address coverage.
- The Microsoft 365 unified manifest now declares its trusted localhost domain
  as a host and port rather than a URL, allowing Word to acquire the AI Guard
  ribbon and task pane; deterministic validation prevents the regression.

## [2.4.0] - 2026-07-22

AI for Thai platform-readiness and the remaining audit-v2 medium findings.

### Added

- Stateless sanitize/restore core and a queue worker whose transport is isolated
  from the product operations while the official platform wire spec is pending.
- Pure detect and protected roundtrip APIs, including a Pathumma provider that
  uses the verified AI for Thai form-data contract.
- Opt-in AI for Thai TNER engine; the default CRF path remains fully offline.
- Opt-in three-panel demo playground with text masking/roundtrip, PDF
  before/after comparison, and PDPA report download.
- Thai PDPA PDF report endpoint that renders only whitelisted aggregate fields.
- Thai/English rule-based prompt-injection signals with documented bypass cases
  and warn-only behavior.

### Changed

- Docker became a tested deliverable: Python/dependencies/toolchains are pinned,
  the CRF model is baked into an appuser-owned offline data directory, the image
  runs non-root, and CI boots it for an end-to-end masking smoke.
- Session storage now has LRU eviction and a coarse process lock that makes the
  single-user local API safe across FastAPI worker threads.
- `/api/redact-pdf` runs as a synchronous endpoint so CPU-heavy PDF/OCR work does
  not block the async event loop.

### Fixed

- Extension masking re-reads the target composer, reports success only when the
  sanitized text actually landed, and displays a blocking failure overlay.
- Restored PII overlays are rendered inside a closed shadow root so page scripts
  cannot read the restored content.
- Desktop startup verifies the process that owns port 8000 before trusting it
  and reaps a verified orphaned sidecar on the next launch.
- Output validation no longer treats ordinary Thai/English text or numbers at
  the end of a document as truncation.
- Desktop webview capabilities were reduced and report counts are coerced to
  numeric values before rendering.

## [2.3.0] - 2026-07-20

First post-competition release. Its headline is not a feature: a full-repo
audit found — and this release closes — six ways PII could leak or be restored
to the wrong person, several of which the product's own guarantees depended on.
Findings and evidence: `docs/decisions/2026-07-19-audit-v2-findings.md`.

### Added

- **Verifiable build.** Hash-pinned Python lockfiles, a pinned PyInstaller, a
  SHA256-pinned Thai NER model, SHA-pinned GitHub Actions, and explicit
  pip/Rust/Node versions. Every release asset ships with `SHA256SUMS` and
  GitHub build provenance (`gh attestation verify`). This is origin and
  integrity verification, not bit-for-bit reproducibility. The one deliberate
  exception (unversioned apt packages) is documented rather than glossed over.
- **Release-pipeline gates**: the pushed tag must match `VERSION` before
  anything is built, the NER model must match its pin before being bundled,
  and the asset set must belong to this release before anything is hashed or
  attested.
- Control-plane boot token (`AIGUARD_TOKEN`) gating `/api/shutdown` and
  `DELETE /api/session/{id}`.
- JS (vitest + jsdom) and Rust (cargo) test harnesses alongside pytest.
- Thai PII benchmark corpus (synthetic v1 + a harder "gold" v2) with a 4-way
  NER strategy comparison (CRF vs. WangchanBERTa vs. union) and an ADR
  recording the strategy decision.
- Opt-in **union NER engine** (`AIGUARD_NER_ENGINE=union`) that runs the
  offline CRF engine and WangchanBERTa together and unions their spans for
  higher recall, plus a post-detection consistency sweep.
- Real CI test gate: pytest on Windows + Linux, a core-only-install job,
  `cargo test` for the desktop shell, a JS syntax check, and a Windows
  packaged-exe smoke test that boots the shipped sidecar end-to-end.

### Changed

- **Unified the web and CLI paths onto one core** (`pii_redactor/session_service.py`).
  `/api/sanitize` and `/api/reidentify` now go through the same `SessionVault`,
  pre-send leak guard, and reverse mapper the CLI pipeline always used,
  closing the "two brains" gap between the storefronts (Horizon-2 #8).
- **Restructured text-based detection**: stride-chunk windowing (~1.2x chars
  tagged instead of ~7x), and honest entity labels — business dates no longer
  become fake birthdays and invoice numbers no longer masquerade as passports.
  Nothing that was masked before became unmasked; the labels stopped lying.
- **Text cleaning is now 4 stages, not 7.** Broken-word recovery, OCR-error
  flagging, and broken-sentence review were removed after verifying against
  running code that they were dead weight: the word-recovery stage loaded the
  entire Thai dictionary to alter nothing, the OCR stage flagged every word
  containing B or Z, the review stage was unreachable, and nothing consumed any
  of their output.
- The browser extension now reuses its session across turns, so token numbering
  stays consistent within a conversation.

### Fixed

- **Redaction boxes could miss the PII on skewed scans.** OCR produced word
  boxes from a deskewed (rotated) page while redaction painted them onto the
  unrotated original, so on a tilted scan the black boxes landed beside the
  text they were meant to cover. Deskew was removed from the OCR path.
- **Thai landline numbers were never detected.** The pattern required 10
  digits; Thai landlines have 9, so every standard-format number passed through.
- **A national ID or phone next to a Thai abbreviation could vanish entirely.**
  The vehicle-plate pattern claimed the leading digits, and deduplication then
  dropped the checksum-verified number instead of the low-confidence plate.
- **Re-identification could splice real PII into unrelated text.** A surrogate
  value that happened to be a substring of a longer number or word was replaced
  in place, injecting the real value mid-token with no warning.
- **Restoring an earlier reply could reveal the wrong person's data.** The
  extension minted a new session on every mask, so a later restore mapped
  tokens against a different conversation's vault.
- **The desktop hotkey failed silently, leaving raw PII in the clipboard.** A
  backend that was down — or actively refusing because it detected a leak —
  produced no feedback, so the unmasked text could be pasted believing it was
  masked. Masking now fails closed and says so.
- API hardening: an unknown `mode` returns 400 instead of silently falling back,
  oversized PDF uploads return 413 before the body is buffered, and a hostile
  session id can no longer escape the audit-log directory.
- Thai-aware output validation: text ending in Thai characters is no longer
  treated as truncated (Thai has no sentence-final punctuation), which had been
  failing every legitimate Thai export.

- Three confirmed recall leaks: a Thai national ID glued directly to Thai
  script escaping detection (`\b` treating Thai characters as word
  characters), `+66` international mobile numbers not matching (or matching
  with the wrong label), and scanned pages inside an otherwise text-layer PDF
  being silently dropped by per-document (not per-page) source-type routing.
- Collision-safe pseudonym generation: a small fake-name pool meant two
  different people could draw the same pseudonym and silently overwrite each
  other's vault entry; the anonymizer now checks uniqueness before writing,
  re-rolls the seed, and falls back to a `#N` suffix.
- Cross-detector span merge: overlapping FP/TB spans could corrupt text
  during the anonymizer's tail-first replace; span deduplication is now a
  shared module (`detectors/aggregate.py`) used by both the web and CLI paths.

## [2.2.0] - 2026-07-09

- Extension + desktop UI redesign: docked side panel (replacing the toolbar
  popup), redesigned Mask/Restore, Redact PDF, PDPA Report, Settings, and
  Audit Log screens, dark mode (system/light/dark) across desktop and popup,
  and a shared design-token sheet.
- Extension support for more chat sites: Gemini, Grok, Perplexity, and
  GLM / Z.ai (in addition to ChatGPT and Claude).
- Redactor fix for edge leaks and gaps in PDF blackout boxes.
- Submission docs (one-pager, form answers) synced with shipped features.

## [2.0.0] - 2026-07-04

- Desktop app: Tauri v2 shell (text mask/restore, redact PDF, PDPA report,
  settings, audit log screens), system tray, global hotkeys
  (Ctrl+Shift+M / Ctrl+Shift+R via clipboard), and a PII-free audit log
  viewer.
- Relicensed to Apache-2.0 and removed PyMuPDF (AGPL): true PDF redaction is
  now flatten-to-image via pypdfium2 + Pillow, PDF text extraction via
  pypdfium2/pdfplumber, and exported text PDFs via reportlab.
- Cross-platform build + release: single-source PyInstaller sidecar build,
  per-OS process kill, a release workflow producing Windows/macOS/Linux
  installers, an auto-updater, and winget/scoop packaging manifests.
- Opt-in WangchanBERTa NER engine (`AIGUARD_NER_ENGINE=wangchanberta`) as a
  higher-recall alternative to the default offline CRF engine.
- Real OCR for scanned PDFs (PaddleOCR, per-page routing, confidence-based
  retry with a `human_review` flag).

## [1.0.0] - 2026-06-27

Initial PSU Future Tech Challenge 2026 submission: the full 8-step pipeline
(ingest & OCR, text cleaning, FP + TB PII detection, pseudonymization, an
in-memory session vault, an AI client with a pre-send leak guard, a reverse
mapper, 3-layer output validation, and export), a CLI (`demo_cli.py`,
`ai_guard.py`), the first FastAPI web API, the PDPA risk report and
re-identification risk scorer, and a Docker Compose demo setup.
