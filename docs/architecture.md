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
Hosted HTTP -----------> hosted port adapter --------------|    detect -> mask
Demo playground -------> demo/API adapter -----------------|    -> guard
CLI -------------------> direct core adapter --------------|    -> provider
Provisional job runner -> worker adapter ------------------/    -> restore
```

The adapters serve three deliberately different lifecycles:

- Local HTTP sessions retain the canonical mapping in backend process memory
  behind an opaque `session_id`, enabling multi-turn restoration on one
  device. Clients necessarily handle the user-submitted and returned text, but
  should receive no explicit mapping DTO and retain no mapping collection.
  Contract v1 nevertheless projects direct or reconstructable mapping fields,
  raw Section 26 match text, and prompt-guard excerpts/rationales into
  first-party client responses; reducing those projections to safe
  category/severity/count metadata is an open contract-v2 gate.
- Hosted HTTP operations are stateless by default. A protected `roundtrip`
  consumes its transient mapping before returning, and normal hosted responses
  must not return the mapping.
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
the residual half at the shared core and direct-provider adapter boundaries:
structured FP findings, text-based TB findings, detector-independent
contiguous runs of six or more digits, and missing replacement records all
fail closed. Caller mappings cannot reuse empty, identity, embedded-original,
source-pre-existing, or independently residual-looking pseudonyms; a reused
token must also match the product token shape for the detected data type. The
CLI repeats the scan immediately before each outer `provider.complete()`
invocation; a self-retrying provider receives one outer validation before
resending the same immutable masked text. HTTP and worker roundtrip repeat it
immediately before their direct calls. Current evidence is source-level
automation plus a generic packaged-sidecar health/synthetic-sanitize smoke,
not acceptance of an installed client or real-host composition. Contract v1
still exports mapping-bearing fields plus raw Section 26 match text and
prompt-guard excerpts/rationales, first-party clients are not strict v2
clients, and fixed-port identity remains unauthenticated. CORS and
`TrustedHost` restrict browser request context and host headers; they do not
establish server identity. Contract v2, fresh client/package acceptance, and
the native broker remain open hardening gates.

Session expiry is request-driven: there is no wall-clock sweep; cleanup occurs
when that known session is accessed, through capacity-driven LRU eviction, or
through explicit/process lifecycle. A session ID is a security-sensitive,
bearer-like restoration reference on the unauthenticated v1 local data plane.
Desktop sanitization does not consistently reuse its previous session, while
extension tab close and Office reset clear client references without
authenticated backend disposal. The broker/lifecycle work must not introduce
or retain an unauthenticated disposal path.

Local sanitize runs under the existing coarse `RLock`. A complete detached
session state is staged through masking, residual scanning, response
projection, Section 26, guard projection, JSON rendering, and required
process-audit work, then published through one `_sessions` assignment. An
exception before that assignment discards staged references without changing
the published graph or capacity/LRU state. Known-session expiry disposal is
lifecycle cleanup outside this rollback guarantee. Cleanup of a replaced or
evicted vault happens after publication and is best effort; it cannot turn an
already-published success into a caller-visible failure. Immutable entity,
mapping, and internal-audit records permit detached containers to share prior
values without a growing deep-copy cost. A clear generation and lifecycle lock
prevent a stale provider rollback snapshot from reviving disposed mappings.

## Trust boundary B - hosted platform

Calling a hosted AI Guard service necessarily sends the request to the hosting
platform. The raw input therefore reaches the platform boundary and the AI
Guard container. The current main-repository source keeps roundtrip mappings
transient and omits the literal mapping dictionary from its roundtrip result,
but v1 still projects token-bearing entities with original-space offsets that
permit reconstruction against caller-held source text. It rejects sanitizer
residuals and repeats the fail-closed scan immediately before a direct provider
call. Automated tests also assert PII-free application errors and logs. The
sibling port's v1 roundtrip likewise consumes its literal mapping internally
but returns the same reconstructable entity projection; its pre-F09 outbound
policy and official platform logs remain unaccepted. The intended hosted
boundary therefore remains:

- no mapping persistence to disk;
- no user text or raw PII in application logs or public error messages;
- no mapping in an approved hosted HTTP result;
- outbound text passes the shared policy immediately before provider use; and
- container restart may intentionally discard transient restoration state.

The hosted product must never reuse the local slogan "PII never leaves the
device". Current source requires text to pass the current outbound-policy
checks before its provider calls, but the historical live and platform
evidence predates this change and must be rerun. Until that exact hosted
composition passes, public
claims remain limited to **AI Guard is designed not to persist the transient
mapping and to send policy-checked masked text to its configured downstream
provider**. The current sibling port uses Tokenmind as a local candidate;
source tests and that candidate are not claims of official deployment
acceptance.

## Core processing layers

1. Ingest and normalize text or PDF content while preserving coordinates where
   redaction requires them.
2. Detect structured PII with regex/checksum rules and free-form PII with Thai
   NER/context logic.
3. Resolve overlaps centrally before any replacement.
4. Replace values with tokens or realistic surrogates.
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

A caller-supplied prior mapping is a declaration, not proof that its key is a
safe pseudonym. Seeded values do not silence FP, TB, or independent digit
findings merely because the caller named them. A seeded value that independently
triggers the residual policy is not reused; token mode also requires the
product token shape for the detected data type. Surrogate generation can
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
| `app/worker/` | Stateless job operations plus a provisional transport used for local pre-platform acceptance; not the official HTTP delivery path. |
| `extension/` | MV3 browser extension and supported-site adapters. |
| `desktop/` | Tauri shell, static UI, updater, and sidecar lifecycle. |
| `office-addin/` | One TypeScript task pane with Word, Excel, and PowerPoint host adapters. Its intended retained state is display text plus a security-sensitive `session_id`, with no explicit mapping collection; current contract-v1 response objects violate that projection boundary and require an atomic v2 migration. |
| `demo/` | Opt-in demonstration UI; not a separate production frontend. |
| `benchmark/` | Diagnostic corpora, scorers, and engine comparisons. |
| `research/` | Privacy-reviewed external evidence and reproducibility records; not a runtime package. |
| `training/` | Optional, gold-disjoint training inputs and lexicons; model weights stay outside the repository. |
| `examples/` | Synthetic prompts, sample documents, and reproducible example builders. |
| `assets/` | Published documentation/store artwork and other intentionally shipped visual assets. |
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
- `AIGUARD_NER_ENGINE` selects a process-wide NER implementation.
- `AIGUARD_TOKEN` is local control-plane authority for shutdown and session
  disposal when configured; it is not a data-plane client credential.
- `AIGUARD_API_KEY` protects hosted declared data-plane endpoints when
  configured. These two trust domains must not be collapsed into one health
  capability.
- `AIFORTHAI_API_KEY` is a provider credential for Pathumma/TNER, not the AI
  Guard caller credential.
- Optional ML/OCR dependencies are not silently installed or silently selected.

Platform-specific HTTP paths, reverse-proxy assumptions, hostnames,
authentication, deployment configuration, and credentials belong in an
adapter/configuration layer. The provisional job envelope stays replaceable.
None of those details may leak into detection or masking code.
