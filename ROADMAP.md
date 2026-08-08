# Roadmap

AI Guard is an open-source (Apache-2.0) Thai PII detection, anonymization, and
redaction toolkit. It has one product core and two delivery contexts:

1. a local-first product — browser extension, Windows desktop app, and
   Microsoft 365 add-in — where the canonical PII mapping is intended to remain
   in backend memory on the user's device; and
2. a hosted service shape where the platform receives the request, AI Guard
   targets no deliberate mapping/raw-PII persistence or PII-bearing logs, and
   downstream provider calls are intended to receive only verified masked
   text. The current generic hosted candidate is mixed-state, and its audit
   transport and retention are not accepted. Current source rejects structured,
   text-based, and detector-independent residuals before HTTP/worker provider
   calls; packaged, live-provider, and official-platform acceptance of that
   change remains open.

This document answers one question: **what gets built next, in what order, and
what is the gate**. It is not the code map ([CODEMAP.md](CODEMAP.md)) and it is
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
- Dated feature acceptance exists for the exact extension, desktop, CLI, API,
  container, and demo candidates named in those records. It remains historical
  evidence for those artifacts, not acceptance of later hardening changes.
  Those candidates predate the current outbound fail-closed policy, so their
  packaged, storefront, and live-provider paths must be rerun before the new
  source behavior is promoted.
  The Microsoft 365 add-in remains Acceptance pending: several host scenarios
  and the packaged unified-manifest activation run remain open (see below).
- A detection benchmark exists: a seeded synthetic corpus plus a hand-authored
  gold corpus with a negative (no-PII) slice, scored entity-level,
  character-level, and exact-boundary, with an external LLM baseline. Numbers
  live in generated benchmark reports, not in this file.
- The official AI for Thai participant guide fixes the deployment shape for
  `team08`: frontend/API ports `20070/20071`, `/api` prefix stripping,
  unprefixed `/health`, template-derived Compose CI from GitLab `main`,
  loopback publication, per-service limits, bounded logs, masked `APP_*`
  secrets, and no-SSH operations. The accepted 2026-07-28 decision selects the
  separate sibling port; main's strict-v2 `app.hosted` remains a generic
  reference, not a second deployment candidate. The sibling has no independent
  service-version source: its public unversioned and `/v1` aliases proxy strict
  contract 2. Business operations
  are product-owned because the guide does not prescribe them. The accepted
  [caller-auth decision](docs/decisions/2026-08-07-aift-caller-authentication.md)
  keeps static/health public and gates every business route with a short-lived
  signed cookie; proxy-to-core and provider secrets remain separate. The
  sibling now pins current core `8c6efef`, preserves its public `/v1` aliases
  while injecting strict contract 2 internally, and returns minimized
  projections. Immutable port commit `e075ca4` passed exact provider-free local
  BusyBox check/deploy, and independent security/compatibility review found no
  remaining static blocker. Live Tokenmind/soak evidence predates that final
  commit. The exact one-page OCR route passes but reaches the 6 GiB core limit
  in 221 seconds, so the configured 20-page/300-second surface is not
  deploy-ready. Credential rotation, the PDF capability decision, the
  owner-gated first GitLab push, and official platform acceptance remain.
  The queue worker is retained only as a local failure/retry emulator, not the
  official delivery path.

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

## Security hardening campaign (active owner-approved exception)

Track A detection remains the declared normal product priority. The owner has
approved this bounded privacy/security/correctness campaign as an explicit
exception; it does not mean Track A is complete. Work proceeds as small,
reviewed, independently revertible integration units in this order:

1. **Preserve the clean baseline and correct current truth — delivered at
   `304b071`.** Record the `93a7108` gates without promoting historical
   evidence or changing runtime behavior.
2. **Make local sanitize transactional — delivered in current source.** A
   failed sanitize publishes no new session, mapping, session-vault audit
   entry, ordinal, session timestamp, or eviction. One safe operation-ID-only
   `prepared` or `blocked` process-attempt record may exist; it carries no live
   session authority or mapping material. Known-session expiry is lifecycle
   disposal outside rollback, and displaced-vault cleanup after publication
   is best effort. Current main-API source
   process-audit callers use fresh operation IDs; the legacy audit field remains
   named `session_id`. Phase 7 later made known-session expiry eager at the
   exact TTL boundary; it remains lifecycle cleanup outside transaction
   rollback.
