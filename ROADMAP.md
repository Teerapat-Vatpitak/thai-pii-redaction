# Roadmap

AI Guard has one product core and two delivery tracks:

1. a local-first desktop/extension product where the PII mapping never leaves
   the user's device; and
2. a hosted AI for Thai service where the platform receives the request, AI
   Guard avoids persistence and PII-bearing logs, and downstream Pathumma calls
   receive only masked text.

The current ordering is deliberate: **make every committed feature work on its
real delivery path first; measure and improve detection accuracy after feature
acceptance**. A benchmark is evidence for a working product, not a substitute
for one.

Current truth lives in [docs/project-status.md](docs/project-status.md). Design
history remains in [docs/decisions/](docs/decisions/), but an old decision record
does not override this roadmap.

## Definition of done for a feature

A feature is not complete merely because its function exists. Before it moves
to Done it must have:

- a working caller-facing path (UI, API, CLI, or queue operation);
- positive, invalid-input, provider-failure, and privacy/log tests appropriate
  to that path;
- a container or packaged-runtime smoke test where that is how users run it;
- documented configuration, trust boundary, limitations, and failure behavior;
- a repeatable demo or acceptance fixture using synthetic PII; and
- no known critical path that returns raw PII in logs or an unintended mapping.

## Phase 0 - Project reset

Goal: make the repository tell one accurate story before building more.

- Establish current-state architecture, feature status, AI for Thai integration,
  and release-process documents.
- Reconcile README, SECURITY, CHANGELOG, packaging docs, and roadmap with the
  code on `main`.
- Separate current documentation from historical ADRs and competition artifacts.
- Record GitHub repository hygiene and branch-protection actions.

Exit gate: a new contributor can identify what is shipped, what is implemented
but awaiting acceptance, what is blocked externally, and what is deliberately
deferred without reading commit history.

## Phase 1 - Feature acceptance before accuracy work

Goal: every feature committed in the proposal and the onboarding demo design
works end to end.

### Local product

- Extension mask/restore on every declared site, including visible fail-closed
  behavior when the composer cannot be updated.
- Desktop text masking, restore, PDF redaction, PDPA report, settings, audit log,
  hotkeys, sidecar lifecycle, and updater path.
- CLI sanitize/report and one full pipeline roundtrip.
- Token and surrogate consistency across turns; session expiry and recovery are
  documented and tested.

### AI Guard for Microsoft 365 (owner-approved feature lane)

- One TypeScript task pane and host-adapter contract, delivered in the fixed
  order Word -> Excel -> PowerPoint on Windows Desktop.
- Word selection Detect/Analyze/Mask/Restore/Pathumma with Preview before Apply,
  stale-selection cancellation, Copy-only mixed formatting, and explicit
  response insertion.
- Excel selected-range masking/restoration that changes text cells only and
  proves every formula remains unchanged.
- PowerPoint API 1.5 selected-text masking/restoration with capability and
  formatting fail-closed behavior; no notes, images, or unselected shapes.
- Node 22 build, mock tests, unified-manifest/version validation, and real-host
  acceptance evidence before the lane is Done.

Local acceptance evidence now records completed synthetic-PII Word, Excel, and
PowerPoint XML-host runs, plus unified Word-manifest acquisition, authoritative
schema validation, and deterministic package verification. The candidate must
continue to describe the unified transport accurately: custom ribbon activation
on the packaged distribution transport has not been independently confirmed,
and this is not a Marketplace or broad Office-distribution claim.

Exit gate for this lane: Word, Excel, and PowerPoint checklist items pass on the
candidate build, then Office and the remaining storefront acceptance gates may
be released together as `2.5.0`. Development does not bump `VERSION`.

### Demo features

- Three-panel playground: detect -> mask -> provider -> restore.
- PDF before/after comparison and redacted-file download.
- Live extension demonstration with a fixed synthetic fixture.
- PII-free Thai PDPA PDF report.
- Prompt-injection signal layer framed and tested as warn-only.

### Platform-facing features

- Detect, sanitize, and analyze operations as the core hosted service.
- Protected Pathumma roundtrip without returning the transient mapping.
- TNER as an explicit opt-in integration, never a silent replacement for the
  offline engine.
- Authentication, safe error responses, PII-free logs, health checks, and a
  replaceable queue/HTTP adapter boundary.
- Resource profile and configuration reference for the actual Docker image.

Exit gate: the acceptance matrix in `docs/project-status.md` contains no
"implemented but unverified" item in the committed scope. Optional OCR/ML extras
may remain optional if their absence and HTTP failure are explicit.

## Phase 2 - Official AI for Thai acceptance

Goal: replace assumptions with evidence from the real platform.

- Capture the official job envelope, authentication, registry, retry/ack,
  timeout, payload, logging, network, and resource policies when the account is
  issued.
- Implement only the platform adapter/configuration delta; keep the core
  operations stable.
- Push the image, boot it, complete the first real job, and verify Thai UTF-8,
  secrets, result delivery, and error behavior.
- Run duplicate, timeout, malformed-input, crash-recovery, payload-limit, and
  concurrent-job acceptance cases.
- Run a PII honeytoken scan over application and platform-visible logs.

Exit gate: an accepted platform job plus a repeatable soak with no crash,
duplicate side effect, mapping export, or PII-bearing log.

The account/spec delay is an external blocker only for the official adapter and
acceptance. It does not block the emulator, feature tests, docs, image, resource
measurement, or demo preparation.

## Phase 3 - Benchmark and detection accuracy

Goal: improve what the accepted product demonstrably misses.

- Freeze a synthetic, document-like development corpus and a separately locked
  blind corpus.
- Measure type-aware recall/precision, character coverage, exact boundaries,
  latency, and memory for each supported engine.
- Fix in this order: scorer/boundaries, structured misses, NAME context,
  ADDRESS coverage, then false positives.
- Compare CRF, TNER, WangchanBERTa/union, and any future ONNX path on the same
  corpus before changing a default.
- Fine-tune a model only if the locked evidence shows rules/context cannot close
  the remaining high-risk gap.

Exit gate: results are reproducible, the blind set has not been tuned against,
all public claims include corpus size and limitations, and no accuracy number is
copied into volatile prose without a generated source.

## Phase 4 - Competition release and presentation

Goal: ship one candidate that the demonstration, documentation, and platform all
describe identically.

- Freeze features; only blocker and security fixes enter the candidate.
- Prepare a release PR: version bump, changelog section, full CI, Docker smoke,
  packaged-runtime smoke, and release notes.
- Tag the exact green commit; never move or reuse a published tag.
- Verify installers, signatures, `SHA256SUMS`, and build attestations before the
  draft release is published.
- Update packaging manifests only after the release exists.
- Rehearse a fixed live demo and keep an offline fallback plus video.

The next tag is chosen by delivered scope, not by elapsed time: additive
platform/product capability is a minor release, compatible fixes are a patch,
and a breaking public contract is a major release. See
[docs/release-process.md](docs/release-process.md).

## Deferred until the four gates above

- New providers, dashboards, batch orchestration, multi-tenant/shared vaults,
  mobile apps, and any storefront not explicitly approved above.
- A default heavyweight NER engine without resource and accuracy evidence.
- Broad OCR expansion beyond the existing optional scanned-PDF path.
- Public benchmark leadership claims or a community dataset launch.
- Package-store submissions that create a support surface before the candidate
  is stable.

Security fixes, official platform requirements, and defects in a committed
feature are never deferred by this list.
