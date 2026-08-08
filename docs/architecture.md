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
CLI, HTTP/hosted roundtrip, and worker roundtrip now reach provider I/O through
the same orchestration function. It repeats the scan immediately before every
actual provider invocation, passes the same immutable masked text each time,
and owns the complete retry policy: at most three 60-second attempts with fixed
one- and two-second delays. Only timeouts, network failures, HTTP 429, and HTTP
5xx are retried. Provider validation, malformed/non-text responses, other 4xx
responses, restore failures, and response-tail defects do not re-enter the
provider. Tokenmind performs one HTTP request per `complete()` invocation and
does not interpret `Retry-After`. Current provider-orchestration evidence is
source-level automation only. The earlier packaged-backend and Office HTTPS
proxy preflight predates this change and did not exercise a provider. Fixed-port
identity remains unauthenticated. CORS and
`TrustedHost` restrict browser request context and host headers; they do not
establish server identity. Fresh client/package acceptance and the native
broker remain open hardening gates.

### Native broker control-plane boundary

Phase 8 Slice 1 defines broker protocol v1 independently from product
`VERSION`, HTTP v2, and worker v1. Its canonical JSON framing, mandatory hello,
closed role/operation table, safe errors, size/deadline table, and non-replay
semantics are fixed in
[`docs/native-broker-protocol-v1.md`](native-broker-protocol-v1.md) and the
single machine-readable policy at
[`native-broker/protocol-v1.json`](../native-broker/protocol-v1.json).

The shared policy also defines closed nested success schemas for every v1
operation. Unknown fields fail at every depth; decimal-valued HTTP results
cross the broker wire only as canonical decimal strings after the future data
plane has validated the complete HTTP-v2 projection.

The pre-hello decoder accepts one frame under a 4 KiB allocation cap; a fresh
post-hello decoder is required after negotiation. Connection validation is
bounded to 4,096 complete messages. Remote TNER is source-only for broker
`detect`, `analyze`, and `analyze_report`; it is disabled without fallback for
sanitize, reidentify, roundtrip, and PDF because the current paths can scan
non-source or unbounded intermediate text. Local multiphase operations carry a
200,000-code-point intermediate-detector cap and terminal phase/operation
budgets for Slice 3 to enforce.

Slice 2 implements the native control plane without enabling a broker data
operation. Windows uses one shared named pipe for the current logon session
across accepted installations, with an explicit protected DACL containing only
the current logon SID,
remote-client rejection, and kernel client/server PID plus token inspection
while a stable process handle is held. An install-independent named kernel
mutex and first-pipe ownership close simultaneous-start races. macOS and Linux
use one canonical per-UID filesystem UDS namespace under a verified private
`/tmp` child directory, with a `0600` lock and socket and `0700` directory,
non-following lock creation, inode-checked cleanup, and a held advisory lock. Linux
requires `SO_PEERCRED`, a stable `pidfd`, and `/proc` executable identity;
macOS requires `getpeereid`, a stable audit token/PID version, and `libproc`
executable identity. Missing platform evidence or an insecure/substituted path
fails closed; there is no abstract socket or localhost client fallback.

The hello `claimed_role` is never identity. Central admission keeps the
transport-authenticated OS context, manifest path/build/digest evidence,
claimed role, and manifest-admitted role separate. The exact package role must
match before negotiated state exists. These are package-consistency checks,
not publisher attestation or cryptographic application authentication; the
boundary does not claim protection from arbitrary malicious code already
running as the same OS user, a compromised OS account, or replacement of an
unsigned installation.

The broker owns one backend process and binds its random `127.0.0.1` listener
before starting it. It transfers a duplicate listener plus independent
per-boot data/control credentials through an inherited channel, retains the
listener guard, and supervises the child with a Windows kill-on-close Job
Object or a Unix process group plus parent-death enforcement. The Python
private entry point consumes those values once in memory and serves the
existing strict HTTP-v2 app only on the transferred listener. Native
publication contains only the pipe name or UDS path; it never contains the
backend address, listener, or either credential.

Slice 2 exposes protocol-v1 hello, `broker_health`, and maintenance-only
`maintenance_drain_stop`. Health verifies the managed backend's exact product,
HTTP contract, and authentication capabilities but is not an HTTP passthrough.
Every data/session/document/provider operation remains disabled. There is no
Chrome adapter, Extension change, Tauri command, Desktop migration, Office
change, session ownership/disposal, or broker forwarding. Existing storefronts
therefore still use their prior paths until later accepted slices. There is no
broker `backend` role; mappings remain Python-owned, and Office, CLI, hosted
HTTP, worker v1, and the demo remain outside broker protocol v1.

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
fail-closed scan immediately before every actual provider invocation through
the shared orchestration layer. Automated tests also assert PII-free
application errors and logs. This remains a generic hosted
reference, not the AI for Thai deployment vehicle. The accepted platform
decision selects a separate sibling repository, not an independently versioned
service. Its public unversioned and `/v1` aliases proxy strict HTTP contract 2,
and its inherited product metadata is not hosted-release evidence. The official
guide confirms its frontend/API proxy, port, health, CI, resource, log, and
secret shape but does not prescribe business routes or caller auth. The
[accepted caller-auth ADR](decisions/2026-08-07-aift-caller-authentication.md)
keeps static/health public and gates every business operation with a
short-lived signed cookie. Nginx separately injects contract 2 plus the
proxy-to-core key. The sibling now vendors current core `8c6efef`, consumes its
literal roundtrip mapping internally, and returns the minimized v2 projection
without mapping or token-bearing entities. Immutable port commit `e075ca4`
passes exact provider-free local check/deploy and independent review. Live
Tokenmind/soak/OCR evidence predates that final commit, and its exact one-page
PDF resource profile is a red deployment gate. Credential rotation, official
platform logs, and platform acceptance remain unverified. The intended hosted
boundary therefore remains:

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

