# Phase 8 native-broker protocol and cross-language conformance

- Evidence date (Asia/Bangkok): `2026-08-08`
- Clean base commit: `3c1ec602b396e03411636d26858f34c5fcf0c8a3`
- Candidate branch: `codex/phase-8-native-broker-protocol`
- Product version: `2.5.0` (unchanged)
- Status: **local candidate complete; independent review passed; branch CI and integration pending**

This record covers Slice 1 only: broker protocol v1, its strict canonical
framing/envelopes, hello negotiation, closed role/operation policy, safe
errors, deterministic limits/deadlines, no-data-replay semantics, and shared
Python/Rust conformance fixtures.

It does not create a named pipe, UDS, Chrome native host, Tauri command,
listener, backend bootstrap, credential path, OS peer inspection, session
store, data-plane forwarding, lifecycle owner, retry loop, storefront
migration, Office integration, installer, package, release, or deployment.

All fixtures use obvious synthetic non-sensitive values. This record and its
artifacts contain no request or restored PII, masked user text, mapping,
credential, provider body, exception graph, backend authority, or
machine-specific secret/path.

## Contract established

The normative contract is
[`docs/native-broker-protocol-v1.md`](../native-broker-protocol-v1.md), backed
by the single machine-readable policy table in
[`native-broker/protocol-v1.json`](../../native-broker/protocol-v1.json).

The contract fixes:

- four-byte big-endian framing over canonical UTF-8 JSON objects;
- mandatory highest-common-version hello with no silent fallback;
- an explicit `claimed_role` that must match a separately supplied
  authenticated role and is never accepted as identity by itself;
- `desktop`, `extension`, and least-authority `maintenance` roles, with no
  backend or Office protocol role;
- exact request/success/error envelopes and single-use per-connection request
  IDs, including consumption of a valid ID before later request rejection, plus
  a terminal 4,096-message connection cap that counts malformed attempts;
- a dedicated single-frame, 4 KiB pre-hello decoder that rejects oversized
  declarations before body copy and forbids request pipelining before decoder
  replacement;
- strict unknown/missing/duplicate-field rejection, including all nested result
  objects and closed result types for every operation;
- a pre-parser 32-container depth ceiling and an exact shared blank-text
  code-point table, avoiding Python/Rust runtime classification drift;
- a closed value-free error taxonomy;
- Python public value validators re-raise only a fresh fixed error after
  discarding raw-bearing traceback graphs; Rust errors carry only fixed code
  and safe correlation metadata;
- limits derived from current HTTP, worker, Chrome, PDF, provider, and TNER
  behavior;
- broker-selected terminal operation deadlines, including local
  intermediate-text/phase budgets and source-only remote-TNER profiles; and
- automatic repeat permission only for PII-free startup/hello/health work.

The sanitize uncertain-completion policy covers both request shapes: a lost
new-session result with no supplied handle requires backend teardown when the
published backend ID is unknown; a supplied handle is a known-session mutation
that requires confirmed authenticated disposal or backend teardown.

HTTP v2, worker v1, provider orchestration, TNER selection/configuration,
mapping ownership, CLI, Office, Extension DOM behavior, and `VERSION` do not
change. The new unpublished Rust crate metadata is synchronized to product
`VERSION`; it is not the broker wire version.

Negotiated connection authority can be created only by a successful hello.
Role and protocol version cannot be rewritten through the public state API,
and safe debug representations omit payloads plus request, scope, and session
identifiers.

## Deadline measurement

The initial 60-second local detection/report draft was rejected during local
verification. A foreground 200,000-character repetitive synthetic Thai report
probe had not completed at its 124-second measurement cutoff. The same
provider-free probe then completed with:

- analysis: `164.741 s`;
- report rendering: `2.230 s`;
- total: `166.972 s`; and
- output PDF: `22,335 bytes`.

The final table therefore preserves the existing 200,000-character HTTP cap
and assigns six minutes to one top-level local detector phase/report path:
twice the measured totals are `329.482 s` and `333.944 s`, rounded upward.
Broker-only intermediate masked, restored, and provider-output detector inputs
reuse that 200,000-character cap. `sanitize` receives two phase caps plus 5 s
(`725 s`); conditional `reidentify` receives one phase plus 60 s
(`420 s`); and `roundtrip` receives six phase caps, three 60-second provider
attempts, the 1+2-second delays, and 5 s (`2,348 s`).

These are authoritative terminal caps, not claims that every current nested
segment rescan completes inside them. Slice 3 must enforce the intermediate,
phase, and outer caps and fail closed. Fast non-detection operations retain a
separate 60-second profile. Remote-TNER deadlines use a separate
500-character cap and a conservative 501-call bound: one primary chunk call
plus at most two retags for each of at most 250 non-empty physical lines. This
covers both the degenerate and multi-span unknown-label retag paths without
assuming that a physical line is retagged only once.

