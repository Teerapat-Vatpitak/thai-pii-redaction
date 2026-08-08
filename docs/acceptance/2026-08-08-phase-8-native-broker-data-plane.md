# Phase 8 native-broker data plane, ownership, and disposal

- Evidence date (Asia/Bangkok): `2026-08-08`
- Clean base commit: `df5e0f3cd41574b4434752618ba548ffe23c6058`
- Candidate branch: `codex/phase-8-native-broker-data-plane`
- Product version: `2.5.0` (unchanged)
- Status: **local Windows/WSL2 verification and independent security review
  passed; exact-head CI pending**

This record covers Slice 3 only: strict forwarding from an authenticated
protocol-v1 connection to the broker-private HTTP-v2 backend, connection and
scope ownership, broker session handles, confirmed disposal, terminal
uncertain-completion handling, broker deadlines/cancellation, backend
generation invalidation, and bounded data-plane resources.

It does not migrate Desktop, the Extension, Chrome Native Messaging, Office,
an installer, registration, packaging, updates, or any storefront. It adds no
PII, provider, detector, PDF, or protocol operation and does not change product
`VERSION`.

All test values and evidence are synthetic and non-sensitive. Captured output,
errors, fixtures, and this record must not contain request or response text,
masked or restored values, mappings, backend session identifiers, credentials,
private endpoints, provider bodies, exception graphs, or machine-specific
paths.

## Data-plane invariants

1. Strict protocol-v1 validation and the authenticated role/operation matrix
   run before scope lookup or forwarding.
2. A scope is issued by and belongs to one authenticated connection. A scope
   identifier has no authority on another connection or after close.
3. A stateful broker session handle belongs to one connection, one live scope,
   one admitted role, and one backend generation. Possession or guessing of a
   handle alone grants no authority.
4. A broker handle is never a Python backend session identifier. The broker
   retains only the backend identifier and ownership/lifecycle metadata needed
   for enforcement. Mapping content remains exclusively in Python
   `SessionService` memory.
5. Reconnect, scope close, explicit disposal, connection close, backend death,
   broker shutdown, and generation change never preserve session authority.
6. Stateful operations are serialized by their owning connection/session.
   Independent connections and stateless work may proceed concurrently within
   fixed global and per-role admission limits; there is no broker-wide data
   operation lock.
7. HTTP-v2 remains private and authenticated. No client receives or can infer
   its listener, data key, control token, disposal authorization, or backend
   session identifier. There is no localhost or provider fallback.
8. The broker validates the exact HTTP-v2 status/header/body contract and all
   cross-field DTO invariants before converting finite numeric values to the
   protocol-v1 decimal-string representation. An oversized valid `200`
   response projects `payload_too_large` with operation-specific cleanup;
   an oversized non-success response is an integrity failure because its fixed
   error envelope could not be validated.
9. Broker-only authenticated HTTP context carries the remaining outer budget,
   local detector-phase count, intermediate-text cap, and phase budget. Python
   installs it in a private context variable, and the authoritative detector
   entry points enforce the 200,000-code-point cap before every phase. A phase
   or outer watchdog that expires terminates the managed backend without
   logging values, so cancelled work cannot continue outside broker admission.
10. A data request is never retried or replayed. The shared Python provider
   orchestration remains the only retry owner.
11. A definitely unsubmitted request has no backend side effect. A confirmed
    fixed backend failure follows the existing transactional/session semantics.
    A confirmed success is published only after complete broker validation.
    Submitted work with unknown completion is never treated as either case.
12. Unknown new-session publication and unconfirmed request-transient mapping
    cleanup terminate the backend and globally invalidate its generation.
    Unknown mutation of a known session first invalidates its broker handle and
    requires confirmed authenticated disposal; failure to confirm also
    terminates the backend and invalidates every handle. Submitted-unknown
    stateless work also tears down the generation so it cannot run after its
    operation permit is released.
