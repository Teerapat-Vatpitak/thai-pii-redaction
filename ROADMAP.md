# Roadmap

AI Guard is an open-source (Apache-2.0) Thai PII detection, anonymization, and
redaction toolkit. It has one product core and two delivery contexts:

1. a local-first product — browser extension, Windows desktop app, and
   Microsoft 365 add-in — where the PII mapping never leaves the user's
   device; and
2. a hosted service shape where the platform receives the request, AI Guard
   avoids persistence and PII-bearing logs, and downstream provider calls
   receive only masked text.

This document answers one question: **what gets built next, in what order, and
what is the gate**. It is not the code map ([CLAUDE.md](CLAUDE.md)) and it is
not the record of what is finished
([docs/project-status.md](docs/project-status.md)). Keeping the three separate
is deliberate — when each file carried a little of all three, they drifted and
told different stories.

Development is organized by delivery tracks, not by event dates. Dated,
time-bounded plans (such as the AI for Thai onboarding window) live in
[docs/decisions/](docs/decisions/) and never override this roadmap.

Historical note: earlier versions of this roadmap were numbered Phase 0-4.
Where a decision record references those numbers, Phase 0/1 are the completed
reset-and-acceptance work (with the Office remainder below), Phase 2
corresponds to the hosted platform track, and Phase 3 corresponds to the
detection accuracy track. Phase 4 (a competition release gate) is retired;
release rules live in [docs/release-process.md](docs/release-process.md).

## Where the project stands

- `v2.5.0` is released with checksums and build provenance. The release
  pipeline (tag, CI, cross-platform builds, attestation) has run end to end on
  a real tag.
- Feature acceptance on the real delivery paths is complete for the extension,
  desktop app, CLI, API, container, and demo playground. The Microsoft 365
  add-in is the one storefront still Acceptance pending: several host
  scenarios and the packaged unified-manifest activation run remain open (see
  below).
- A detection benchmark exists: a seeded synthetic corpus plus a hand-authored
  gold corpus with a negative (no-PII) slice, scored entity-level,
  character-level, and exact-boundary, with an external LLM baseline. Numbers
  live in generated benchmark reports, not in this file.
- The AI for Thai participant guide has arrived and fixes the deployment shape
  (HTTP/FastAPI behind a reverse proxy, Compose from GitLab `main`). The
  deployment project and the exact public route/auth contract are still
  pending; the queue worker is retained only as a local failure/retry
  emulator, not the official delivery path.

The source tree keeps live product code, required synthetic/reproducibility
inputs, and privacy-reviewed evidence. Local environments, runtime logs,
generated reports, model caches, and build output are deliberately ignored.
`blind-v1` remains only as a closed historical audit trail after its six reveals;
it is not a current blind evaluation set. Any future blind evaluation requires
a newly frozen `blind-v2` dataset under the same protocol.

## Definition of done for a feature

A feature is not complete merely because its function exists. Before it moves
to Done it must have:

- a working caller-facing path (UI, API, CLI, or hosted operation);
- positive, invalid-input, provider-failure, and privacy/log tests appropriate
  to that path;
- a container or packaged-runtime smoke test where that is how users run it;
- documented configuration, trust boundary, limitations, and failure behavior;
- a repeatable demo or acceptance fixture using synthetic PII; and
- no known critical path that returns raw PII in logs or an unintended mapping.

## Outstanding feature acceptance — Microsoft 365 add-in

The Office lane receives only blocker/security fixes and acceptance evidence
until new scope is explicitly approved. Still open, per the
[acceptance checklist](docs/acceptance/README.md):

- the remaining local host-functional scenarios (Word table and
  missing-key/provider/expired-session cases; Excel changed-value/formula
  cancellation and Pathumma Copy-only; PowerPoint full unselected-content
  isolation, missing API 1.5, and Pathumma Copy-only); and
- one real-host run proving the exact packaged three-host unified manifest
  activates its ribbon/task pane. Schema validation, acquisition metadata, and
  local XML transports do not close that distribution gate.

## Track A - Detection accuracy (current focus)

Goal: improve what the accepted product demonstrably misses, with evidence
that survives being checked.