Remote TNER is enabled only for `detect`, `analyze`, and `analyze_report`.
`sanitize`, `reidentify`, and `roundtrip` are disabled with remote TNER because
their current core paths can scan masked, restored, or provider-produced text;
`redact_pdf` remains disabled because extracted text lacks a finite broker cap.
This preserves the ADR's raw-pre-mask-only external TNER boundary. This timing
probe is limit/deadline design evidence, not the repository performance gate;
no measured runtime source changed.

These numbers are terminal broker wall-clock policy caps, not claims that the
current scalar `httpx` values bound total call duration. Those values apply to
individual phases or read inactivity. A later data-plane slice must enforce
the broker's outer monotonic deadline and the ADR's terminal
disposal/backend-teardown rule independently.

## Tests-first evidence

The test/fixture-only tree failed before protocol implementation:

- Python collection stopped with `ModuleNotFoundError` for the deliberately
  absent `native_broker_protocol` module; and
- Rust compiled the declared dependencies, then failed the conformance target
  with unresolved `aiguard_native_broker_protocol` imports because no library
  target existed.

Both failures occurred before a protocol assertion could pass. The fixtures,
contract tables, and tests therefore preceded the Python and Rust
implementations.

## Evidence ledger

| Gate | Result |
|---|---|
| Tests-first Python collection | EXPECTED FAIL — missing `native_broker_protocol` during collection |
| Tests-first Rust collection | EXPECTED FAIL — unresolved protocol crate because no library target existed |
| Focused Python protocol tests | PASS — `146 passed` |
| Focused Rust protocol tests | PASS — `20 passed` conformance groups, two decoder allocation regressions, plus crate/doc targets |
| Shared byte/policy fixture parity | PASS — both languages consume the same fixture/policy files; authoritative hello/request/response frames and all 20 fixed correlated errors match exact bytes; valid vectors cover all 14 deep result schemas and shared mutations pin nested unknown fields, fixed values, decimals, ordering, maps, and base64 |
| Full Python suite | PASS — `2,478 passed`, five expected optional OpenCV skips, existing Starlette/httpx deprecation warning |
| Root JavaScript tests | PASS — `123 passed` |
| Desktop Rust tests | PASS — `31 passed` |
| Office manifest/type/unit/build gates | PASS — repository, local Microsoft XML, and checksum-pinned upstream schema validation; package; typecheck; `129 passed`; build |
| Ruff lint and format | PASS |
| Rust format/clippy | PASS — rustfmt plus all-target warning-as-error Clippy |
| Version/release/documentation checks | PASS — `46 passed`; `VERSION 2.5.0`; release readiness; version/workflow/docs coverage includes the new native-broker Cargo metadata drift target |
| Performance gate | NOT REQUIRED unless a measured `pii_redactor/` or `app/` path changes |
| `git diff --check` and final privacy/scope review | PASS — no protocol ambiguity, Python/Rust policy drift, permissive parsing, role escalation, unsafe error content, replay weakening, transport/bootstrap code, raw data, unrelated change, or version drift remained |
| Independent review | PASS — exact-index read-only review found no remaining actionable blocker after the stale Slice 1 status sentence was corrected |
| Exact-head branch CI | PENDING |
| Main integration and post-main CI | PENDING |

## Acceptance boundary

Passing this record will establish protocol/source conformance only. It cannot
establish authenticated OS peer identity, an installed broker, a private
backend, session ownership/disposal, Chrome or Tauri behavior, a real transport,
or package/real-host acceptance. Those remain Slice 2 or later work.

## Independent review

The independent reviewer audited the exact 19-file Slice 1 index and reran the
focused Python and Rust protocol gates, both format/lint paths, warning-as-error
Clippy, version/release checks, documentation/version tests, and cached-diff
checks. The final pass found no unresolved code, policy, privacy, scope, or
cross-language conformance issue.

Earlier review rounds found and closed strictness and parity gaps around
Python boolean versions, Unicode blankness, rejected-request ID consumption,
deep JSON failures, frame allocation, wrong-container payloads, exhaustive
authorization coverage, bounded connection state, hello-size framing,
value-free Python tracebacks and Rust debug output, PDF base64 byte semantics,
and machine-table startup validation. Execution-path review also corrected
remote-TNER eligibility, terminal deadline claims, intermediate caps, and both
sanitize uncertain-completion branches without changing the existing core or
implementing a data plane.

Runtime admission, transport authentication, deadline cancellation, call-cap
enforcement, session ownership, uncertain-completion cleanup, installed-host
acceptance, and storefront projection remain intentionally deferred. Slice 3
must also validate the complete HTTP-v2 cross-field DTO invariants at the
broker conversion boundary.