13. Explicit session disposal, scope close, connection close, and shutdown
    remove broker authority before cleanup starts. A disposal rejection,
    timeout, lost response, malformed response, or transport failure can never
    be guessed into success. Concurrent generation invalidation is an error,
    never a fabricated `disposed: false`, and terminal cleanup preserves
    timeout/cancellation precedence after fail-safe teardown.
14. The protocol-v1 monotonic outer deadline is selected by the broker. A
    timeout or observable client disconnect cancels transport work; if bytes
    may have reached the backend, uncertain-completion policy applies and the
    request remains non-replayable.
15. A complete, schema-validated native success envelope is built before any
    state is committed. Its bounded publication lease retains global/per-role
    admission until the final native write succeeds or fails, preventing large
    replies or slow readers from escaping concurrency accounting.
16. Remote TNER remains the existing explicitly selected Python detector.
    Broker v1 permits it only for `detect`, `analyze`, and `analyze_report`,
    applies the fixed 500-code-point/501-call-derived profile, and never retries,
    substitutes, or broadens that path.
17. PDF input is decoded only after protocol validation, remains under the
    exact 50 MiB/raw and framing limits, and is forwarded to the existing PDF
    route without reimplementing selection, OCR, source intervals, or
    flattening.
18. Windows uses nonblocking byte mode on both named-pipe ends and bounded
    64 KiB write chunks. Slow or zero-progress readers are retried only until
    the existing absolute deadline; the exact 70,953,644-byte maximum frame is
    not truncated, a never-reader returns only `operation_timeout`, and a dead
    peer is detected promptly so session cleanup and the publication lease do
    not remain pinned to a long operation deadline.
19. Scope/session tables, request admission, backend response buffers, and
    connection counts are bounded. Limit failures are fixed and value-free.
20. Operational errors and debug representations use only the Slice 1 fixed
    taxonomy and safe structural metadata. They never include payload-derived
    values or backend authority.

## Operation classification

| Operation | Broker classification | Existing backend state semantics |
|---|---|---|
| `broker_health` | PII-free control | Broker/backend health only; automatically repeatable only as startup work |
| `scope_open` | connection-state mutation | Creates only bounded broker ownership metadata |
| `scope_close` | terminal scope operation | Invalidates the scope and disposes all of its backend sessions |
| `session_dispose` | terminal session operation | Invokes target-bound authenticated Python disposal |
| `detect` | stateless, scope-bound | No `SessionService` mapping; optional explicit remote-TNER source call |
| `analyze` | stateless, scope-bound | No `SessionService` mapping; optional explicit remote-TNER source call |
| `guard` | stateless, scope-bound | Local warn/report scan only |
| `sanitize` without `session_id` | session creation | Atomically publishes one Python session only on confirmed success |
| `sanitize` with `session_id` | session mutation | Atomically replaces the owned Python session graph on confirmed success |
| `reidentify` | session mutation | Uses the owned Python session and refreshes retention only after success |
| `roundtrip` | stateless with request-transient mapping/provider use | Mapping is created, consumed, and cleared inside one Python request |
| `analyze_report` | stateless artifact operation | No session; optional explicit remote-TNER source call |
| `redact_pdf` | stateless document operation | Existing bounded temporary-file/PDF path; no `SessionService` mapping |
| `audit_log` | stateless scope-bound read | Existing minimized private audit projection; no broker correlation identifier |
| `maintenance_drain_stop` | global maintenance control | Existing Slice 2 maintenance-only lifecycle operation |

Every operation except PII-free startup/hello/health is non-replayable. The
classification does not make an HTTP stateless operation stateful, and it does
not make a Python session globally reusable broker state.

## Explicit non-goals

- No storefront, Tauri, Extension, Chrome adapter, Office, installer, native
  registration, package, updater, release, deployment, or Slice 6 change.
