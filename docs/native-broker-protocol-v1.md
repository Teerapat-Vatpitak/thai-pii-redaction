# Native broker protocol v1

- Status: normative Slice 1 contract; runtime Slices 2--5 integrated; the Slice
  6 package/lifecycle closure candidate uses the existing maintenance operation,
  does not change protocol v1, and becomes integrated only when this exact tree
  reaches `main` through its closure protocol
- Protocol version: `1`
- Product version: independent (`VERSION` remains `2.5.0`)
- HTTP contract: independent (HTTP v2 remains unchanged)
- Worker envelope: independent (worker v1 remains unchanged)

This document is the normative human-readable contract for the native broker
protocol selected by
[the accepted native-broker ADR](decisions/2026-08-07-native-broker.md).
The machine-readable policy table is
[`native-broker/protocol-v1.json`](../native-broker/protocol-v1.json).
The shared byte fixtures are under
[`tests/fixtures/native_broker/v1/`](../tests/fixtures/native_broker/v1/).

Slice 1 defines serialization, negotiation, authorization policy, limits,
deadlines, errors, and replay behavior. It does not create a listener, native
host, Tauri command, backend connection, process lifecycle, session store, or
data-plane forwarder. That is the historical Slice 1 boundary: integrated
Slice 2 supplies native transport, authenticated admission, and broker-owned
backend lifecycle, while integrated Slice 3 supplies the data plane, deadline
enforcement, cancellation, disposal, uncertain-completion handling, and
teardown.

The unpublished Rust crate's Cargo package metadata follows product `VERSION`
and is covered by the repository version-drift gate. That build/package value
is informational in hello and never selects wire protocol compatibility.

## Identity boundary

The hello field `claimed_role` is a claim, not authentication. A hello is
accepted only when the Slice 2 admission layer supplies an `authenticated_role`
derived from OS peer/process context and package/platform checks and it exactly
matches the claim. The Slice 1 harness requires that value explicitly so there
is no API that authorizes a caller from its JSON role alone. Negotiated
role/version state is created only by a successful hello and cannot be
constructed from, or mutated to, an arbitrary role through the public
protocol API.

The protocol roles are `desktop`, `extension`, and `maintenance`. There is no
`backend` protocol role. The broker/backend boundary remains private
authenticated HTTP v2 under the accepted ADR; it does not negotiate or accept
broker messages. Office, CLI, hosted HTTP, worker v1, and the demo are not
broker peers.

### Current installed-product profile

This is a runtime/product restriction, not a protocol-v1 wire change. Installed
Desktop and its shared broker accept only local `thainer`; the managed backend's
provider allowlist is `fake` solely for internal conformance. The Desktop
webview has no provider command. An explicit unsupported engine or provider
selector fails before broker connection or launch as the stable,
non-secret `ner_unavailable` or `provider_configuration` error. A Desktop
`roundtrip` conformance request naming a non-`fake` provider fails before
backend submission.

The Desktop-to-broker and broker-to-backend child seams construct their child
environment from a fixed allowlist of ordinary runtime-variable names without
querying provider/TNER credential values, then pin `AIGUARD_NER_ENGINE=thainer`
and `AIGUARD_PROVIDERS=fake`. Desktop and broker do
not snapshot remote configuration independently, so an attaching process cannot
silently reinterpret a warm broker. Protocol-v1 remote-TNER limits and deadlines
remain reserved contract policy, but the current installed runtime never selects
those profiles. Core, CLI, HTTP/hosted, and worker provider/TNER capabilities
remain outside this restriction.

Credential-requiring providers or remote TNER for installed Desktop require a
future owner-approved ADR covering credential ownership, provisioning,
permissions, storage, rotation, configuration identity/epoch, broker restart or
reconfiguration, upgrade, uninstall, attestation, and cross-platform behavior.

## Canonical serialization

Each broker message is one canonical UTF-8 JSON object:

- no BOM, leading/trailing whitespace, or trailing newline;
- object keys sorted lexicographically by Unicode scalar value;
- no insignificant whitespace;
- non-ASCII text encoded directly as UTF-8, not `\u` escapes;
- duplicate object keys rejected at every depth;
- invalid UTF-8, lone surrogate escapes, and non-finite numbers rejected;
- container depth, counting the root object, limited to 32 and checked before
  either language's JSON parser runs;
