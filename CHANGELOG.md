# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).
The current version lives in [`VERSION`](VERSION) — see `scripts/check_version.py` /
`scripts/bump_version.py` for how every other version-bearing file stays in sync.

Entries below v2.2.0 are a coarse backfill from git history, not a per-commit
log — see `git log` for full detail on any release.

## [Unreleased]

## [2.3.0] - 2026-07-20

First post-competition release. Its headline is not a feature: a full-repo
audit found — and this release closes — six ways PII could leak or be restored
to the wrong person, several of which the product's own guarantees depended on.
Findings and evidence: `docs/superpowers/specs/2026-07-19-audit-v2-findings.md`.

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