- No new protocol-v1 field, operation, role, error, limit, or deadline.
- No Rust detection, sanitization, provider, mapping, restore, audit, TNER, or
  PDF algorithm.
- No worker-v1, hosted, CLI, provider registry, retry, fallback, or detection
  behavior change.
- No product-version bump and no claim of installed/storefront/live-provider
  acceptance.

## Tests-first ledger

The Slice 3 acceptance record and adversarial Rust test target were added before
the production data-plane module. `cargo test --test slice3` failed at
compilation with unresolved imports for the deliberately absent
`aiguard_native_broker_protocol::data_plane` module and its types. No Slice 3
assertion could pass. The acceptance contract and adversarial test tree
therefore preceded production implementation.

After the connection-owned state machine passed its focused tests, the real
managed-backend acceptance target was added before its production adapter.
`cargo test --test slice3_backend` then failed at compilation because the
deliberately referenced `managed_backend_executor` did not exist. This pins the
private HTTP-v2 forwarding seam before it is implemented.

The authenticated end-to-end runtime test was then changed to require
`scope_open` followed by `detect` over native IPC. Its focused run failed at
the missing scope result while the Slice 2 control-only dispatcher was still
active, before the runtime was connected to the new data plane.

Security-review regressions were also added before each corrective change.
They first proved that detector budgets were absent from Python execution,
submitted-unknown stateless work could outlive admission, and a publication
permit ended before the native response write. Later red tests pinned valid
oversized-success projection, oversized non-success integrity failure,
bidirectional Windows named-pipe backpressure, connection teardown with live
sessions, and the full-envelope publication lease. The final two red tests
reproduced a concurrent invalidation that returned `disposed: false` without a
confirmed DELETE and terminal cleanup that returned `operation_failed` after
cancellation; both now fail closed with the fixed terminal error.

## Adversarial coverage map

| Required boundary | Deterministic evidence |
|---|---|
| Valid stateless, session creation, continuation | Direct projection tests, real managed-backend lifecycle, and authenticated native-IPC detect/sanitize/reidentify/dispose |
| Cross-connection, cross-scope, guessed, stale, reconnect | One ownership test uses the same handle across distinct connections/scopes and after disposal/reconnect; every rejection is value-free |
| Explicit disposal, scope close, connection close | Separate tests remove authority first, confirm each backend disposal, and reject every later use |
| Not submitted, confirmed failure, confirmed success, unknown | Scripted completion variants and real TCP fault injection keep all four states distinct |
| New sanitize loss, existing mutation loss, roundtrip loss | New/transient uncertainty tears down globally; known-session uncertainty removes the handle and requires one confirmed disposal |
| Disposal response loss, timeout, partial completion, crash | Every unconfirmed disposal tears down the backend generation without a second attempt; concurrent invalidation cannot fabricate confirmed absence and terminal timeout precedence is deterministic |
| Backend crash and forced restart | Operation/runtime crash tests invalidate all handles; real forced cycles prove fresh generation and bounded resources |
| Deadline expiry and cancellation races | Pre-submit cancellation, submitted timeout, post-success cancellation, monotonic outer deadlines, Python phase/outer watchdogs, terminal cleanup races, and late-publication races are separate tests |
| Malformed HTTP, v2 mismatch, backend authentication failure | Exact header/body framing, duplicate-free JSON, cross-field validation, exact authenticated failure, and integrity teardown are pinned |
| Role violation and request-ID reuse | Slice 1 validation consumes IDs and rejects unauthorized operations before any backend call |
| No replay | Real one-accept response-loss test plus scripted call counts prove no request or disposal is sent twice |
| Bounded state and concurrency | Scope/session/role caps, eight-global/four-role operation admission held through publication, 16-connection transport admission, 64 reconnect cycles, slow/never/dead readers in both Windows directions, and live resource counters |
| PDF and remote TNER | Exact 50 MiB raw PDF forwarding and 70,953,644-byte native frame plus canonical 500-character/501-call/7,520,000 ms remote-TNER limits; disallowed operations remain Slice 1 regressions |
| Value-free failures/logs/debug | Synthetic sentinel scans plus existing HTTP-v2/Uvicorn privacy regressions; broker production code emits no payload-derived operational log |