- protocol numbers are JSON integers in JavaScript's exact range
  `0..9007199254740991`; and
- floating-point JSON numbers are not part of v1. Decimal-valued adapter
  results use canonical non-negative decimal strings such as `"0"`, `"10"`,
  or `"10.5"`. Leading zeros, a trailing decimal zero, and values such as
  `"10.0"` are rejected.

An input that parses but is not byte-for-byte canonical is `request_invalid`.
This gives Python and Rust one fixture representation and removes alternate
spellings such as reordered keys, `1.0`, `-0`, escaped non-ASCII text, or
duplicate semantic fields.

A required text value is blank only when it is empty or every scalar belongs
to the exact `serialization.blank_text_code_points` table. That table pins the
25 Unicode White_Space code points used by v1 rather than delegating to a
language runtime's `strip`/`trim` behavior. In particular, U+001C through
U+001F are not protocol whitespace.

### Framing

The broker stream frame is:

```text
4-byte unsigned big-endian payload length N | N canonical JSON bytes
```

`N` counts only the JSON bytes. Zero-length, partial-header, partial-body, and
trailing bytes at EOF are `request_invalid`. A declared length above the
applicable cap is `payload_too_large` and is rejected before allocating or
reading that body.

Before negotiation, a connection must use the dedicated hello decoder. It
applies the 4,096-byte hello cap to the length prefix, accepts exactly one
frame, and rejects an attached or later pipelined frame as `request_invalid`.
That rejects an oversized declaration before copying any body bytes. Only
after that frame passes hello negotiation may the implementation discard the
hello decoder and create a new post-hello decoder with the applicable message
cap. No bytes buffered or attached under the hello decoder carry across that
switch. Post-hello stream decoders may accumulate partial input and may return
multiple complete frames in order.

This is the broker framing used over the Slice 2 named-pipe/UDS stream. Chrome
Native Messaging keeps its platform-defined native-endian stdio framing. The
Slice 5 adapter validates that outer frame and creates a new broker request;
it never tunnels an untrusted Chrome length prefix. Slice 1 itself still opens
neither transport.

### Chrome Native Messaging adapter

The registered host is `th.ac.psu.aiguard.native_host`. It accepts one exact
build-specific `chrome-extension://<id>/` origin and no wildcard. Before
processing PII-bearing input it validates Chrome's supplied origin argument,
a stable same-user browser parent/process context, its own installed
path/build/digest, and broker admission as role `extension`.

The outer request and response cap is 1,048,576 bytes. Zero, partial, invalid,
or oversized frames; invalid UTF-8; duplicate or unknown JSON fields;
unsupported operations; and incompatible versions fail closed. Stdout is
reserved exclusively for Native Messaging frames. Diagnostics use only fixed
structural event codes and bounded counts/durations on stderr; no request ID,
scope/session handle, text, origin, path, credential, or exception message is
logged.

The Extension subset is `broker_health`, `scope_open`, `scope_close`,
`sanitize`, and `reidentify`. Scope kind is only `extension_tab` or
`extension_panel`. PDF/document bytes, provider operations, remote TNER,
audit, maintenance, mapping values, backend identity/address/credentials, and
arbitrary broker operations cannot enter this adapter path. Only PII-free
connect/hello/health may be retried; a PII-bearing operation is never replayed.

## Mandatory hello

The first complete message is exactly:

```json
{"claimed_role":"desktop","client_product_version":"2.5.0","request_id":"hello-1","supported_protocol_versions":[1]}
```

The keys are:

- `request_id`: an opaque correlation ID matching
  `[A-Za-z0-9][A-Za-z0-9_-]{0,127}`;
- `supported_protocol_versions`: one to eight unique positive integers in
  strictly increasing order;
- `client_product_version`: a bounded informational product-version string;
  and
- `claimed_role`: one closed role.

The broker selects the highest common protocol. The current broker set is
exactly `{1}`. An explicit list such as `[1,2]` selects `1`; `[2]` returns
`broker_incompatible`. Missing, malformed, duplicated, or unordered version
lists are `request_invalid`. There is no product-version heuristic, implicit
downgrade, or HTTP/worker fallback.

Broker v1 has no independently negotiable capability list. The accepted
client classes are represented by the closed authenticated role/operation
policy, so a `capabilities` field is unknown and fails `request_invalid`.
Adding a negotiable capability requires a compatible protocol revision.

