# Roadmap

AI Guard is an open-source (Apache-2.0) Thai PII detection, anonymization, and
redaction toolkit. It has one product core and two delivery contexts:

1. a local-first desktop/extension/Office product where the PII mapping never
   leaves the user's device; and
2. a hosted service shape where the platform receives the request, AI Guard
   avoids persistence and PII-bearing logs, and downstream provider calls
   receive only masked text.

Development is organized by delivery tracks, not by event dates. Dated,
time-bounded plans (such as the AI for Thai onboarding window) live in
[docs/decisions/](docs/decisions/) and never override this roadmap. Current
truth lives in [docs/project-status.md](docs/project-status.md).

Historical note: earlier versions of this roadmap were numbered Phase 0-4.
Where a decision record references those numbers, Phase 0/1 are the completed
reset-and-acceptance work, Phase 2 corresponds to the hosted platform track,
and Phase 3 corresponds to the detection accuracy track below. Phase 4
(a competition release gate) is retired; release rules live in
[docs/release-process.md](docs/release-process.md).

## Where the project stands

- `v2.5.0` is released with checksums and build provenance. The release
  pipeline (tag, CI, cross-platform builds, attestation, packaging metadata)
  has run end to end on a real tag.
- Product-feature acceptance for the committed scope is complete on the real
  delivery paths: extension, desktop, Office task pane (local acceptance),
  CLI, API, container, and worker emulator. Remaining acceptance items are
  externally blocked platform gates, tracked in
  [docs/project-status.md](docs/project-status.md).
- A detection benchmark exists: a seeded synthetic corpus plus a hand-authored
  gold corpus with a negative (no-PII) slice, scored entity-level,
  character-level, and exact-boundary, with an external LLM baseline. Numbers
  live in generated benchmark reports, not in this file.

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

## Track A - Detection accuracy (current focus)

Goal: improve what the accepted product demonstrably misses, with evidence
that survives being checked.

Ordered so that evaluation integrity comes before tuning:

1. **Lock a blind set before tuning.** Freeze a held-out corpus that is never
   inspected during detector work. Without it, every fix tuned on the gold set
   is unfalsifiable.
2. **Harden the gold set as evidence.** Annotation is currently single-source;
   add a label review/adjudication pass before treating gold-set scores as
   release or CI evidence. Grow underrepresented types as gaps appear.
3. **Fix in impact order:** scorer/boundary defects, structured (FP) misses,
   NAME context coverage, ADDRESS coverage, then false-positive reduction.
   Prefer recall over precision, but keep type labels honest.
4. **Compare engines on the same corpus** before changing any default:
   CRF, WangchanBERTa, union, and routed strategies via the benchmark CLI.
   TNER is a remote service with a narrower label set; it gets a separate,
   qualified comparison on the subset it can express, not a same-table row.
5. **Fine-tune a model only if locked evidence** shows rules and context
   cannot close the remaining high-risk gap. Fine-tuning is an accuracy
   decision.
6. **Evaluate an ONNX (or similar) runtime separately** as an
   inference/deployment decision. It needs output-parity and resource
   evidence, not accuracy claims.

Exit gate: results are reproducible, the blind set has not been tuned against,
and every public claim carries corpus size and limitations. No accuracy number
is copied into volatile prose without a generated source.

## Track B - Hosted platform integration (externally gated)

Goal: replace assumptions with evidence from a real hosting platform. The
first concrete instance is AI for Thai; the design keeps the platform adapter
replaceable so a second platform is a delta, not a rewrite.

- Capture the official job envelope, authentication, registry, retry/ack,
  timeout, payload, logging, network, and resource policies when the platform
  issues them. Record unanswered fields as unknown; never convert assumptions
  into a contract.
- Implement only the transport/configuration delta; core operations stay
  stable and shared with the local product.
- Acceptance on the real platform: first accepted job, Thai UTF-8 integrity,
  secrets handling, duplicate/timeout/malformed/crash/concurrency behavior,
  and a PII honeytoken scan over platform-visible logs.

This track blocks only on the external account/specification. It does not
block Track A or Track C, and its dated commitments live in the
[2026-07-24 execution plan](docs/decisions/2026-07-24-post-v2.5-execution-plan.md),
whose freeze rules apply to that program's release candidate, not to the
repository as a whole.

## Track C - Open-source distribution and sustainability

Goal: make the project usable, verifiable, and contributable without the
maintainer in the room. Standing policies (release discipline, documentation
honesty, PII-free evidence) are enforced by
[docs/release-process.md](docs/release-process.md) and AGENTS.md; this track
lists only decidable deliverables:

- **Store distribution decision.** Decide, per storefront, whether to submit
  the extension to the Chrome Web Store and the packaging manifests to
  winget/Scoop upstreams, accepting the support surface that creates. Listing
  copy and permission justifications are already drafted under
  [docs/store/](docs/store/).
- **Contributor path.** Issue templates, a labeled starter-issue set, and a
  documented benchmark-contribution workflow (how to add gold documents and
  what review they need).
- **Signing decision.** Revisit unsigned-by-design once distribution widens;
  record the outcome either way.

Candidates, not commitments (each needs its own accepted design before any
implementation): a policy-gateway integration contract for other applications,
additional AI providers, and a community annotation effort for the gold
corpus.

## Deferred

- Dashboards, batch orchestration, multi-tenant/shared vaults, and mobile
  apps.
- A default heavyweight NER engine without resource and accuracy evidence.
- Broad OCR expansion beyond the existing optional scanned-PDF path.
- Public benchmark leadership claims.

Security fixes, official platform requirements, and defects in a committed
feature are never deferred by this list.