3. **Harden vault seeding and audit — delivered in current source.** New seeds
   use opaque `seed:<uuid4>` IDs and one structural `seed` audit row. Replaying
   an identical pair returns the existing immutable record without changing
   lookup, audit, or access state; a conflicting original fails with a
   constant value-free error. The safe `SEEDED` provenance marker remains
   internal, and `clear()` drops vault-owned references rather than claiming to
   zeroize immutable strings.
4. **Decide HTTP contract v2 in an ADR — delivered in current source.** The
   [accepted decision](docs/decisions/2026-08-05-http-contract-v2.md) moves the
   main API directly to strict response DTOs with no explicit mapping fields;
   the repository/deployment inventory found no evidenced external v1
   consumer, while unknown consumers remain possible. Clients still
   necessarily handle submitted and returned text. The worker's internal
   envelope remains version 1. Runtime implementation is recorded in item 5.
5. **Fail closed on outbound residuals and cut over server plus first-party
   clients atomically — delivered in current source; fresh package/host
   acceptance remains open.** The shared core blocks structured FP findings,
   text-based TB findings, detector-independent contiguous runs of six or more
   digits, and missing replacement records. Caller-seeded pseudonyms are reused
   only when nonempty, original-free, absent from the current source text, and
   free of independent FP/TB/digit residual signals; token reuse also requires
   the product token shape for the detected data type.
   Token mode now combines a non-secret random vault-generation tag with an
   unpredictable nonce for each newly minted token. Regressions keep stale and
   guessed tokens foreign in the exercised drop, restart, expiry, eviction, and
   same-session preplay cases. The random 64-bit tag plus approximately 94-bit
   nonce makes accidental identity reuse and future-token preplay
   computationally impractical; this is probabilistic separation, not
   impossibility. Unknown token text remains unchanged and becomes a count-only
   unsafe warning. The accepted
   [identity decision](docs/decisions/2026-08-06-session-namespaced-token-identity.md)
   adds no wire field or credential. It is implemented in current source; the
   exact-candidate sanitize performance gate is red, its measured security
   trade was owner-accepted on 2026-08-06, and package/real-host acceptance
   remains pending.
   CLI, HTTP/hosted roundtrip, and worker roundtrip now use one shared provider
   orchestration layer. It rescans immediately before each actual invocation,
   reuses one immutable masked text, caps execution at three 60-second
   attempts, and applies fixed one- then two-second delays only for timeout,
   network, HTTP 429, and HTTP 5xx failures. Tokenmind performs one HTTP request
   per invocation and no provider owns retries. Runtime and first-party clients
   now use strict HTTP v2 with exact
   response projection, sanitized-space highlights, safe errors, and separate
   control/data-plane health capabilities. The worker envelope remains version
   1. The source gates do not establish packaged Desktop, real-browser,
   HTTPS-proxy/Office-host, or live-provider acceptance.
6. **Verify packaged-backend and Office development composition — delivered as
   automated local transport evidence.** The Windows runner builds the Office
   production bundle and packaged sidecar, boots the sidecar headlessly,
   validates strict-v2 health, token sanitize, and reidentify directly, and
   repeats the API flow through the Office HTTPS development proxy when valid,
   already-trusted development certificate files are present. The dated run
   left those files unchanged. It did not execute Office JavaScript or the
   built bundle, open an Office host, sideload a manifest, provision trust, call
   a provider, release, or deploy. All eight real-host/package checks remain
   open.
7. **Make request-driven lifecycle behavior eager and finish authenticated
   disposal — integrated into main; post-merge CI green.** The first
   independent merge review of `f968833` found six
   blockers: failed-restore retention refresh, competing service/vault TTL
   decisions, noncanonical authorization replay identity, pre-lock-only
   authorization expiry, bearer-like access-log disclosure, and contradictory
   status documentation. The corrective commit makes `SessionService` the sole
   managed TTL authority, refreshes restore access only after success, accepts
   only canonical authorization text, performs final expiry/replay/disposal
   atomically under the lifecycle lock, and redacts the disposal route before
   launcher/Desktop forwarding while retaining safe access logs. One
   backend-owned earliest-deadline timer expires idle sessions at the exact TTL
   boundary without a later request. Expiry, explicit disposal, capacity
   eviction, shutdown, and lifecycle failures use the same idempotent
   session-scoped cleanup. The boot token and derived authority are not exposed
   to JavaScript clients. Corrective commit `b9c0b745` passed branch CI 11/11,
   but its post-CI review found an eager-callback fail-closed gap and stale
   pre-push status text. Follow-up `6cd109d1` closes both with deterministic
   evidence and passed its branch CI 11/11. Final branch head `2e147481` passed
   11/11 jobs, and the two read-only lifecycle/concurrency and
   authentication/secrecy reviewers found no blocker on that exact head. Main
   integrated the branch with history-preserving merge `eb0c45c`; post-merge
   CI passed 11/11 and cross-platform smoke passed 2/2. Broker-backed Extension
   and Desktop disposal remains Phase 8 work. Office is outside broker v1 under
   the accepted native-broker ADR, and all eight Office real-host/package gates
   remain open under the unchanged web-add-in architecture.