The success is exactly:

```json
{"broker_product_version":"2.5.0","broker_protocol_version":1,"request_id":"hello-1","role":"desktop"}
```

`role` is the role bound after the external authenticated role matched the
claim. Product versions are reported for diagnostics/package consistency but
do not select the broker protocol. A second hello or any request before hello
is `request_invalid` and closes the connection.

## Request and response envelopes

A request has exactly these fields:

```json
{"broker_protocol_version":1,"operation":"sanitize","payload":{"mode":"token","text":"synthetic text"},"request_id":"request-1","scope_id":"scope-1"}
```

`scope_id` is present exactly when the operation table requires it. A request
never carries `role`, `authenticated_role`, a deadline, a retry instruction,
backend authority, a port, or a backend session UUID. Role and negotiated
version come from connection state; deadlines come from the fixed broker
table.

A success has exactly:

```json
{"broker_protocol_version":1,"request_id":"request-1","result":{"status":"ok"}}
```

A failure has exactly:

```json
{"broker_protocol_version":1,"error":{"code":"operation_failed","retry":"never"},"request_id":"request-1"}
```

When framing or malformed JSON provides no valid safe correlation ID, an error
uses `request_id:null`. A success never does. Request IDs are single-use for
the lifetime of one negotiated connection, including the hello ID. Once a
canonical request object provides a syntactically valid ID, that ID is consumed
before the remaining envelope, authorization, payload, limit, or deadline
checks. Reusing an ID after either an accepted or rejected request is
`request_invalid`; an ID is not idempotency or replay authority.

A connection admits at most 4,096 complete messages including hello. Every
post-hello validation attempt counts before JSON parsing, including malformed
messages and duplicate IDs. Once the count is full, the next attempt returns
`broker_busy` without parsing its body and makes the protocol state terminal;
later attempts return `broker_unavailable`. The transport closes after
that terminal result. This bounds both retained IDs and per-connection
validation work.

Protocol debug representations omit request IDs, scope/session IDs, and
payload/result values. This is defense in depth for operational code;
the logging allowlist in the ADR remains mandatory and must not log a complete
wire message or request object.

The operation payload is always an object. Its exact required/optional fields
and complete nested result schema live in the machine-readable table. Unknown
fields are rejected at every object depth.

### Strict result schemas

All result fields are required unless their schema explicitly admits `null`;
no result object has optional or passthrough fields. The shared schema
vocabulary is deliberately small: closed objects, homogeneous arrays, typed
maps, booleans, bounded non-negative integers, canonical decimal strings,
bounded opaque IDs, canonical standard base64, fixed string enums, nullable
values, and a closed union for the two audit-event shapes.

| Operation | Exact top-level result fields |
|---|---|
| `broker_health` | `status` |
| `scope_open` | `scope_id` |
| `scope_close` | `closed` |
| `session_dispose` | `disposed` |
| `detect` | `detected_entity_count`, `entity_type_counts`, `highlights` |
| `analyze` | `overall_score`, `overall_grade`, `risk_label`, `direct_pii_count`, `fp_count`, `tb_count`, `section26_categories`, `reidentification`, `breakdown`, `recommendations` |
| `guard` | `flagged`, `guard_findings` |
| `sanitize` | `session_id`, `sanitized_text`, `detected_entity_count`, `replacement_count`, `entity_type_counts`, `highlights`, `section26_categories`, `guard_findings`, `warnings`, `safety` |
| `reidentify` | `restored_text`, `replaced_count`, `leftover_count`, `warnings` |
| `roundtrip` | `sanitized_text`, `ai_response_masked`, `restored_text`, `detected_entity_count`, `entity_type_counts`, `provider_used`, `section26_categories`, `guard_findings`, `warnings`, `safety`, `restoration` |
| `analyze_report` | `report_pdf_b64`, `overall_score`, `overall_grade` |
| `redact_pdf` | `source_type`, `ocr_confidence`, `human_review`, `warnings`, `detected_entity_count`, `entity_type_counts`, `fields`, `section26_categories`, `redacted_pdf_b64`, `after_png_b64` |
| `audit_log` | `status`, `total_count`, `limit`, `offset`, `logs` |
| `maintenance_drain_stop` | `accepted` |

