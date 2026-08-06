# Architecture and trust boundaries

AI Guard follows **one core, multiple storefronts**. Detection,
pseudonymization, leak scanning, restoration, and validation live under
`pii_redactor/`. The extension, desktop app, Microsoft 365 add-in, CLI, HTTP
API, demo, and hosted adapters translate caller input to that core; they must
not create separate detection logic.

## System shape

```text
Browser extension ----\
Desktop app -----------+--> local FastAPI adapter --------\
Office add-in ---------/                                  |
                                                           +--> pii_redactor core
Hosted HTTP -----------> main hosted candidate ------------|    detect -> mask
Demo playground -------> demo/API adapter -----------------|    -> guard
CLI -------------------> direct core adapter --------------|    -> provider
Provisional job runner -> worker adapter ------------------/    -> restore
```

The adapters serve three deliberately different lifecycles:

- Local HTTP sessions retain the canonical mapping in backend process memory
  behind an opaque `session_id`, enabling multi-turn restoration on one
  device. Clients necessarily handle the user-submitted and returned text, but
  receive no explicit mapping DTO and retain no mapping collection. Current
  HTTP v2 projects sanitized/restored text plus safe counts, categories,
  severities, and sanitized-space highlights; strict first-party validators
  reject unknown mapping-oriented fields, raw Section 26 matches, and
  prompt-guard excerpts/rationales.
- The current main-repository hosted candidate is mixed. `sanitize` plus
  `reidentify` retain an in-process mapping behind `session_id`, while a
  protected `roundtrip` consumes its transient mapping before returning. No
  hosted response returns an explicit mapping DTO, token/original pair, or
  reconstructable original-space entity projection. Callers still necessarily
  handle submitted and returned text. The official platform route set and
  lifecycle remain unconfirmed.
- The worker operations and internal versioned job envelope remain a local
  emulator and replaceable compatibility boundary. The official participant
  guide selects an HTTP/FastAPI service behind its reverse proxy, so the worker
  is not the current delivery contract.

## Trust boundary A - local product

The desktop sidecar binds to localhost and serves the browser, desktop, and
Office paths (the Office task pane reaches it through an HTTPS localhost
proxy). The intended local invariant is that a client's retained authority is
an opaque session reference rather than an explicit mapping or credential, the
canonical token-to-original map remains in backend memory, and an
AI Guard-controlled provider adapter should send only leak-guarded masked text.
Clients still handle input and display/output text transiently.

The browser in-page composer has an earlier trust boundary: raw text is typed
into a provider-owned page DOM before the user clicks Mask. Page code can
observe or transmit that draft before AI Guard replaces it. Contract v2,
residual blocking, and a localhost broker cannot remove that exposure. For the
stronger boundary, enter raw text in the extension side panel and paste only
the reviewed masked result into the provider page. In-page Mask protects the
AI Guard-controlled call and places reviewed masked text in the composer before
the user submits. It does not intercept or attest the provider page's network
request and is not a guarantee that page code never saw or retained the draft.

At the frozen `93a7108` baseline, three verified gaps prevented stating that
invariant as accepted: contract-v1 responses exposed direct or reconstructable
mappings to client code; local clients plus HTTP/worker roundtrip providers
could continue after residual warnings; and a fixed-port client did not
authenticate which process owned localhost port 8000. Current source closes
the response-projection and residual halves. HTTP v2 uses exact server/client
DTOs with no explicit mapping, raw match, or excerpt fields. At the shared core
and direct-provider adapter boundaries:
structured FP findings, text-based TB findings, detector-independent
contiguous runs of six or more digits, and missing replacement records all
fail closed. Caller mappings cannot reuse empty, identity, embedded-original,
source-pre-existing, or independently residual-looking pseudonyms; a reused
token must also match the exact product token shape for the detected data type.
New token-mode values carry a random vault-generation tag and an unpredictable
per-token nonce. A token from a dropped, restarted, expired, or evicted session
remains unchanged and is reported only as a count-only foreign warning in the
exercised regressions instead of being restored through a replacement vault.
The random 64-bit tag plus approximately 94-bit nonce makes accidental identity
reuse and future-token preplay computationally impractical; this is
probabilistic separation, not impossibility. Exact unknown current-format
tokens remain foreign even when the replacement vault uses surrogate mode. The
CLI repeats the scan immediately before each
outer `provider.complete()`
invocation; a self-retrying provider receives one outer validation before
resending the same immutable masked text. HTTP and worker roundtrip repeat it
immediately before their direct calls. Current evidence includes source-level
automation plus an exact-candidate automated local run of the packaged backend
directly and through the Office HTTPS development proxy. The proxy leg reused
pre-existing trusted development certificates without changing them; it did
not exercise an installed client, Office JavaScript or host adapters,
sideloading, certificate provisioning, or a provider. Fixed-port identity
remains unauthenticated. CORS and
`TrustedHost` restrict browser request context and host headers; they do not
establish server identity. Fresh client/package acceptance and the native
broker remain open hardening gates.