Ordered so that evaluation integrity comes before tuning:

1. **Keep the blind set locked during tuning.** `blind-v1` is frozen and its
   reveal budget is now EXHAUSTED at 6/6 (both final reveals owner-approved,
   2026-08-02): reveal 5 scored the gov-form campaign after it landed (CRF —
   blind F2 flat within CI, character coverage and exact-boundary recall up,
   negative slice identical) and reveal 6 re-certified the fine-tuned opt-in
   engine on the same code (F2 0.914 to 0.916, exact and coverage up,
   negative slice identical). Tuning never touched the set. Any future blind
   measurement requires authoring and freezing a blind-v2 under the same
   protocol — a deliberate, owner-approved undertaking, not a side effect.
2. **Separate automatic and human evidence.** Gold v4 already has its recorded
   two-reviewer adjudication. Government-form synthetic expectations are
   developer-authored and not independently adjudicated. Independent annotation
   and adjudication of broader real-form content are deferred by the owner;
   automatic synthetic results must not be described as general accuracy.
3. **Fix in impact order:** scorer/boundary defects, structured (FP) misses,
   NAME context coverage, ADDRESS coverage, then false-positive reduction.
   Prefer recall over precision, but keep type labels honest.
   Worked end to end in the 2026-08-04 weakness-closure campaign
   ([record](docs/decisions/2026-08-04-weakness-closure-campaign.md)): an
   enumerated inventory drove four implementation waves, and a four-lens
   adversarial review then found seven realistic sentences the corpus could
   not see, all of them from span-*removing* mechanisms. What remains on this
   rung is owner-gated rather than unfinished — the STUDENT_ID label-honesty
   scope question, generic administrative dates, and a gold self-contradiction
   in `ng06` — and each is recorded in that document. The whole ladder
   was worked in the 2026-08-04
   [weakness-closure campaign](docs/decisions/2026-08-04-weakness-closure-campaign.md),
   driven by an enumerated inventory rather than a sample; the items it left
   open are owner calls (STUDENT_ID exam-roster scope, salutation addressees,
   generic administrative dates, one gold self-contradiction) and are listed
   in that record. Its structural outcome — a span-removing mechanism may
   consume only closed-lexicon evidence, because trimming unmasks — applies to
   any future rule of that shape.
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
7. **Extend coverage to real Thai government documents.** The current
   adjudicated accuracy corpus is self-authored prose; real forms are tables
   with checkboxes, stamps, and fields the 11-type scheme never adjudicated.
   Phase 1 artifacts:
   `docs/research/gov-doc-coverage.md` (sampling frame),
   `docs/research/gov-doc-policy-ontology.md` (per-field policy draft), and
   `benchmark/probe_document.py` (six-measurement instrument). The owner
   approved Phase 2 downloads on 2026-07-31. Source and sanitized-artifact
   hashes are pinned for three official blanks, and a deterministic builder
   creates nine inputs (three modalities each); raw downloads are not committed.
   The local runner now covers digital plus all six OCR inputs. Strict gates
   cover route/OCR, extraction, pixel coverage, residual PII, and declared
   decoy extraction; detection and type results are telemetry. It also checks
   unique alignment and evidence provenance. The runner is verified; its
   privacy gate was red at the
   [2026-07-31 dated run](docs/acceptance/2026-07-31-government-form-synthetic-run.md)
   and passed green 9/9 on the 2026-08-01 branch rerun, detailed next.
   That failed gate's cause was not what it first looked like: near-miss OCR
   reads were already tolerated, and "an OCR read one character off is
   treated as absent" was not why values leaked. Investigation found four
   detection-side mechanisms instead: a degenerate whole-chunk CRF span
   silently dropped on an unmapped label; `_name_hygiene`'s head-keep rule
   losing real names to a label-first OCR line order; name shapes gated on a
   space an OCR read had deleted; and a corrupted duplicate of a structured
   value from the OCR retry merge leaking on the text path — a gap the
   original two-gap framing never named. All four closed 2026-08-01/02
   (commits 76eb9c4..60955b6) with zero acceptance-gate or threshold edits;
   the strict gate passed green for the first time on the branch's
   acceptance rerun. See the corrected investigation, fixes, and rerun
   results in the 2026-08-02 addendum to `docs/research/gov-doc-phase2.md`.
   ท.ร.6 had no public blank download and its declared backup คร.1 is used.
   Physical scans, handwriting, independent real-form annotation, and the
   มาตรา 26 scope question remain open.