## Required evidence ledger

| Gate | Result |
|---|---|
| Tests-first Rust compile | EXPECTED FAIL — the deliberately referenced `data_plane` module and types did not exist |
| Tests-first managed-backend compile | EXPECTED FAIL — the deliberately referenced `managed_backend_executor` did not exist |
| Tests-first native-IPC data dispatch | EXPECTED FAIL — authenticated `scope_open` reached the existing Slice 2 control-only dispatcher and returned no result |
| Focused Slice 3 Python tests | PASS — 17 broker data-plane/private-context tests passed with two expected Unix-only skips; 163 combined protocol/backend/data-plane tests passed with the same two skips |
| Focused Slice 3 Rust tests | PASS — 33 deterministic ownership/fault/concurrency groups, eight private-backend executor fault/projection unit tests, and three real managed-backend lifecycle/cancellation/resource tests |
| Slice 1 protocol/conformance regression | PASS — 20 Rust conformance groups and the Python protocol suite inside the 163-test focused run |
| Slice 2 bootstrap/runtime regression | PASS — complete Windows and real WSL2 native suites, including transport, admission, bootstrap, broker runtime, backend ownership, and resource gates |
| Windows native runtime | PASS — 111 tests/groups passed and five subprocess fixtures were intentionally ignored; authenticated native IPC performed detect/sanitize/reidentify/roundtrip/PDF/dispose, both named-pipe directions passed slow/never/dead-reader tests, and the exact maximum frame passed |
| Linux/WSL2 native runtime | PASS — 110 tests/groups passed and five subprocess fixtures were intentionally ignored on Linux 6.18; UDS/peer/descriptor/process paths plus the real data plane ran from an isolated Linux target against an explicit fresh Python environment |
| macOS native runtime | PENDING |
| Full Python suite | PASS — 2,495 passed, seven expected optional/platform skips, and one existing Starlette/httpx deprecation warning |
| Root JavaScript suite | PASS — 123 tests across 16 files plus Desktop JavaScript syntax checks |
| Desktop Rust suite | PASS — 31 tests; no Desktop source changed |
| Office gates | PASS — unified/local/upstream manifests, live XML schema validation, package manifest, TypeScript, 129 tests, and production build; no Office source changed |
| Ruff, rustfmt, warning-as-error Clippy | PASS — Ruff checked/formatted 229 Python files; native-broker rustfmt and all-target Clippy passed |
| Dependency/static/security checks | PASS with pre-existing development-tool debt recorded below — `pip check`, RustSec for all 33 locked broker crates, workflow/lock checks, Office TypeScript, and zero root/Office production npm advisories passed |
| Version/release/documentation checks | PASS — synchronized `2.5.0`, both scripts, and 59 lock/workflow/version/release/documentation/container tests |
| Performance/resource matrix | PASS against the exact integrated base; the pre-existing stale formal anchor remains red as explained below |
| `git diff --check` and final privacy/scope audit | PASS locally — no storefront dependency, protocol/`VERSION` drift, mapping copy, retry/replay layer, HTTP/provider fallback, payload-derived diagnostic, or exposed endpoint/credential was found |
| Independent security review | PASS — separate-context review of the complete current diff has no unresolved security or correctness finding; reviewer reruns passed 33/33 Rust and 17 Python tests with two expected skips |
| Exact-head branch CI | PENDING |
| Main integration and post-main CI | PENDING |

## Performance and resources

The formal in-process harness remains red against its old absolute sanitize
anchor on both the candidate and exact integrated base commit. Three
alternating 20-iteration runs against clean base
`df5e0f3cd41574b4434752618ba548ffe23c6058` distinguish that stale anchor from
branch impact:

| Operation | Clean-base median | Candidate median | Candidate delta |
|---|---:|---:|---:|
| Detect | 5.77 ms | 5.80 ms | +0.5% |
| Sanitize | 15.61 ms | 15.63 ms | +0.1% |
| Restore | 0.22 ms | 0.23 ms | +4.5% |
| PDF redact | 71.96 ms | 72.92 ms | +1.3% |
| Resident memory | 153.9 MiB | 154.8 MiB | +0.6% |

Every branch delta is inside the repository's 20% time and 15% resident-memory
budgets. The committed baseline was not moved.

The final real private-backend loop covers 24 detect calls, 24 complete
sanitize/reidentify/dispose cycles, eight fake-provider roundtrips, and three
PDFs. On Windows it measured 129/436/87/2,708 ms respectively, 796,681 us of
measured broker forwarding overhead, zero process-handle growth, and 12,288
bytes of broker RSS growth. WSL2 measured 45/374/69/1,373 ms, 361,954 us of
overhead, zero descriptor growth, and zero RSS growth. An independent reviewer
also reran the Windows matrix (105/387/87/2,910 ms, 868,815 us overhead, zero
handle growth, 69,632 bytes RSS growth).

Authenticated native IPC exercises the same detect, sanitize, reidentify,
roundtrip, PDF, and disposal route; its representative PDF response was
5,331,037 bytes. Separate Windows and WSL2 transport tests forward the exact
70,953,644-byte protocol maximum frame. Three forced teardown/restart cycles
after warmup produced a distinct backend generation every time and stayed
within one handle/file descriptor and 64 MiB RSS. The existing three-cycle
graceful bootstrap/teardown resource gate also passed on both platforms.

Read-only dependency audits found no production npm advisory and no RustSec
advisory in the native-broker lock. The unchanged development trees report two
root advisories (one high, one moderate) and 20 Office advisories (13 high,
seven moderate). This branch changes neither JavaScript dependency tree; the
findings are recorded without claiming those development tools are
vulnerability-free.

## Independent security review

A separate-context reviewer inspected the complete Slice 3 diff for session
ownership, connection/scope isolation, Python-private mappings, unauthorized
reuse, confirmed disposal, uncertain completion, non-replay, generation
invalidation, disconnect/crash races, deadline/cancellation behavior, HTTP-v2
projection, privacy/error containment, bounded resources, storefront scope,
and duplicated core/provider logic.

The review first found missing Python intermediate-phase enforcement,
unaccounted submitted-unknown stateless work, early publication-permit release,
and insufficient real teardown coverage. Corrective tests now pin authenticated
operation context and detector watchdogs, generation teardown for submitted
uncertainty, a lease through the final native write, and real EOF/malformed/
shutdown cleanup.

Follow-up review found oversized-response classification, bidirectional Windows
pipe backpressure, stale performance evidence, concurrent disposal
confirmation, and terminal timeout-precedence defects. Later exact probes also
found that a dead Windows peer retained a large write until the full deadline.
Each finding received a red regression before its fix: valid oversized `200`
and invalid oversized non-success bodies are distinct; both pipe ends are
nonblocking and bounded; slow, never-reading, and dead peers are distinct in
both directions; invalidated/generation-mismatched disposal cannot return
success; and session/scope cleanup preserves cancellation or timeout after
teardown. The reviewer independently reran the final 33-group Slice 3 Rust
target, the 17-test Python broker data/context/backend set, the six Windows
large-write cases, and `git diff --check`, then reported no unresolved finding.

## Acceptance boundary

A future green record establishes the Slice 3 source/runtime data plane and its
fault semantics only. It cannot establish Desktop or Extension migration,
Chrome native-host behavior, installed packaging, Office support, live-provider
behavior, deployment, release, or upgrade recertification. Those remain Slice 4
or later work.