`SessionService` is the sole TTL authority for its managed vaults. It owns one
earliest-deadline timer and expires every due session at the exact half-open TTL
boundary (`age >= TTL`) without waiting for a client request; managed
`SessionVault` instances do not make a second expiry decision. Standalone
vaults retain their own exact-boundary idle expiry. Timer generations make
canceled or stale callbacks inert. A request that acquires the coarse lifecycle
lock before its deadline completes atomically. Sanitize and restore receive a
fresh TTL only after successful completion; failed restore attempts leave the
original access time, deadline, and timer unchanged. Expiry, explicit disposal,
shutdown, and capacity eviction serialize on the same lock. The service
validates every managed deadline before scheduling. A timer-start or scheduling
prerequisite failure closes the service and releases all registered state
rather than continuing without eager expiry. An ordinary eager-callback
failure follows the same close-and-clear path; process signals still propagate.

A session ID is a security-sensitive, bearer-like restoration reference on the
local data plane when its optional API key is unset. The internal
`DELETE /api/session/{session_id}` route requires exactly one short-lived HMAC
authorization derived from the boot secret inside the trusted control plane.
The signature binds its version, target session, expiry, and random nonce.
Verification accepts only canonical unpadded base64url, fingerprints canonical
authenticated content, and rejects exact-boundary expiry, malformed or
noncanonical values, duplicate headers, a different target, and replay. Final
expiry validation, replay consumption, and disposal occur atomically under the
lifecycle lock, so authority that expires while waiting is not consumed. No
configured boot secret means disposal is unavailable. A fresh valid
authorization makes repeated disposal idempotent, while the same authorization
is single-use. Recognized Uvicorn access records discard query values and
replace the bearer-like session path value with a fixed redaction marker before
launcher or Desktop output forwarding; an unknown access-record shape is
suppressed fail-closed. Non-sensitive access and application logs remain
enabled. Desktop web and hotkey paths reuse their prior session and retry once
without it only for exact expiry/mode-reset errors. Extension tab close and
Office reset still clear only client references. No JavaScript client receives
the boot secret or a derived disposal authorization; broker-backed client
disposal remains Phase 8.

The session resource graph is deliberately small: the service owns each
in-memory vault/mapping namespace, entity list, trusted digest list, salt,
lifecycle timer state, bounded authorization-replay fingerprints, and hashed
tombstones. Cleanup clears those references on authenticated disposal, eager
expiry, shutdown, eviction, and lifecycle failures. Current provider clients
are per-call resources rather than session-owned handles, and `SessionService`
owns no provider process, child process or handle, listener/port, temporary
path, or delivery queue. Process-audit records use non-authorizing operation
IDs and are not a session-owned restoration namespace.

Local sanitize runs under the existing coarse `RLock`. A complete detached
session state is staged through masking, residual scanning, response
projection, Section 26, guard projection, JSON rendering, and required
process-audit work, then published through one `_sessions` assignment. An
exception before that assignment discards staged references without changing
the published graph or capacity/LRU state. Known-session expiry disposal is
lifecycle cleanup outside this rollback guarantee. Cleanup of a replaced or
evicted vault happens after publication and is best effort; it cannot turn an
already-published success into a caller-visible failure. A required timer that
cannot start is different: the service fails closed, clears both detached and
registered session state, and returns no success. Immutable entity,
mapping, and internal-audit records permit detached containers to share prior
values without a growing deep-copy cost. A clear generation and lifecycle lock
prevent a stale provider rollback snapshot from reviving disposed mappings.