Exit gate: results are reproducible, the blind set has not been tuned against,
and every public claim carries corpus size and limitations. No accuracy number
is copied into volatile prose without a generated source.

## Track B - Hosted platform integration (externally gated)

Goal: adapt the accepted core to the official HTTP delivery path and replace
the remaining assumptions with platform evidence. The first concrete instance
is AI for Thai; the adapter stays replaceable so a second platform is a
delta, not a rewrite.

The participant guide fixes the deployment shape: FastAPI behind a same-origin
reverse proxy whose public `/api/...` path reaches an unprefixed backend
route, Compose deployed from GitLab `main`, loopback-only host publication, an
unprefixed `/health`, masked CI variables, bounded log rotation, and CPU-only
resource limits. GitLab group access (Maintainer) and separate LLM service
credentials have arrived.

The deployment is built as a **separate port repo** (`aiguard-aift`), keeping
this repo local-first: a vendored core slice + nginx adapter (prefix re-add,
six-endpoint allowlist, key injection) + OCR-baked image, with a stateless
roundtrip against thaillm-8b. It passed a full local Docker phase — the ก-ฌ
checklist, fail-loud/503 failure modes, and a service-level soak — recorded in
the [tokenmind detector + port ADR](docs/decisions/2026-07-28-tokenmind-detector-and-aift-port.md)
and the port repo's `docs/evidence/`. Pushing to GitLab and the real platform
run are owner-gated; the exact public operation/authentication contract plus
LLM protocol and policy still need confirmation.

- Capture the remaining official answers: project/template ownership, public
  operations, caller authentication, payload/timeout/concurrency limits,
  outbound network policy, LLM protocol/quota/logging policy, and acceptance
  owner/evidence. Record unanswered fields as unknown; never convert
  assumptions into a contract.
- Implement only the hosted adapter/configuration delta: stripped path prefix
  and `root_path`, unprefixed health check, trusted-host policy, a deliberately
  allowlisted/authenticated public surface, and platform Compose/CI/logging.
  Keep detection, masking, vault, provider, and restoration logic unchanged.
- Obtain or initialize the approved deployment project, push the exact
  candidate through the supplied GitLab path, boot it, and verify Thai UTF-8,
  secret injection, health, responses, and safe failures.
- Run malformed input, timeout, payload-limit, concurrent request, restart,
  and duplicate-side-effect cases. Test retry ownership only if the official
  HTTP contract defines retries.
- Complete one protected LLM roundtrip and scan application plus
  platform-visible logs with synthetic honeytokens.

Exit gate: the accepted HTTP service plus a repeatable soak with no crash,
duplicate side effect, mapping export, credential exposure, or PII-bearing
log.

The remaining external blockers are the deployment project, confirmed support
channel, and unanswered contract fields. They do not block Track A, Track C,
documentation, adapter seam tests, the provisional worker emulator, or
image/resource measurement. Dated commitments for this program live in the
[2026-07-24 execution plan](docs/decisions/2026-07-24-post-v2.5-execution-plan.md),
whose freeze rules apply to that program's release candidate, not to the
repository as a whole.

## Track C - Open-source distribution and sustainability

Goal: make the project usable, verifiable, and contributable without the
maintainer in the room. Standing policies (release discipline, documentation
honesty, PII-free evidence) are enforced by
[docs/release-process.md](docs/release-process.md) and AGENTS.md; this track
lists only decidable deliverables:

- **Store distribution decision.** Decided 2026-07-29 and revised the same day
  ([record](docs/decisions/2026-07-29-store-distribution-and-signing.md)): no
  package manager at all. Installers are published as release assets and linked
  for direct download, so the winget and Scoop manifests were removed rather
  than submitted. The Chrome Web Store stays on hold until a reviewer has a
  workable path to a running backend; listing copy and permission
  justifications stay ready under [docs/store/](docs/store/).
