# Roadmap

AI Guard's north star: **maximum adoption of a local-first Thai PII protection
tool** — no cloud, no telemetry, vault never leaves the device. The
competition (PSU Future Tech Challenge 2026) ended at the poster presentation;
everything below is post-competition, solo-maintained OSS work.

This is a summary. Full reasoning and the decision log live in
[`docs/decisions/2026-07-17-roadmap-v2-design.md`](docs/decisions/2026-07-17-roadmap-v2-design.md),
which supersedes the ordering in the
[original post-competition roadmap](docs/decisions/2026-07-10-post-competition-longterm-roadmap.md).

Ground rules (2026-07-10, still in force): engineering/quality is the main
axis, not new product features; OSS solo; stay unsigned — trust comes from
verifiable builds, not a paid certificate.

Decisions locked 2026-07-17:

- **GitHub is the only distribution channel this round.** Releases + README.
  No Chrome Web Store, winget/scoop, or PyPI submission until there is a
  signal to justify it.
- **The Rust rewrite is dead, permanently.** No language migration. Detection
  improves on the existing Python stack (Python + ONNX Runtime). Both Rust
  design docs are marked superseded.
- **Re-audit before the next tag.** The earlier "tier 1-6" audit left no
  findings artifact, so it did not count as done; a full re-audit was run and
  its findings live in
  [`docs/decisions/2026-07-19-audit-v2-findings.md`](docs/decisions/2026-07-19-audit-v2-findings.md).

## Phase 1 — Close the next release

The first post-competition release: clean, audited, and proving a release
pipeline that has never run on a real tag.

| Item | Status |
|---|---|
| Core correctness + detection fixes from the first audit pass | Done |
| Full-repo re-audit with a permanent findings artifact | Done |
| Close every critical/high finding | Done — see the findings doc's status table |
| Release-pipeline gates (tag matches `VERSION`; NER model hash pinned; asset set verified before hashing/attesting) | Done |
| Housekeeping (regenerate this file, drop the dead text-cleaner stages, mark the Rust specs superseded, clear the Dependabot action bumps) | In progress |
| Tag the release and review the first real run of `release.yml` | Not started |
| Owner action: enable GitHub private vulnerability reporting | Not started |

The remaining medium/low audit findings are tracked in the findings doc and
are not release blockers.

## Phase 2 — Safety net + front door

Every change after this has a measurement behind it, and a newcomer can
install without asking.

| Item | Status |
|---|---|
| CI recall gate over the benchmark corpora (per-entity-type floors) | Not started — corpora and the NER strategy ADR already exist |
| Playwright live-DOM checks + selector-drift badge for the extension | Not started — the vitest/cargo harness core is done |
| README install-from-Releases in three steps, real screenshots, a real `desktop/README.md` | Not started |

## Phase 3 — Detection quality on Python

| Item | Status |
|---|---|
| ONNX Runtime as an opt-in NER engine, measured against the recall gate | Not started |
| Fine-tune a Thai PII NER model and publish it to HuggingFace | Not started — prerequisites (benchmark, windowing) are done |
| Publish the benchmark dataset as a community standard | Not started |

## Backlog — no date, waiting for a real signal

Chrome Web Store and Edge submission; winget/scoop submission; PyPI publish;
technical blog posts; Chrome native messaging with a token-gated data plane;
a Presidio bridge (still gated on a one-page decision doc); an OCR bake-off;
an on-prem PDPA tier; dark theme for the desktop app and side panel; and the
documented CLI gaps (`run_pipeline()` does not call `audit.py` and drops PDF
word bboxes).

## Explicitly out of scope (kill-list)

No cloud/SaaS-hosted version. No mobile app. No multi-tenant/Redis session
store before a real pilot org asks for one. No WangchanBERTa as the *default*
NER engine until its windowing cost is fixed and benchmarked. No public
accuracy/F1 claims before the benchmark ships. No language migration. No
hand-written volatile numbers (test counts, version strings, platform lists)
in prose — those live in machine-readable files (`VERSION`, CI output) and get
cited from there, not typed by hand.

See the linked design docs' kill-list sections for the full list and
reasoning.
