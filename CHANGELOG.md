# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).
The current version lives in [`VERSION`](VERSION) — see `scripts/check_version.py` /
`scripts/bump_version.py` for how every other version-bearing file stays in sync.

Entries below v2.2.0 are a coarse backfill from git history, not a per-commit
log — see `git log` for full detail on any release.

## [Unreleased]

### Added

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

### Fixed

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