Protected provider orchestration has one core choke point. The CLI pipeline,
HTTP/hosted roundtrip, and worker roundtrip all call
`complete_provider_with_retry_policy()`, whose single-attempt primitive is
`complete_provider_call()`. A caller-specific callback runs the outbound policy
immediately before each actual invocation. The shared layer caps execution at
three attempts, passes a fresh 60-second timeout to each, sleeps for fixed
one- then two-second delays, and retries only timeout, network, HTTP 429, and
HTTP 5xx failures. It passes the same immutable system and masked-user strings
on every invocation and never selects a fallback provider. Tokenmind performs
exactly one HTTP request per `complete()` invocation; it has no internal
deadline, retry sleep, or `Retry-After` handling.

The adapters retain their different lifecycle and wire duties. The CLI keeps
its pre-call vault snapshot and rolls back after a provider attempt fails or a
later pre-attempt check blocks. HTTP and worker keep their transient mappings
inside one stateless request. HTTP v2 and worker envelope v1 translate the
shared fixed failure metadata into their existing error shapes. Provider-call
exceptions are reduced and scrubbed inside the single-attempt primitive; each
outer adapter discards its caught fixed exception before emitting a fresh
value-free failure. Response validation, restoration, and other tail work
remain outside the retry loop.
Likewise, explicitly selected remote TNER receives raw pre-mask chunks. Current
source makes it the fail-closed exception to the shared NER chunk guard:
configuration, dependency, network, or upstream unavailability aborts the
whole operation as `ner_unavailable`, while malformed, unequal, misaligned,
truncated, illegal-BIO, or unknown-label token streams abort as
`ner_incomplete`. The client requires ordered tokens to cover every
non-whitespace source character, and source-position span ends preserve
internal whitespace that a tokenizer omits. Earlier candidates are discarded,
later chunks and providers are not called, and no PDF output or session is
published. The shared BIO/chunk engines (`thainer`, WangchanBERTa, and union)
retain structural skip-and-continue behavior; the separate fine-tuned offset
engine is outside this change. Core wrappers copy only fixed
code/category/count metadata before clearing the original exception graph;
retryability is derived from the locked code/category pair. HTTP v2 derives its
fixed 502/503 envelope and worker v1 keeps its fixed type/message envelope.
This is automated source evidence only: fresh live TNER
response-shape/mapping acceptance remains open. Shared provider orchestration
likewise has automated source evidence only; current live-provider, packaged,
real-host, and official-platform acceptance remains open.

PDF extraction carries geometry and canonical source provenance together.
Every returned PDF `WordBbox.source_span` is a half-open Python Unicode
interval whose slice in the returned extraction text equals the box text.
pdfplumber builds both from its character-to-text map; pdfium assigns offsets
while consuming its character stream and explicitly maps CRLF to LF; retained
OCR fragments receive offsets when they enter page text; and page joining
shifts every local interval by the exact inserted separator length.

`redact_pdf()` selects boxes only where `Entity.span` intersects those
intervals. It validates span/text length, length-preserving Thai-digit
equivalence, page and finite geometry, conflicting-page coverage, and coverage
of every non-whitespace entity character. Missing, malformed, inconsistent, or
incomplete provenance raises one fixed value-free error before any output is
written. There is no document-, page-, normalized-, or fuzzy-value search
fallback. Flatten-to-image output, opaque padding, lossless palette output,
the existing coordinate system, and the no-deskew rule remain deliberate.
Fallback/retry paths and the public provenance boundary clear caught exception
graphs before fixed translation. This is current-source automated evidence;
optional live OCR, physical scans, handwriting, hosted resource behavior, and
real-host acceptance remain separate gates.

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
| `native-broker/` | Broker-v1 Rust codec plus the Slice 2 broker executable, central admission, strict component manifest, Windows named-pipe and macOS/Linux filesystem-UDS transports, control-only client, single-instance ownership, backend bootstrap/supervision, and health/lifecycle tests. It has no data plane, session store, or storefront bridge. |
| `native_broker_protocol.py` | Transport-free Python reference implementation of the same broker-v1 policy and shared fixture behavior; not a server or packaged runtime path. |
| `native_broker_backend.py`, `app/private_backend_bootstrap.py` | Broker-private Python bootstrap: receives a prebound listener and one-use in-memory data/control credentials through inherited OS state, then starts the existing HTTP-v2 app. It is not a storefront endpoint or native protocol adapter. |
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
- Broker protocol version `1` is independently negotiated and is not inferred
  from product `VERSION`, HTTP contract version, or worker envelope version.
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