## Trust boundary B - hosted platform

Calling a hosted AI Guard service necessarily sends the request to the hosting
platform. The raw input therefore reaches the platform boundary and the AI
Guard container. The current main-repository `app.hosted` candidate uses
minimized v2 projections and a fixed allowlist of health, detect, analyze,
guard, sanitize, reidentify, and roundtrip. Its sanitize/reidentify pair keeps
session state in process with no hosted disposal route; roundtrip keeps its
mapping within one request. It rejects sanitizer residuals and repeats the
fail-closed scan immediately before a direct provider call. Automated tests
also assert PII-free application errors and logs. This generic candidate is not
the confirmed official route/lifecycle contract. The separate sibling port
remains independently versioned v1: its roundtrip consumes its literal mapping
internally but returns its older reconstructable entity projection, and its
pre-F09 outbound policy and official platform logs remain unaccepted. The
intended hosted boundary therefore remains:

- no deliberate mapping persistence to disk;
- no user text or raw PII in application logs or public error messages;
- no explicit mapping DTO, token/original pair, or reconstructable
  original-space entity projection in an approved hosted HTTP result;
- outbound text passes the shared policy immediately before provider use; and
- container restart may intentionally discard transient restoration state.

The hosted product must never reuse the local slogan "PII never leaves the
device". Current source requires text to pass the current outbound-policy
checks before its provider calls, but the historical live and platform
evidence predates this change and must be rerun. Until that exact hosted
composition passes, public
claims remain limited to **AI Guard is designed not to write the canonical
mapping to disk and to send policy-checked masked text to its configured
downstream provider**. The current sibling port uses Tokenmind as a local
candidate; source tests, the main candidate, and that sibling are not claims of
official deployment acceptance.

## Core processing layers

1. Ingest and normalize text or PDF content while preserving coordinates where
   redaction requires them.
2. Detect structured PII with regex/checksum rules and free-form PII with Thai
   NER/context logic.
3. Resolve overlaps centrally before any replacement.
4. Replace values with session-namespaced tokens or realistic surrogates.
5. Enforce the shared outbound policy before optional AI provider use:
   structured FP and text-based TB findings, an otherwise undetected
   contiguous run of six or more digits, or a missing replacement record
   blocks the output.
6. Restore from the in-memory mapping when the selected lifecycle supports it.
7. Validate restoration/output integrity and produce structural audit
   metadata.
8. Return text, a report, or a flattened redacted PDF.

Product-owned vault audit rows contain opaque identifiers and structural
metadata. When a caller-held stateless mapping is re-admitted, `seed()` checks
the pseudonym directly under the vault lifecycle lock. A new pair receives an
opaque `seed:<uuid4>` entity ID, keeps provenance in the safe `SEEDED`
data-type sentinel, and adds one `seed` audit row. An identical pair returns
the existing immutable record without changing lookup, audit, or access state.
A conflicting original fails with a constant value-free error before mutation.
Production `write()` callers supply detector-generated UUIDs; an arbitrary
direct Python caller is not an adapter boundary and could still supply an
unsafe entity ID. `clear()` drops vault-owned lookup references and may retain
the safe product-owned structural audit rows; it cannot securely zeroize
Python immutable strings.

Each vault also owns a non-secret random token-generation tag. Every newly
minted token adds an unpredictable per-token nonce, so a visible tag and
predictable ordinal do not make future-token preplay practical under the
accepted probabilistic design. Detached transaction clones and snapshots
preserve the tag and full token records, while `clear()` drops them with the
mapping references. Fresh
stateless token calls receive fresh tags and nonces; a caller that explicitly
supplies one admissible prior-mapping namespace can continue that chain and
reuse its complete existing tokens. The parser requires the exact
label/tag/nonce/ordinal grammar before a seed can select continuity. Neither
component is `session_id` or authentication material.

A caller-supplied prior mapping is a declaration, not proof that its key is a
safe pseudonym. Seeded values do not silence FP, TB, or independent digit
findings merely because the caller named them. A seeded value that independently
triggers the residual policy is not reused; token mode also requires the
product token shape for the detected data type, and the residual scan runs
before that shape can be trusted. Current code never mints the legacy
`[<label>_<ordinal>]` shape; it remains readable only at this explicit
caller-held stateless boundary. Surrogate generation can
independently reproduce a prior product value under the current salt/context,
at which point the normal generated record—not the caller declaration—becomes
trusted. Every detected entity must have a current replacement record; an
absent record blocks rather than returning an incomplete result.

