# Roadmap

AI Guard's north star: **maximum adoption of a local-first Thai PII protection
tool** — no cloud, no telemetry, vault never leaves the device. The
competition (PSU Future Tech Challenge 2026) ended at the v2.2.0 poster
presentation; everything below is post-competition, solo-maintained OSS work.

This is a summary. Full reasoning, decision log, and risk analysis:
[`docs/superpowers/specs/2026-07-10-post-competition-longterm-roadmap.md`](docs/superpowers/specs/2026-07-10-post-competition-longterm-roadmap.md).

Ground rules locked 2026-07-10: engineering/quality is the main axis for the
next 3-12 months (not new product features); OSS solo (no PSU/DIIS
partnership dependency); stay unsigned (no code-signing cert — trust comes
from reproducible/verifiable builds instead).

## Horizon 1 — Now (0-1 month): close gaps before promoting

Public Apache-2.0 repo, so close what a security blogger would write about
first.

| # | Item | Status |
|---|---|---|
| 1 | Fix the 3 confirmed recall leaks (Thai-glued PII, `+66` mobiles, per-page PDF routing) | Done |
| 2 | Harden the localhost API (boot token, Host-header check, session TTL) | Mostly done — CORS is a strict allowlist, `TrustedHostMiddleware`, `/api/shutdown` requires a header, sessions have a TTL. **Still open:** a random boot token on general mutating endpoints |
| 3 | Real CI test gate (pytest win+ubuntu, core-only install, cargo test, JS syntax, packaged-exe smoke) | Done |
| 4 | Collision-safe pseudonyms + cross-detector span merge | Done |
| 5 | Single-source version + OSS front door (this doc, `CONTRIBUTING.md`, `SECURITY.md`, `CHANGELOG.md`, `VERSION` + bump/check scripts) | Done |
| 6 | Chrome Web Store submission (privacy policy, listing assets, `_locales`) | Not started |
| 7 | Poster-day momentum (launch posts, measured booth latency) | Not started |

## Horizon 2 — Next (1-3 months): unify + measure

| # | Item | Status |
|---|---|---|
| 8 | Unify web + CLI onto one core (`SessionService`) | Done |
| 9 | Thai PII benchmark corpus + CI recall gate | Partial — synthetic v1 + gold v2 corpora and a 4-way NER strategy comparison exist; no CI recall gate yet |
| 10 | Restructure TB detection (non-overlapping windowing, stop over-mapping DATE/LOCATION) | Not started |
| 11 | Reproducible, verifiable (but unsigned) Windows build | Not started |
| 12 | Publish a Presidio bridge as a PyPI plugin | Not started — kill-listed until a one-page decision doc is written and benchmark work lands |
| 13 | JS/Rust test harness + selector-drift telemetry | Not started |

## Horizon 3 — Later (3-12 months): moat + sustainability

Fine-tuned Thai PII NER model on HuggingFace, Chrome native messaging (drop
fixed-port localhost HTTP), offset-accurate redaction + OCR bake-off
(PaddleOCR vs. Tesseract vs. EasyOCR vs. Typhoon OCR), an on-prem PDPA
deployment tier, publishing the benchmark dataset as a community standard,
and Chrome Web Store + Edge publication once the stack above is unified and
hardened.

## Explicitly out of scope (kill-list)

No cloud/SaaS-hosted version. No mobile app. No multi-tenant/Redis session
store before a real pilot org asks for one. No WangchanBERTa as the *default*
NER engine until its windowing cost is fixed and benchmarked. No public
accuracy/F1 claims before benchmark v1 ships. No hand-written volatile
numbers (test counts, version strings, platform lists) in prose — those live
in machine-readable files (`VERSION`, CI output) and get cited from there,
not typed by hand.

See the linked design doc's "Kill-list" section for the full list and
reasoning.