8. **Converge longer-term choke points — in progress.** The first separately
   reviewable unit is integrated and implements the locked explicit-TNER
   policy: a failed request or incomplete ordered token stream aborts the whole
   operation with bounded `ner_unavailable` or `ner_incomplete` metadata, while
   the shared BIO/chunk engines (`thainer`, WangchanBERTa, and union) retain
   structural skip-and-continue behavior. The separate fine-tuned offset
   engine is outside this change. Automated coverage spans core, local session,
   stateless, HTTP v2, hosted, PDF, and worker-v1 call paths. Exact branch head
   `a7e388257` passed all 11 CI jobs after infrastructure-canceled jobs were
   rerun; fresh live TNER response/mapping evidence remains open. The second
   separately reviewable unit converges protected provider attempts across
   CLI, HTTP/hosted, and worker on the locked shared retry and outbound-policy
   contract. Tokenmind now makes one HTTP request per invocation, so no stacked
   retry path or provider-controlled delay remains. Automated source evidence
   covers attempt limits, per-attempt timeouts, retry classification, immutable
   masked input, rollback/stateless boundaries, safe errors, v2/v1 wire
   compatibility, and unchanged hosted allowlisting. Fresh live-provider,
   packaged, real-host, and official-platform acceptance remains open. The
   accepted
   [native-broker ADR](docs/decisions/2026-08-07-native-broker.md) selects a
   shared per-user named-pipe/filesystem-UDS broker, Chrome native-messaging
   adapter, allowlisted Tauri bridge, broker-prebound authenticated loopback
   backend, explicit unsigned-distribution limits, and maintenance-only global
   lifecycle. Slice 1 protocol definition and cross-language conformance are
   complete in source: one machine policy drives strict
   Python/Rust framing, mandatory hello, immutable negotiated authority,
   closed roles/operations and nested result schemas, safe errors, measured
   limits/deadlines, and non-replay semantics. Independent exact-index review
   passed with no unresolved finding, and reviewed implementation commit
   `4ada40d203f98039c93b78d6fb0ab2a14df91f2d`
   [passed all 11 branch CI jobs](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31216048119).
   Slice 2 is now implemented as a local source candidate: a single on-demand
   broker owns a protected Windows named pipe or filesystem UDS, binds OS peer
   identity and strict package-consistency evidence to the claimed role,
   prebinds and supervises one private authenticated Python backend, and serves
   only broker health plus maintenance-only drain/stop. Windows uses an
   explicit current-logon-SID DACL, kernel PID/token inspection, a named mutex,
   and an atomic kill-on-close Job assignment. macOS/Linux use `0700`/`0600`
   filesystem protections, a held lock, peer credentials, stable process
   identity, and substitution-safe cleanup. Local Windows and Linux runtime
   gates and independent security review pass; macOS runtime evidence and exact
   branch CI are still pending at this checkpoint. No broker data plane,
   session ownership/disposal, storefront cutover, Chrome/Tauri/Office change,
   packaging migration, or installed acceptance exists. Office remains
   outside broker v1. The third
   separately reviewable unit adds authoritative PDF source-to-box intervals:
   pdfplumber, pdfium, and retained OCR fragments carry exact provenance into
   the page-joined extraction text, and redaction selects boxes only by
   interval intersection. Repeated-value, cross-page, overlapping-fragment,
   Thai combining-character, normalization, missing-provenance, negative-pixel,
   flattening, and fixed-error regressions are automated. Optional live OCR,
   physical scans, handwriting, hosted PDF resources/timeouts, and real-host
   acceptance remain open.