Direct stateless sanitize/restore wrappers translate unexpected defects to
fixed value-free processing errors only after clearing their public arguments
and clearing—or, if cleanup itself fails, dropping references to—the throwaway
vault. `SessionService` applies the same pattern to sanitize finalization and
restore, including context-free expiry translation. The HTTP adapter contains
endpoint-authored failures, otherwise-unhandled downstream HTTP exceptions
that reach the endpoint decorator, request-model validation, and
pre-response-start JSON rendering. Invalid values are never copied into the
fixed 422/500 responses. The worker handler and runner sever ordinary caught
error graphs before returning or submitting a version-1 error envelope. The
shared disposal helper clears traceback/chaining, arguments, ordinary custom
attributes, and common built-in payload slots after safe metadata has been
extracted. An ordinary `ExceptionGroup` is translated and its members are
recursively scrubbed, but Python exposes the group's own message/member shell
through read-only C-level fields; the helper preserves that shell to avoid
corrupting `repr()` and callers drop it without logging/exporting it. Groups
carrying process signals are allowed to propagate. Process signals may also
propagate when raised directly.

All public `SessionVault` reads, writes, exports, audit access, and lifecycle
operations share one re-entrant lock. This makes a seed/write/clear transaction
and its public observations linearizable. Some core pipeline functions read
private vault indexes while already operating inside a caller-owned
single-threaded or service-locked path; this is not a claim that arbitrary
whole-pipeline concurrent use is safe.

Current API process-audit call sites pass fresh operation UUIDs rather than
live restoration session IDs. Successful sanitize writes a `prepared` record
before publication, and blocked residual requests may retain one safe
`blocked` attempt record. The legacy filename/JSON field is still named
`session_id`; the audit primitive does not enforce safe identifiers for
arbitrary future callers. `/api/audit-log` omits that field. Each operation
creates an operation-specific file in file mode, and those files have no timed
retention policy; configured stdout mode creates no file. The published 2.5.0
artifact predates this source change, and official hosted log transport and
retention acceptance remain pending.

Provider orchestration is not yet one choke point. The CLI pipeline uses
`send_to_ai()` for retries, validation, and rollback and now repeats the shared
outbound scan immediately before each outer provider invocation. Providers
that own their retries receive one outer validation and resend the same
immutable masked input internally. Its public wrapper also translates snapshot,
provider-capability, validation, provider, response-tail, and rollback defects
to fixed safe categories after discarding the original error graph. HTTP
roundtrip and the worker still invoke `provider.complete()` through their own
adapters, but each repeats that same scan immediately before the direct call.
This closes the known residual bypass without claiming retry/error/lifecycle
parity.
Tokenmind's current internal retry loop still uses one total timeout and honors
`Retry-After`; the locked shared-orchestration target instead uses up to three
60-second attempts with fixed 1/2-second backoff.
Likewise, explicitly selected remote TNER receives raw pre-mask chunks. The
shared NER chunk guard currently skips runtime tag failures for every engine;
the locked policy keeps appropriate local/default degradation but requires
explicit TNER to fail the whole request. Shared protected-roundtrip
orchestration and typed fail-closed TNER errors remain open gates.

PDF extraction preserves geometry, but `WordBbox` does not yet carry canonical
source intervals. `redact_pdf()` does not consume `Entity.span`; it derives
normalized `Entity.original_text` fragments and globally substring-matches
boxes, omitting one-character boxes. Exact half-open source intervals and
fail-closed missing-box behavior are open gates; the existing coordinate
system and no-deskew rule remain deliberate. Current fallback/retry paths clear
traceback frames, exception chaining, arguments, ordinary custom attributes,
and common built-in payload slots from caught pdfplumber,
page-object-enumeration, dependency-probe, encoding, and OCR retry errors before
continuing. Retained-error tests cover the ordinary exception links and payload
forms used by these paths; the immutable `BaseExceptionGroup` shell limitation
above still applies. This is privacy containment, not exact-alignment or
optional-OCR acceptance.