- **Contributor path.** Issue forms (wrong detection result, bug, proposal,
  benchmark document), a pull-request template, and the
  [benchmark-contribution workflow](docs/benchmark-contribution.md) are in
  place; each form makes the project's non-negotiables explicit at filing time
  (fabricated data only, private reporting for vulnerabilities, the blind set
  untouched). What remains is a labeled starter-issue set drawn from real open
  work rather than invented tasks.
- **Signing decision.** Decided 2026-07-29 (same record): stay unsigned. The
  cheapest managed option (Azure Artifact Signing) is not open to developers
  based in Thailand, a CA certificate costs a few hundred dollars a year for a
  project with no revenue, and since August 2024 no certificate class clears
  SmartScreen on first download anyway — reputation is earned by download
  history either way. Verifiability keeps carrying the trust: `SHA256SUMS` plus
  build provenance on every release. The record lists what would reopen it.

Candidates, not commitments (each needs its own accepted design before any
implementation): a policy-gateway integration contract for other applications,
additional AI providers, and a community annotation effort for the gold
corpus.

## Track D - PDPA compliance surface

Goal: turn what the product already does into artifacts an organization can put
in front of a regulator. Each item is a separate design; none of them may
introduce retention the rest of the product refuses to have.

Ordered as agreed, and deliberately narrow — a compliance feature that stores
more than the tool needs would trade the project's central promise for a
document.

1. **Processing receipt (section 39).** Delivered 2026-07-29
   ([record](docs/decisions/2026-07-29-processing-receipt.md)): a per-run slip
   rather than a cumulative register, verified by rerunning the input and
   comparing digests rather than by a signature. Core plus a CLI that both
   issues and verifies, plus a Thai PDF. No API endpoint in v1.
2. **Breach assessment mode.** Delivered 2026-08-01
   ([record](docs/decisions/2026-08-01-breach-assessment.md)): scan a set of
   leaked documents and summarize type, count and affected-subject estimates,
   so a controller can draft the 72-hour PDPC notification from evidence
   rather than memory. Core plus a CLI verb, plus a Thai PDF. No API endpoint
   in v1.
3. **DSAR helper.** Delivered 2026-08-01
   ([record](docs/decisions/2026-08-01-dsar-helper.md)): locate which of a set
   of documents the controller already holds mention a data subject, so the
   controller can serve a มาตรา 30 access request from the located files
   themselves rather than searching by hand. The retention question that
   blocked this item was answered by the owner — in-memory for the run only,
   nothing beyond the requested artifacts written to disk. Core plus a CLI
   verb, plus a Thai PDF. No API endpoint in v1.
4. **Standards mapping.** Delivered 2026-08-01
   ([docs/standards-mapping.md](docs/standards-mapping.md)): a correspondence
   document, not a conformance claim. Grounded in the sources actually
   accessible — a publicly served ISO/IEC 20889 preview (complete terminology
   clause plus the full table of contents; clauses 8-12 cited by title only)
   and the full 103-page มรด. 6:2566 PDF from the DGA standards site. Reading
   the latter end to end established that it defines no de-identification
   technique at all (and does not reference ISO/IEC 20889), so the mapping is
   terminology/technique-family level for ISO and governance-practice level
   for มรด., with every non-claim listed explicitly. This item is a document,
   so the exit gate below applies in its documentation form: the "caller-facing
   path" is the published document, and the tests are the claims having been
   adversarially checked against the sources and the codebase — there is no
   runtime path and no code to test.

Exit gate for each item: a caller-facing path, tests covering the failure and
privacy behavior, and no artifact that carries a personal-data value.

## Deferred

- Dashboards, batch orchestration, multi-tenant/shared vaults, and mobile
  apps.
- A default heavyweight NER engine without resource and accuracy evidence.
- Broad OCR expansion beyond the existing optional scanned-PDF path.
- Public benchmark leadership claims.

Security fixes, official platform requirements, and defects in a committed
feature are never deferred by this list.