The nested definitions pin highlight, finding, safety, warning, analysis,
document, restoration, and audit-event fields and enums. Result score,
confidence, timestamp, and latency values use decimal strings on this wire;
Slice 3 converts already validated finite HTTP numbers into that canonical
representation.

The protocol schema is an additional boundary, not a replacement for the
existing HTTP-v2 DTO. Slice 3 first validates the child response header and
complete HTTP projection—including its cross-field count, interval, warning
order, and recommendation invariants—then convert it to this broker schema
before constructing a success.

## Roles and operations

| Operation | Scope | Desktop | Extension | Maintenance | Payload |
|---|---|---:|---:|---:|---|
| `broker_health` | none | yes | yes | yes | `{}` |
| `scope_open` | none | yes | yes | no | `{scope_kind}` |
| `scope_close` | required | yes | yes | no | `{}` |
| `session_dispose` | required | yes | yes | no | `{session_id}` |
| `detect` | required | yes | no | no | `{text}` |
| `analyze` | required | yes | no | no | `{text}` |
| `guard` | required | yes | no | no | `{text}` |
| `sanitize` | required | yes | yes | no | `{text, mode?, session_id?}` |
| `reidentify` | required | yes | yes | no | `{session_id, text}` |
| `roundtrip` | required | yes | no | no | `{text, mode, provider}` |
| `analyze_report` | required | yes | no | no | `{text}` |
| `redact_pdf` | required | yes | no | no | `{pdf_b64}` |
| `audit_log` | required | yes | no | no | `{limit?, offset?}` |
| `maintenance_drain_stop` | none | no | no | yes | `{}` |

Desktop scope kinds are `desktop_ui` and `desktop_hotkey`. Extension scope
kinds are `extension_tab` and `extension_panel`. A role cannot open another
role's scope kind. Slice 3 binds broker-issued scope IDs and session
handles to the authenticated connection; Slice 1 validates only their opaque
syntax and the closed policy.

`session_id` is always a broker handle on this wire, never the backend UUID.
`pdf_b64` is ASCII canonical RFC 4648 standard base64 with padding and no
whitespace. Non-ASCII input is `request_invalid` before encoded-size
classification so Python and Rust apply the same byte-based limit semantics.
`provider` is only a bounded provider name; it cannot contain an endpoint,
credential, arbitrary configuration, or fallback list. The backend's existing
allowlist remains authoritative.

Unknown roles fail hello as `broker_unauthorized`. Unknown operations are
`request_invalid`. A known operation outside the bound role is
`broker_unauthorized`. Authorization is checked before operation-payload
validation.

## Fixed value-free errors

The closed table is:

| Code | Retry classification | Meaning |
|---|---|---|
| `broker_unavailable` | `reconnect_only` | PII-free startup/connection/hello may be attempted again |
| `broker_unauthorized` | `never` | peer, role, scope kind, or operation is not authorized |
| `broker_incompatible` | `never` | no common explicit broker protocol |
| `request_invalid` | `never` | malformed, noncanonical, unknown, missing, duplicate, or invalid request structure |
| `payload_too_large` | `never` | frame, message, field, or decoded document exceeds a fixed cap |
| `broker_busy` | `never` | a bounded connection-message or executor/queue limit rejected admission |
| `operation_timeout` | `never` | the broker-selected deadline expired |
| `operation_failed` | `never` | unknown/internal failure collapsed at the broker boundary |
| `session_unavailable` | `never` | handle/session is missing, expired, invalidated, or not owned |
| `residual_pii` | `never` | the existing outbound policy blocked publication/use |
| `document_invalid` | `never` | fixed document validation failure |
| `provider_unavailable` | `never` | shared provider attempts were exhausted/unavailable |
| `provider_rejected` | `never` | fixed non-retryable provider rejection |
| `provider_response_invalid` | `never` | fixed provider response validation failure |
| `provider_configuration` | `never` | fixed provider configuration failure |
| `dependency_unavailable` | `never` | fixed local dependency failure |
| `ocr_unavailable` | `never` | fixed OCR dependency failure |
| `ner_unavailable` | `never` | fixed explicit-TNER availability failure |
| `ner_incomplete` | `never` | fixed explicit-TNER completeness failure |
| `restore_failed` | `never` | fixed restoration failure |