Section 26 semantic signals are reported rather than automatically removed.
The prompt-injection guard is an independent warn-only signal layer, not part of
PII detection and not a complete injection defense. The inspection endpoints
`/api/detect`, `/api/analyze`, and `/api/guard` likewise report findings; they
are not outbound-use paths and do not turn Section 26 or prompt-injection
signals into automatic blocking or redaction.

## Source layout

| Path | Responsibility |
|---|---|
| `pii_redactor/` | Product core: ingest, detection, masking, vault, provider clients, restoration, validation, reports, and PDF redaction. |
| `app/server.py` | Local/HTTP adapter and API contract. |
| `app/http_v2.py` | Strict HTTP-v2 response and error DTOs shared by the main adapters. |
| `app/hosted.py` | Generic main-repository hosted candidate with required API-key/provider configuration and a fixed seven-route allowlist; not an official-platform acceptance claim. |
| `app/worker/` | Stateless job operations plus a provisional transport used for local pre-platform acceptance; not the official HTTP delivery path. |
| `extension/` | MV3 browser extension and supported-site adapters. |
| `desktop/` | Tauri shell, static UI, updater, and sidecar lifecycle. |
| `office-addin/` | One TypeScript task pane with Word, Excel, and PowerPoint host adapters. Its retained state is display text plus a security-sensitive `session_id`, with no explicit mapping collection; current source validates strict v2 projections and blocks document writes on malformed, incomplete, or unsafe results. Automated packaged-backend/HTTPS-development-proxy transport composition is verified locally; all eight real-host/package gates remain open. |
| `demo/` | Opt-in demonstration UI; not a separate production frontend. |
| `benchmark/` | Diagnostic corpora, scorers, and engine comparisons. |
| `research/` | Privacy-reviewed external evidence and reproducibility records; not a runtime package. |
| `training/` | Optional, gold-disjoint training inputs and lexicons; model weights stay outside the repository. |
| `examples/` | Synthetic prompts, sample documents, and reproducible example builders. |
| `assets/` | Shipped visual assets. Stale demo/architecture rasters were removed; current trust-boundary claims live in this document. |
| `tests/` | Contract, security, feature, benchmark, and release regression tests. |
| `scripts/` | Build, version, release, and smoke tooling. |
| `docs/` | Current operating docs plus historical ADRs. |

The repository root keeps public entry points, project metadata, and governing
files: `ai_guard.py` and `demo_cli.py` are supported CLI commands, `run.ps1`/`run.sh`
start the local backend, and `pyproject.toml`, requirements files, package
manifests, and lock files define the supported Python, JavaScript, Office, and
Rust environments.
Generated reports, logs, caches, virtual environments, model downloads, and
packaged output are local-only and must not be committed. The encrypted
`blind-v1` corpus, its aggregate audit log, synthetic gold data, and sanitized
government-form inputs are deliberate evidence/reproducibility artifacts; the
blind budget is exhausted and future blind evaluation requires `blind-v2`.

This boundary is already test-covered. Moving modules for appearance alone
would add release risk without improving the product, so source reorganization
is deferred unless a concrete dependency or ownership problem appears.

## Configuration boundaries

- `VERSION` is the product-version source of truth.
- `contract_version` is the independently versioned public API contract.
- Current HTTP v2 uses `X-AIGuard-Contract-Version: 2` as a required assertion
  on every API operation except health; clients also validate the fixed
  response header before using a result.
- `AIGUARD_NER_ENGINE` selects a process-wide NER implementation.
- `AIGUARD_TOKEN` is local control-plane authority for shutdown and the secret
  from which trusted native/backend code derives target-bound session-disposal
  authorization. Raw boot-token use does not authorize session disposal, and
  neither form is a data-plane client credential.
- `AIGUARD_API_KEY` protects data-plane, document, and introspection routes
  when configured. These two trust domains must not be collapsed into one
  health capability.
- `AIFORTHAI_API_KEY` is a provider credential for Pathumma/TNER, not the AI
  Guard caller credential.
- Optional ML/OCR dependencies are not silently installed or silently selected.

Platform-specific HTTP paths, reverse-proxy assumptions, hostnames,
authentication, deployment configuration, and credentials belong in an
adapter/configuration layer. The provisional job envelope stays replaceable.
None of those details may leak into detection or masking code.
