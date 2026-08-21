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

- `v3.0.0` is tagged and published as the current GitHub Release (2026-08-14)
  with checksums and build provenance; the manually installable Extension ZIP
  is attached to the same release. `v2.5.0` evidence applies only to that
  pre-broker artifact. The Chrome Web Store item remains unpublished until
  exact-ZIP submission; publication details and their evidence limits are in
  [docs/project-status.md](docs/project-status.md).
- Phase 8 native-broker Slices 1--6 are integrated on `main` at
  `21f921aa8edb7415551b76f6633ce52fc5e323c6`; exact branch and post-main CI and
  cross-platform package smoke are green, and those slices ship in the
  published 3.0.0 packages.
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
   CI passed 11/11 and cross-platform smoke passed 2/2. Slice 4 Desktop
   broker-backed session/scope disposal is integrated. Slice 5 integrates the
   Extension equivalent; its owner-approved production identity, installed-
   companion gates, exact-head review, and CI pass. Office is outside broker v1
   under the accepted native-broker ADR, and all eight Office real-host/package
   gates remain open under the unchanged web-add-in architecture.
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
   Slice 2 is integrated: a single on-demand
   broker owns a protected Windows named pipe or filesystem UDS, binds OS peer
   identity and strict package-consistency evidence to the claimed role,
   prebinds and supervises one private authenticated Python backend, and serves
   only broker health plus maintenance-only drain/stop. Windows uses an
   explicit current-logon-SID DACL, kernel PID/token inspection, a named mutex,
   and an atomic kill-on-close Job assignment. macOS/Linux use `0700`/`0600`
   filesystem protections, a held lock, peer credentials, stable process
   identity, and substitution-safe cleanup. Local Windows and real WSL2 Linux
   runtime gates, macOS runtime CI, all 14 implementation branch CI jobs, and
   independent security review passed that checkpoint. Slice 3 is integrated
   with strict private HTTP-v2 forwarding,
   connection/scope/session ownership, confirmed disposal, non-replayable
   uncertain-completion handling, authenticated Python detector budgets,
   protocol deadlines, disconnect cleanup, bounded concurrency held through
   native publication, prompt dead-peer cleanup plus deadline-bounded Windows
   pipe backpressure, and
   backend-generation invalidation. Submitted-unknown work is never replayed
   or left running outside admission, and Python remains authoritative for
   mappings and every product operation. The
   [Slice 3 record](docs/acceptance/2026-08-08-phase-8-native-broker-data-plane.md)
   records local Windows/WSL2 runtime and a clear independent security review.
   Reviewed implementation commit
   `19b38392541bdb1c713a037799190409e71e61c1`
   [passed all 14 branch CI jobs](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31262151884),
   including Windows, Ubuntu, and macOS native runtime. Integrated baseline
   `33989cac356330ff4efdb080c470b8bb63561c6a` contains Slices 1--3.
   Slice 4's last fully gated executable checkpoint is
   `492dad34361b09d7ffa58fa192a2447de7414418`. Webview operations cross
   operation-specific Tauri commands; hotkeys call the same typed Rust broker
   client directly. Per-window UI and hotkey scopes own broker handles,
   submitted data operations are never replayed, renderer generations reject
   stale queued work, and unconfirmed cleanup disconnects fail closed.
   Production Desktop contains no direct backend/data-plane HTTP, Python
   launch, port scan, provider implementation, or legacy fallback authority.
   The owner chose a credential-free installed-product boundary. The current
   branch fixes the Desktop/shared-broker detector to local `thainer`, allows
   `fake` only for internal backend conformance, and exposes no provider command
   to the webview. Unsupported explicit detector/provider selectors fail before
   launch with stable `ner_unavailable` or `provider_configuration` errors.
   Desktop-to-broker and broker-to-backend child seams construct a fixed
   runtime-name allowlist without querying provider/TNER credential values and
   pin `thainer`/`fake`;
   Desktop and broker no longer snapshot remote configuration independently, so
   a warm broker cannot silently select a different detector. This closes the
   identified configuration-ownership P1. Exact branch CI, cross-platform
   package smoke, and independent review passed before Slice 4 integration.

   Slice 5 is integrated. Its source branch was
   `codex/phase-8-native-broker-extension`. The MV3
   service worker owns one Native Messaging port and separate broker scopes for
   each tab and panel instance; every document replacement, including same-
   origin hard navigation, gets a fresh tab scope. The strict adapter validates
   exact origin,
   browser process context, package identity, framing, response bounds, and the
   `extension` role. Production Extension code has no loopback permission,
   fetch/port discovery, credential/provider/TNER path, or fallback. The
   Desktop companion packages and registers the adapter and exact host manifest
   on Windows, macOS, DEB, and AppImage layouts. Transient AppImage Desktop
   startup re-executes from the verified stable package so it shares Chrome's
   exact component root; the GUI is not a runtime dependency. Historical
   synthetic evidence remains test-only. Production-keyed real Chromium and
   exact CI-produced NSIS installed-companion acceptance is recorded in the
   [Slice 5 record](docs/acceptance/2026-08-11-phase-8-slice-5-native-messaging.md).
   AppImage packaging preserves the frozen backend outside linuxdeploy,
   restores it atomically, and attests the restored final bytes before
   checksum-pinned repacking. One private per-version lock serializes the full
   stage+register or unregister+remove transaction; repeated repair preserves
   every verified stable component inode when the complete installed set
   already matches, so a live broker remains admissible across AppImage
   launches.
   Owner-approved unpublished Chrome Web Store Item ID
   `kdjmkknedgmfphpkjhjdhmjadaelgggm` derives from the committed public key and
   admits only
   `chrome-extension://kdjmkknedgmfphpkjhjdhmjadaelgggm/`. The normal
   production packager, exact-ID Chromium 145 run, CI-produced NSIS
   install/register/use/uninstall path, wrong-origin fixture, and Windows/Linux/
   macOS package smoke all pass with zero final product registration/process
   delta. The Web Store item remains Draft/unpublished; this is exact-ID
   unpacked-browser evidence, not Web Store installation or default-path NSIS
   evidence. Slice 5 is integrated.

   The Slice 6 source closure repair is locally complete in its affected scopes;
   a replacement exact-head review and workflow candidate remains pending. It
   was recovered from preserved
   branch `codex/phase-8-native-broker-package-recertification`; exact checkpoint
   `d1ee42557c2b620d37a07504aea9e33047599746` remains the pre-final local
   executable/package artifact record. When this exact tree reaches `main`
   through the closure protocol below, the integrated tree requires one
   complete five-executable manifest set before
   installed native admission, rechecks the opened executable identity, and
   rejects mixed build IDs, roles, names, digests, modes, owners, or links with
   fixed value-free failure. A verified product-owned maintenance barrier
   stops new data admission while the least-authority maintenance client drains
   broker/backend state. Package replacement never serializes mappings or
   replays an uncertain operation; repaired/restarted clients receive fresh
   credentials and empty scopes. Windows NSIS, external Linux `dpkg`, and
   AppImage stable-root transactions use the same drain-before-replacement
   contract. The only enabled in-app updater is Windows, where verified bytes
   are handed to NSIS. macOS relocation repair verifies the complete set and
   repairs registration without claiming component replacement; in-app macOS,
   DEB, and AppImage updates are rejected before updater access. Local installed
   NSIS plus exact-ID Chrome evidence,
   real WSL tests, deterministic interruption/crash/stale-state fixtures, and
   package contract tests are green. Recovery and review also closed bounded
   shutdown-response, AppImage drain reachability, extended-UNC normalization,
   product-wide cross-session Windows transaction-locking, fresh-process NSIS
   receipt recovery with Windows PowerShell 5.1-compatible validation, retry-
   idempotent partial DEB removal, and clean-runner process-query races without
   weakening inactivity or exact-path proof. The final recovery also makes
   Windows fixture ownership deterministic, requires the exact 65-byte receipt,
   publishes the Desktop smoke release marker atomically, and nests the bounded
   Linux drain/parent/signal deadlines with explicit margin. The obsolete
   replacement also exposed case-insensitive PowerShell matching, the separate
   Slice 6 fixture owner, and a live DEB harness that asked the invalidated old
   Desktop to run the new package workflow. The current recovery requires
   case-sensitive receipts and splits DEB upgrade evidence into old-session
   invalidation followed by re-attestation and full smoke of the new install.
   The earlier candidate's independent NSIS tool-download disconnect is not
   code evidence and must be replaced by a green exact-head package job. Later
   obsolete heads were invalidated by an overstated structured-invalidation
   assertion and exact-head failures in bounded startup readiness, control-
   handshake deadline ownership, and a marker-only Windows package failure
   whose artifact did not preserve its failing phase. The current source
   requires explicit second-operation invalidation and accepts startup busy
   only through bounded readiness. A later final
   review invalidated its candidate because a late connection reset the request
   deadline and a pre-request operation timeout was not retried. The current
   source reuses one strict maintenance preparation, retries pre-request
   transients only while the endpoint proves active, and threads one absolute
   outer deadline through connect/hello, the single drain request, and
   inactivity proof. Candidate `854b6aba` then failed Windows installed-package
   CI and Ubuntu cross-platform smoke; neither run counts as evidence. Local
   reproduction proved a real PowerShell 5.1 `Add-Type` collision with NSIS's
   native `$PLUGINSDIR\System.dll`; changing the child working directory to
   `$INSTDIR` closes that mechanism, but did not prove the hosted failure phase.
   The Ubuntu log did not preserve its final command, but the workflow also
   contradicted the nonblocking AppImage lease by requiring two concurrent
   repairs to succeed. It now proves fixed contention status 75 with no state
   mutation, releases the lease, and retries within a finite bound. After the
   package-layout step initializes its tracker, the `always()` artifact can
   upload only the latest-started coarse phase and available value-free partial
   evidence; it cannot guarantee an artifact for earlier failure or runner loss.

   Candidate `ea8eb772` passed all three read-only reviews but was invalidated
   by exact-head CI `31705549161` (13/14; only Windows installed-package job
   `94465065578` failed) and cross-platform smoke `31705549230` (macOS passed;
   Ubuntu failed). The Windows artifact retained the full extracted payload,
   manifest, uninstaller, and marker with no registration; the Linux artifact
   identified only the latest-started `deb-interrupted-remove-recovery` phase
   after earlier DEB phases completed. Neither artifact preserved the exact
   failing command; the Windows artifact also preserved no ACL. Neither run is
   closure evidence.

   The current repair preserves `TokenUser` as the installed trust boundary.
   Before post-install manager admission, actual PowerShell 5.1 handle-validates
   the exact fixed payload, permits bootstrap source ownership only from exact
   `TokenUser` or the process's exact `TokenOwner`, rejects empty/reparse/linked
   state, normalizes the payload to `TokenUser`, and rechecks identity and owner.
   It never normalizes receipt-bearing authority; the unchanged strict manager
   then verifies manifest schema, paths, build IDs, and digests. This addresses
   the mechanism-consistent elevated-NSIS owner mismatch without admitting an
   administrator group in ordinary operation. The exact-head job records a
   value-free owner-difference boolean and remains the authoritative transition
   proof. Separately, only manager `cleanup deb` may load the incomplete set
   left after interrupted `prerm`; it still verifies the exact manager and
   manifest authority, while all other operations require the complete set.
   Fine-grained phase starts and 60-second manager/retry bounds narrow a later
   Linux failure to its latest-started step without proving that command or
   phase completed. Current actual PS5.1, WSL manager/Slice 6, both Windows
   native matrices, affected Python,
   format/lint/version, and isolated NSIS lifecycle gates are green.
   Receipt-bearing state remains strict. Three read-only
   exact-head reviews, branch CI/package smoke, squash integration, post-main
   workflows, tree equality, and branch cleanup are required by the closure
   protocol recorded in the Slice 6 acceptance document.
   Evidence is recorded in the
   [Slice 6 acceptance document](docs/acceptance/2026-08-12-phase-8-native-broker-package-recertification.md).

   Candidate `097d41d4d7c141f0e001ded1cbb868c0c45ae7d7`, tree
   `9d74a768814d18d064da11300de2da0e1428fe48`, passed its independent
   correctness/security and package/deployment reviews but was invalidated by
   both exact-head workflows and therefore was not integrated. CI run
   `31713219318` passed 13/14 jobs; Windows package job `94491279795` failed
   after a distinct-`TokenOwner` clean install, four registrations, and two-run
   installed smoke. The artifact did not retain per-contender statuses. Source
   ordering and a local held-lock run of the exact custom-root artifact prove
   rejection with only an empty directory left by Tauri's pre-hook `SetOutPath`;
   the workflow incorrectly treated that directory as package state.
   Cross-platform run `31713219299`
   passed macOS job `94491279822` and failed Ubuntu job `94491280004` only at
   normal AppImage FUSE repair after all DEB and extracted/stable AppImage
   phases had completed. Artifact `9186746050`, the fixed failure stage, and a
   pinned-runtime WSL mount prove that immutable FUSE files are root-owned on a
   read-only mount, whereas the staging predicate previously required the
   effective user. Neither failed run counts as closure evidence.

   The replacement leaves the production Windows lock unchanged. Its workflow
   requires both contenders to fail, accepts only an absent or exact empty
   non-reparse synthetic directory, re-attests the installed digests and
   registrations, and removes only that verified-empty probe. AppImage staging
   now permits root ownership only for the exact canonical `$APPDIR/usr/bin`
   transient source on a read-only filesystem, with one owner/device, regular
   non-symlink one-link files, exact modes, and the existing digest/build-ID
   checks. Extracted sources may remain effective-user-owned; stable published
   components remain strictly effective-user-owned. The focused workflow tests
   and the resulting 22-test WSL manager suite pass without changing any
   deadline or downgrading normal FUSE evidence.

   Evidence remains separated by exact path. Prior local source/native tests
   pass on Windows and real WSL2 Linux. The 12-launch Windows NSIS result and
   its hash/timings are historical dirty-tree evidence only. Clean predecessor
   `c6dcad1` passed all 14 jobs in
   [CI run 31325662048](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31325662048),
   including a two-run isolated NSIS install. Predecessor `0424716` had a green
   relocated-macOS-app job in
   [run 31326610316](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31326610316),
   whose overall workflow failed on Linux; relocation is not installation
   evidence. Earlier predecessor `8be9523`
   [CI run 31327288545](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31327288545)
   passed 14/14 including installed Windows NSIS. Its macOS relocation job
   passed in
   [cross-platform package run 31327288595](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31327288595)
   but the workflow is red because Linux process inspection rejected an
   unrelated protected same-UID process before Desktop launch; that diagnostic
   harness failure supplies no Linux DEB/AppImage result. Predecessor `6ad3422`
   adds a reviewed process-name prefilter while retaining exact
   `/proc` path and fail-closed checks for actual candidates. Its 56 focused
   package/workflow tests and real WSL clean-parser probe passed locally. Exact
   [CI run 31328047804](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31328047804)
   passed all 14 jobs, including the two-run installed Windows NSIS smoke.
   [Cross-platform package run 31328047802](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31328047802)
   is red. Its macOS relocation job passed with
   tested-app archive SHA-256
   `8d22957bba783737df954dee5c2a76a012ebeb1bb6f4c1f04886e93916245939`;
   the extracted DEB also completed both runs, but AppImage component digest
   verification failed before AppImage Desktop launch because packaging mutated
   the component bytes after the pre-bundle hashes. No AppImage, full Linux, or
   cross-platform pass comes from that predecessor.

   Predecessor `3836024` stages an invalid AppImage pre-manifest, hashes the
   actual post-linuxdeploy AppDir components, and repacks with a
   checksum-pinned AppImage plugin. Exact
   [CI run 31329794579](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31329794579)
   passed all 14 jobs, but
   [cross-platform package run 31329794568](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31329794568)
   is red: macOS passed and Linux failed finalization before package smoke
   because the first runtime-prefix guard did not allow appimagetool's defined
   `.digest_md5` rewrite.

   Predecessor `73dcca4` copies the trusted original runtime prefix before
   repacking. For the pinned, scrubbed no-sign/no-update invocation, it parses
   both little-endian x86-64 ELF64 prefixes, permits only the unique
   non-executable, non-overlapping 16-byte `.digest_md5` rewrite, rejects
   overlap with executable load segments, and requires every other prefix byte
   to match. Its 76 focused package/workflow tests and exact-delta independent
   review passed with no P0/P1/P2. Exact
   [CI run 31345691672](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31345691672)
   passed 14/14 including installed Windows NSIS, but
   [cross-platform package run 31345691667](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31345691667)
   is red: relocated macOS and extracted DEB passed, while the AppImage harness
   bypassed the outer runtime/`AppRun` and produced no marker.

   Predecessor `8194c23` adds a separately precreated canonical private marker
   directory for AppImage smoke, routes native-start and every fixed marker
   through it without overwrite, and fails an invalid supplied root without a
   package-directory fallback. An independently extracted layout attests the
   finalized bytes; repetition one crosses the exact outer AppImage with
   `--appimage-extract-and-run`, and the warm repetition re-attests the retained
   live root before launching its `AppRun`.
   [CI run 31348501253](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31348501253)
   is red, 10/14, only because the new canonical-root unit test relied on
   non-portable path spelling. Its installed-Windows NSIS job nevertheless
   passed. Separate
   [cross-platform package run 31348501256](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31348501256)
   passed 2/2, covering relocated macOS, direct extracted-DEB smoke, and the
   finalized outer AppImage plus verified warm `AppRun` with
   `execution_mode=outer_appimage_extract_and_run_then_verified_apprun`.

   Last fully gated checkpoint `492dad3` repairs only that portable test
   construction and retains the production contract. Focused package/workflow
   Python tests pass 100 with one expected Windows Unix-mode skip; separate
   full local Rust runs of 19 default and 26 all-feature tests preceded the
   final portability-only edit. After it, the exact private-root test passed on
   Windows and real WSL; exact CI confirms all 26 Desktop tests on Ubuntu,
   Windows, and macOS. Affected format, lint, Clippy, and diff gates pass. Exact
   [CI run 31349781519](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31349781519)
   and
   [cross-platform package run 31349781518](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31349781518)
   passed 14/14 and 2/2 respectively. CI includes two launches from the exact
   isolated Windows NSIS installation. The package run includes two relocated
   macOS launches, two direct extracted-DEB launches, and the finalized outer
   AppImage `--appimage-extract-and-run` launch followed by a re-attested warm
   `AppRun`; every path left zero broker/backend process delta. Installed
   Windows NSIS, relocated macOS app, extracted DEB, and
   outer-AppImage/warm-`AppRun` results remain separate evidence classes. The
   AppImage run is not normal FUSE/double-click or installation evidence. The
   detailed record is the
   [Slice 4 acceptance document](docs/acceptance/2026-08-09-phase-8-native-broker-desktop.md).

   Slice 4 package smoke uses an offline detector and fake provider. That is the
   installed Desktop product boundary, not live provider/TNER evidence. The
   owner-decision correction has focused source regressions for selector
   rejection, child-environment isolation, warm-broker attachment, and Desktop
   provider admission, plus green exact branch CI and package smoke. Slice 5 is
   integrated. Slice 6 completes automated
   package/runtime behavior, updater ordering, supported-path relocation,
   upgrade/drain, interrupted-
   upgrade recovery, stale cleanup, uninstall/reinstall, and installed lifecycle
   recertification. The repeated final pixel-level UI pass was unavailable at
   the Windows lock screen and is not claimed. Exact Slice 6 branch/post-main
   workflow evidence is green at integrated main `21f921aa`; that is
   integration evidence, and the separately owner-authorized 3.0.0
   certification concluded with the published `v3.0.0` release on 2026-08-14
   (publication facts and their evidence limits are in
   [docs/project-status.md](docs/project-status.md)). Office remains
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
current Desktop broker-backed lifecycle/disposal, future Extension lifecycle,
explicit-TNER,
provider-orchestration, and PDF-offset changes each invalidate carry-forward
evidence only for their affected paths. Fresh automated, packaged, real-host,
live-provider, or official-platform evidence must match the strength of the
changed path. Shared provider orchestration has current-source automated
evidence, while its packaged, live-provider, real-host, and official-platform
recertification remains open. The owner-authorized 3.0.0 release is tagged and
published (2026-08-14) with synchronized package metadata; Chrome Web Store
submission remains a distinct owner-gated gate.

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
- Credential-requiring providers or remote TNER in installed Desktop. A future
  owner-approved ADR must define credential ownership, provisioning,
  permissions, storage, rotation, configuration identity/epoch, broker
  restart/reconfiguration semantics, upgrade, uninstall, attestation, and
  cross-platform behavior before this boundary can expand.

Security fixes, official platform requirements, and defects in a committed
feature are never deferred by this list.