`reconnect_only` never authorizes replay of a data request. Every other
classification is `never`. Unknown codes and unknown/internal exceptions
collapse to `operation_failed`. No error field or exception object may contain
request or response text, masked/restored text, PII, a mapping, credential,
provider body, exception text/type/graph, path, filename, endpoint, backend
authentication material, or observed peer value.

## Limits

| Limit | Value | Basis |
|---|---:|---|
| Hello JSON | 4,096 bytes | bounded negotiation metadata only |
| Default request/response | 1,048,576 bytes | existing worker cap and Chrome host-to-extension ceiling |
| Extension response | 1,048,576 bytes | Chrome Native Messaging host response ceiling |
| Raw PDF payload | 52,428,800 bytes | existing HTTP 50 MiB upload cap |
| Base64 for max raw PDF | 69,905,068 bytes | `4 * ceil(52,428,800 / 3)` |
| Maximum broker JSON frame | 70,953,644 bytes | max PDF base64 plus one 1 MiB envelope/result budget |
| Text, local engine | 200,000 Unicode code points | existing HTTP work cap |
| Local intermediate detector input | 200,000 Unicode code points | reuses the local text-work cap for masked, restored, or provider-output scans |
| Text, explicit remote TNER | 500 Unicode code points | one existing `_CHUNK_CORE_CHARS` core; bounds current retag amplification |
| Explicit remote-TNER calls | 501 calls | one primary call plus at most two line-retags for each of at most 250 non-empty physical lines; degenerate and unknown-label retag branches are mutually exclusive |
| Complete messages per connection | 4,096, including hello | bounds retained single-use IDs to at most 524,288 ASCII ID bytes and permits more than 20 operations per existing 200-session cap |
| Request/scope/session ID | 128 ASCII characters | existing worker opaque-ID convention |
| Operation/provider/product version | 64 ASCII characters | existing worker operation convention and closed syntax |
| Supported-version list | 8 integers | bounded explicit compatibility generations |
| JSON container depth | 32, including the root object | the deepest v1 conformance result envelope needs five levels; more than six times that depth remains available while input is rejected below language parser recursion limits |
| Audit limit | 1..1,000 | existing HTTP-v2 contract |
| Audit offset | 0..2,147,483,647 | language-neutral signed 32-bit bound; existing API semantics remain unchanged |

The 1 MiB result ceiling can reject an otherwise valid text result after work
if expansion makes it too large; no truncated success is returned. The PDF
budget admits the existing maximum input plus bounded JSON metadata. A larger
PDF result also fails rather than streaming, truncating, or changing framing.
Revising a wire limit requires an explicit compatible protocol update.

## Broker-selected deadlines

Clients cannot send or extend deadlines. These values are normative terminal
whole-operation wall-clock caps. The Slice 3 data-plane adapter enforces them
independently with a monotonic outer deadline; it cannot rely on an HTTP
library's scalar timeout to enforce total elapsed time. In particular, the
current 15-second TNER and 60-second provider scalar `httpx` settings apply to
individual phases or read inactivity and do not prove a total-call upper
bound.

The local phase counts below are top-level detector-entry budgets, not counts
of every internal `detect_tb` call. Outbound policy may rescan multiple
segments inside one phase. The six-minute phase cap is authoritative over that
whole nested call graph and may fail closed on a valid worst-case expansion or
segment-rescan case; it is not a claim that the current uncontained core always
finishes in six minutes. Before each local detector phase, Slice 3 rejects
masked, restored, or provider-output text above the fixed 200,000-code-point
intermediate cap as `payload_too_large`. It also makes the phase and outer
deadline cancellable. Slice 1 changes no current core path.