The outbound-policy, HTTP-v2 client, and token-identity source changes plus the
future broker-backed client lifecycle/disposal, explicit-TNER,
provider-orchestration, and PDF-offset changes each invalidate carry-forward
evidence only for their affected paths. Fresh automated, packaged, real-host,
live-provider, or official-platform evidence must match the strength of the
changed path. Shared provider orchestration has current-source automated
evidence, while its packaged, live-provider, real-host, and official-platform
recertification remains open. `VERSION` remains
`2.5.0` during development; a release containing the breaking HTTP contract is
expected to be prepared as `3.0.0`, but release work requires separate
authorization.

The browser in-page flow cannot guarantee that provider page code did not
observe raw text typed into its composer before Mask. This campaign can protect
AI Guard-controlled calls and place reviewed masked text into the composer; it
does not intercept or attest the provider page's model request or erase that
earlier DOM boundary. Requiring extension-side-panel entry for all raw text
would change product direction and requires a separate owner decision.

The separate sibling `aiguard-aift` port is outside this campaign and must not
be described as a migration or independent release line of the local product
API. It has no separate service-version source. Its public unversioned and
`/v1` aliases remain port-owned, while the vendored current core uses strict
contract 2 and minimized projections behind nginx. The accepted
2026-08-07 ADR gates business routes with a short-lived signed caller cookie;
the internal shared-key injection still authenticates nginx to core rather
than the caller. Immutable commit `e075ca4` passed exact provider-free local
BusyBox check/deploy and independent review. Dated working-tree evidence covers
live Tokenmind, fake/live soak, and OCR correctness, while the exact PDF
resource probe is red at 221 seconds and the 6 GiB limit. Credential rotation,
the PDF capability decision, official AI for Thai deployment, and
live-platform acceptance remain open.

## Outstanding feature acceptance — Microsoft 365 add-in

The Office lane receives only blocker/security fixes and acceptance evidence
until new scope is explicitly approved. Still open, per the
[acceptance checklist](docs/acceptance/README.md):

- the remaining local host-functional scenarios (Word table and
  missing-key/provider/expired-session cases; Excel changed-value/formula
  cancellation and Pathumma Copy-only; PowerPoint full unselected-content
  isolation, missing API 1.5, and Pathumma Copy-only); and
- after the remaining host-functional checks pass, one real-host run proving the
  exact promoted three-host unified manifest activates its ribbon/task pane.
  The release manifest remains Word-only until then; schema validation,
  acquisition metadata, and local XML transports do not close that distribution
  gate.

## Track A - Detection accuracy

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
   A WSL rerun at exact commit `ded67d3` on 2026-08-04 completed 9/9 with zero gate failures
   (45/45 removed, zero exposed or unmeasurable, residual OCR measured 9/9,
   and decoy controls clean). The runner conservatively labeled its summary
   `functional_pass_repository_dirty` during the WSL run; immediately after,
   both Windows and WSL Git status were clean at that commit. This is
   historical exact-candidate evidence; the current HTTP-v2/PDF composition has
   not rerun it. It closed that candidate's functional evidence gap, but not the runtime limitation:
   the WSL run took about 34 minutes and peaked near 8 GiB RSS, the Windows
   run still has a 30-minute timeout, and an earlier Windows access violation
   remains recorded in the phase-2 addendum.
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

The official participant guide fixes the deployment shape for `team08`:
standard frontend `/` on host port `20070`, backend `/api/` on `20071`, prefix
stripping to an unprefixed backend route, unprefixed `/health`,
template-derived Compose CI deployed from GitLab `main`, loopback-only host
publication, masked `APP_*` variables, `50m` times three log rotation,
per-service CPU/memory limits under an adjustable approximately 13 GiB team
budget, and no-SSH operations. GitLab group access (Maintainer) and separate
LLM service credentials have arrived.

The accepted 2026-07-28 deployment decision uses a **separate port repo**
(`aiguard-aift`), keeping this repo local-first: a vendored core slice + nginx adapter (prefix re-add,
six-endpoint allowlist, key injection) + OCR-baked image, with a stateless
roundtrip against thaillm-8b. It passed a full local Docker phase — the ก-ฌ
checklist, fail-loud/503 failure modes, and a service-level soak — recorded in
the [tokenmind detector + port ADR](docs/decisions/2026-07-28-tokenmind-detector-and-aift-port.md)
and the port repo's `docs/evidence/`. That historical soak predates F09. The
new candidate vendors `8c6efef`, injects strict HTTP contract 2 behind its
existing public aliases, and minimizes roundtrip results. Immutable port commit
`e075ca4` passed exact local BusyBox `check` in 28.0 seconds and provider-free
`deploy` in 244.3 seconds; all three services were healthy with matching
revision labels. Independent review is complete. Exact live `acceptance` was
not run because the Tokenmind credential exposed during a local Compose probe
must be rotated first; older live/soak/OCR runs remain dated working-tree
evidence. Pushing to GitLab and the real platform run are owner-gated. The
guide does not prescribe business operations or caller auth; both are product
contracts now recorded by the port ADRs. LLM operational policy and
real-platform behavior still need confirmation.