| Profile | Deadline | Policy basis |
|---|---:|---|
| `control` | 5,000 ms | existing Desktop startup wait; PII-free broker-local work |
| `local_non_detection` | 60,000 ms | bounded guard, audit, and lifecycle work; the measured guard path was 0.051 s, with headroom for bounded audit/disposal work |
| `local_text` | 360,000 ms | one authoritative top-level detector phase; a 200,000-character repetitive synthetic Thai analysis probe measured 164.741 s, twice that is 329.482 s, rounded up to six minutes |
| `local_report` | 360,000 ms | the same max-size probe plus report rendering measured 166.972 s total; twice that is 333.944 s, rounded up to six minutes |
| `local_sanitize` | 725,000 ms | two top-level detector phases at 360 s plus 5 s adapter budget |
| `local_reidentify` | 420,000 ms | one conditional restored-output detector phase at 360 s plus 60 s restoration/disposal budget |
| `local_document` | 300,000 ms | existing documented 300 s document surface; current one-page OCR evidence is 221 s |
| `local_provider` | 2,348,000 ms | six top-level detector phases at 360 s + three configured 60 s provider attempts + `1+2 s` delays + 5 s adapter budget |
| `remote_tner_text` | 7,520,000 ms | at 500 characters, one primary call plus at most 500 line-retags = 501 calls; allocates `501*15 s + 5 s`, with the outer cap authoritative |
| `remote_tner_report` | 7,580,000 ms | remote-TNER text budget + 60 s local/report overhead at the separate 500-character TNER cap |

`detect` and `analyze` select `local_text` or `remote_tner_text`.
`analyze_report` selects `local_report` or `remote_tner_report`. These are the
only broker-v1 data operations that may select remote TNER: their current
paths make one source-text detector entry, so the 500-character/501-call table
applies to raw pre-mask source only.

`sanitize`, `reidentify`, and `roundtrip` use `local_sanitize`,
`local_reidentify`, and `local_provider`, respectively. Explicit remote TNER
is disabled for all three in broker v1 because their current core paths can
rescan masked text, restored text, or provider output. Sending those values to
the remote detector would violate the accepted ADR's raw-pre-mask-only and
never-external-restored-PII rules. Selection of one of these disabled
combinations fails fixed as `ner_unavailable` with no local fallback.
`redact_pdf` uses `local_document` and also disables remote TNER because its
extracted text has no finite broker cap.
`guard`, `audit_log`, `scope_close`, and `session_dispose` use
`local_non_detection`. HTTP v2 and detector/provider orchestration remain
unchanged.

A deadline expiry is terminal even if an underlying HTTP timeout has not
expired. The Slice 3 broker applies the ADR's known-session disposal or
backend-teardown rule; it does not return a partial result or replay the
request. Cancellation and teardown enforcement belong to the integrated
data-plane/lifecycle slices, not historical Slice 1.

## Replay and uncertain mutation

Only PII-free connection establishment, hello, and `broker_health` are safe to
repeat automatically. Every other operation is `non_replayable`, including
read-like data operations, because replay can resend raw text to remote TNER,
repeat provider use, refresh session retention, duplicate publication, or
confuse ownership.

Implemented uncertain-completion handling is fixed:

- `sanitize` without a supplied session handle: possible unknown session
  publication; if the backend session ID is unknown, tear down the backend and
  invalidate all handles;
- `sanitize` with a supplied session handle: known-session mutation; invalidate
  that handle and confirm authenticated disposal, or tear down the backend and
  invalidate every handle if disposal cannot be confirmed;
- `reidentify` and `session_dispose`: known session mutation; confirm
  authenticated disposal or tear down the backend;
- `roundtrip`: request-transient mapping/provider use; unconfirmed Python
  cleanup tears down the backend;
- `scope_close`: dispose every owned session; unconfirmed disposal tears down
  the backend;
- remote-TNER/provider-capable reads: never resend their input; and
- broker/backend restart or upgrade: invalidate every handle and create no
  restoration continuity.

Slice 6 package replacement activates a verified local maintenance barrier
before any executable or manifest byte changes. The barrier is outside the
wire contract: it rejects new native admission, while only a complete-set-
admitted `maintenance` client may send `maintenance_drain_stop`. That role has
no scope kind and cannot sanitize, restore, inspect, or receive a session
handle. Once drain begins, the broker stops admissions, cancels or boundedly
terminates in-flight work without replay, disposes known sessions, terminates
the backend when completion/disposal is uncertain, closes the endpoint, and
exits. Package repair then starts a new broker generation with new private
backend credentials and empty state. Neither the barrier nor the component
manifest contains mapping/session data.

Slice 1 itself implements no retry, disposal, teardown, or backend call. It
exposes the policy metadata so later slices cannot silently choose weaker
semantics; integrated Slices 2--5 and the merge-conditional Slice 6 closure tree
enforce that policy at the runtime, data-plane, native-host, and package
boundaries.