Current main also includes `app.hosted`, a generic strict-v2 candidate with
required API-key/provider configuration and a fixed seven-route allowlist. It
does not implement or prove the platform prefix/health shape, it includes
stateful sanitize/reidentify, and it does not migrate or replace the selected
sibling.

- Record the guide-confirmed repository template, topology, ports, resources,
  health, logs, secret materialization, and build rule as known. Capture only
  the remaining external answers: outbound network policy, actual proxy Host
  behavior, stricter infrastructure limits, LLM quota/logging/timeout policy,
  platform log retention/redaction, and acceptance owner/evidence.
- The public caller boundary is decided and implemented: static/health remain
  public, while every business route requires an access-code exchange for a
  30-minute HMAC-signed `Secure`/`HttpOnly`/`SameSite=Strict` cookie. Unit and
  container checks cover missing, invalid, tampered, expired, rotated, and
  cross-site authority. Rate limits remain defense-in-depth.
- Keep main v2 as a generic reference. Adjust only the selected sibling, which
  already covers prefix handling, frontend, and platform-shaped
  Compose/CI/logging. It is not accepted until its current-core composition is
  exercised on the official platform.
- The port now adapts current main through its pinned manifest without forking
  detection, masking, vault, provider, or restoration logic. Nginx keeps the
  public aliases, injects contract 2 and the internal core key, and the
  frontend consumes minimized v2 DTOs. Roundtrip no longer exports mapping or
  token-bearing entity projection. Exact provider-free check/deploy and
  independent review are complete. Dated live/failure/soak evidence remains
  useful but does not certify the final commit. The exact one-page PDF probe
  passes correctness in 221 seconds while nearly saturating two cores and
  reaching the 6 GiB memory limit; the 20-page/300-second claim remains a red
  deploy gate.
- Only after credential rotation and the PDF capability decision, create/push
  the owner-gated GitLab project,
  boot the exact candidate, and verify Thai UTF-8, secret injection, health,
  responses, and safe failures.
- Run malformed input, timeout, payload-limit, concurrent request, restart,
  and duplicate-side-effect cases. Test retry ownership only if the official
  HTTP contract defines retries.
- Complete one protected LLM roundtrip and scan application plus
  platform-visible logs with synthetic honeytokens.

Exit gate: the accepted HTTP service plus a repeatable soak with no crash,
duplicate side effect, mapping export, credential exposure, or PII-bearing
log.

Creating and pushing the GitLab deployment project is owner-gated. The core
PDF source-to-box boundary now has authoritative interval and fail-closed
automated coverage. The remaining hosted PDF blocker is to narrow/disable the
route or change its execution model, then prove multi-page resource/timeout
behavior. The remaining external
blockers are Tokenmind credential rotation, protected production-runner
confirmation, a confirmed support channel, outbound/LLM/log policy, first
push, public HTTPS/proxy evidence, and official acceptance. They do not block
Track A, Track C, documentation, adapter seam tests, the provisional worker
emulator, or image/resource measurement. Dated commitments for this program live in the
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
   issues and verifies, plus a Thai PDF. No HTTP endpoint by design.
2. **Breach assessment mode.** Delivered 2026-08-01
   ([record](docs/decisions/2026-08-01-breach-assessment.md)): scan a set of
   leaked documents and summarize type, count and affected-subject estimates,
   so a controller can draft the 72-hour PDPC notification from evidence
   rather than memory. Core plus a CLI verb, plus a Thai PDF. No HTTP endpoint
   by design.
3. **DSAR helper.** Delivered 2026-08-01
   ([record](docs/decisions/2026-08-01-dsar-helper.md)): locate which of a set
   of documents the controller already holds mention a data subject, so the
   controller can serve a มาตรา 30 access request from the located files
   themselves rather than searching by hand. The retention question that
   blocked this item was answered by the owner — in-memory for the run only,
   nothing beyond the requested artifacts written to disk. Core plus a CLI
   verb, plus a Thai PDF. No HTTP endpoint by design.
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
