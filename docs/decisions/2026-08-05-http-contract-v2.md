# HTTP contract v2 privacy boundary

Date: 2026-08-05
Status: accepted; implementation pending

Supersedes the main-HTTP-contract portions of
[the 2026-07-22 platform integration contract](2026-07-22-platform-integration-contract.md).
It does not supersede that record's worker-envelope decisions.

## Context

The intended local trust boundary keeps the canonical pseudonym-to-original
mapping in backend memory. Browser, Desktop webview, and Office JavaScript
data-plane clients may retain an opaque `session_id`; they must not receive a
mapping or credential. The native Desktop shell separately owns its
control-plane authority in process memory.

HTTP contract v1 does not meet that boundary. `/api/sanitize` returns the
submitted text plus original-space entity spans and replacement values, so a
client can reconstruct mapping pairs. `/api/reidentify` returns explicit
replacement/original pairs and leftover replacement strings. Section 26 and
prompt-injection projections can include matched text or excerpts. The health
response also exposes one `token_required` capability for the control-plane
boot token, while Office interprets it as a data-plane credential requirement.

The v1 contract tests check for the absence of a literal `mapping` key, but
accept extra fields and do not reject reconstructable or direct mapping
material. First-party runtime clients do not currently enforce
`contract_version`. Office additionally validates `recommendations` as an array
of strings while the server returns structured recommendation objects; its
unit fixtures do not exercise that real composition.

A repository and deployment-consumer inventory found no evidenced external
HTTP-v1 caller. Every executable caller found is a first-party client
(Extension, Desktop, Office, or the opt-in demo) or repository-owned
acceptance/build automation. Published documentation and OpenAPI exposure make
unknown consumers possible, but are not evidence that one exists. The separate
`aiguard-aift` repository is an independently versioned v1 service, not a
caller of this API, and remains outside this change.

This is an accepted public-contract decision, not implementation or acceptance
evidence. Current source continues to serve contract v1 until the atomic v2
cutover lands.

## Decision

### 1. Direct cutover and version boundaries

The main HTTP API moves directly from contract version 1 to contract version 2.
No v1 route, content negotiation, compatibility projection, or silent fallback
will be added unless a real external v1 consumer is identified. Finding one
before the cutover is a stop condition requiring owner review.

HTTP `contract_version` is independent of both product `VERSION` and the local
queue-worker envelope:

- the worker's `CONTRACT_VERSION` remains `1`;
- the separately versioned `aiguard-aift` service remains v1 and out of scope;
- product `VERSION` remains `2.5.0` during development; and
- a release containing this public break is expected to be prepared as
  `3.0.0`, but version bump, tag, release, and deployment require separate
  authorization.

### 2. Route and authentication matrix

The fixed request header `X-AIGuard-Contract-Version: 2` is required on every
v2 `/api/*` operation except health. It is a version assertion, not
negotiation: missing, malformed, lower, or higher values fail with HTTP 426
before request body parsing. No downgrade path exists.

Every actual v2 `/api/*` success and error response, including health and 426,
also carries `X-AIGuard-Contract-Version: 2`. This response assertion is
required because some deliberately unchanged v1 and v2 JSON bodies, such as
control success and analyze-report, cannot identify the server generation by
shape alone. A client validates the header before it accepts any operation
result or performs a write.

A bodyless browser `OPTIONS` preflight is transport setup, not an API
operation. CORS handles it before contract, authentication, body, and service
middleware and does not require the assertion header itself. It succeeds only
for an exactly allowlisted origin, a requested `GET` or `POST` method, and a
requested-header subset of `Content-Type` and
`X-AIGuard-Contract-Version`; there are no wildcard origins, methods, or
headers. CORS exposes only `X-AIGuard-Contract-Version` from the relevant
non-safelisted response headers. The actual request must then carry the
assertion and pass every normal gate. A preflight does no PII, session, audit,
provider, or other service work, and its transport response is not an
operation/error DTO. Cross-origin JavaScript is not permitted to request
either credential header or any control-plane method.

| Surface | Routes | Stability and authority |
|---|---|---|
| Contract discovery | `GET /api/health` | Stable v2; open so a client can establish compatibility before sending PII; requires and interprets neither contract assertion nor credential |
| Main data plane | `POST /api/detect`, `/api/analyze`, `/api/guard`, `/api/sanitize`, `/api/reidentify`, `/api/roundtrip` | Stable v2; requires the contract assertion and, when `api_key_required` is true, `X-AIGuard-Key` |
| Local document data plane | `POST /api/analyze-report`, `/api/redact-pdf` | Internal first-party surface, not a stable hosted promise; still requires the contract assertion and configured data-plane authority; disabled by a hosted adapter unless explicitly allowlisted |
| Local introspection | `GET /api/audit-log` | Internal first-party surface with a strict safe DTO; requires the contract assertion and configured data-plane authority; never exposed by the hosted adapter |
| Local control plane | `DELETE /api/session/{session_id}`, `POST /api/shutdown` | Internal; requires the contract assertion and `X-AIGuard-Token` when configured; never exposed by the hosted adapter |
| Local UI | `GET /demo` and static assets | Not an API contract; opt-in development/packaged UI only |
| Developer metadata | `/`, `/docs`, `/redoc`, `/openapi.json` | Not an API contract; disabled by the hosted adapter |

When `AIGUARD_API_KEY` is configured, every non-control data-plane and
introspection route above requires `X-AIGuard-Key`; health remains open. A
hosted deployment must configure this authority or provide an authenticated
adapter that removes the direct app routes from public reach. The local source
profile may leave it unset until native-broker enforcement lands.

Health ignores assertion and credential headers if an infrastructure client
adds them; it never logs or reflects them. First-party health callers do not
send them.

`AIGUARD_TOKEN` and `X-AIGuard-Token` remain control-plane authority. Browser
and Office JavaScript never receive either credential. CORS and host checks
remain defense in depth, not server identity. Official AI for Thai route
allowlists and authentication remain adapter-owned and outside this contract.

Request DTOs also reject extra fields. Detect, analyze, guard, and
analyze-report accept only `{text}`. Sanitize accepts
`{text, mode?, session_id?}` where mode is `token` or `surrogate`; a new
session defaults to token and an existing session inherits its locked mode
when mode is omitted. Reidentify accepts `{session_id, text}`. Roundtrip
accepts `{text, mode, provider}` with mode and provider drawn from closed
server allowlists. Redact-pdf accepts one multipart `pdf_file`. Audit-log
accepts only integer query parameters `limit` from 1 through 1000 and `offset`
of zero or greater, defaulting to 100 and zero. Health accepts no query or
body; session disposal accepts one non-empty opaque path identifier and no
query or body; shutdown accepts no query or body. No route accepts a preview,
residual override, or arbitrary provider configuration.

### 3. Strict projections

Every v2 JSON response consumed by a privacy-sensitive first-party path has an
exact server schema and an exact client validator equivalent to
`additionalProperties: false`. Clients construct new DTOs from validated
fields; they do not pass through backend objects. Unknown fields, missing
fields, wrong types, and unsafe safety state are hard failures.

The JSON field `contract_version` appears only in `/api/health`, not in each
operation DTO. Every client must validate an exact v2 health response and its
v2 response header before it enables an operation, repeat that gate after a
backend restart or reconnect, and validate the v2 response header again on
every operation success or error. A missing, malformed, or mismatched health
contract or response assertion is a hard failure before any client write; a
failed health gate prevents any PII-bearing request.

Text a caller submitted and the sanitized or restored text it requested are
necessarily present in that caller's process. Contract v2 does not claim that
reconstruction from caller-owned text is mathematically impossible. It removes
backend-projected mapping-oriented material and prevents that material from
being copied into additional browser, Office, or Desktop response objects.

No v2 response may contain:

- `original_text`;
- a replacement `token` or `original`;
- a `replaced` collection;
- leftover replacement strings;
- raw Section 26 match text;
- raw guard excerpts or rationales;
- internal entity IDs; or
- credentials, provider bodies, or exception messages.

Fields such as `control_token_required` describe a capability; they never carry
a token value.

### 4. Exact response DTOs

`GET /api/health` is the contract-discovery response:

```text
{
  status,
  version,
  contract_version: 2,
  capabilities: {
    control_token_required: boolean,
    api_key_required: boolean
  }
}
```

`control_token_required` describes local control-plane authority.
`api_key_required` describes hosted data-plane caller authentication. They are
different trust domains. Office readiness depends only on
`api_key_required`; it must not reject a packaged local backend merely because
the control plane is protected.

Those are the complete v2 capability keys. Because the health schema is
strict, the later native-broker design cannot add
`local_broker_required` or `broker_protocol_version` while continuing to call
the response HTTP contract v2. Its ADR must choose either a separately
versioned broker-attestation endpoint or a new HTTP contract version. The
broker protocol's own version remains independent.

Unless a narrower rule appears below, count and offset fields are non-negative
integers, booleans are JSON booleans, lists preserve the specified canonical
order, and text/base64 fields are strings. Health `status` is exactly `ok`;
`version` is the product-version string; `session_id` is a non-empty opaque
string; and `provider_used` is one configured provider-enum value. Every object
at every nesting level rejects additional properties.

For roundtrip, `provider_used` must exactly equal the caller's validated
`provider` choice. Failure is returned through the safe error contract; the
server never falls back to a different provider because that would change
which external party receives masked text.

`POST /api/sanitize` returns:

```text
{
  session_id,
  sanitized_text,
  detected_entity_count,
  replacement_count,
  entity_type_counts,
  highlights: [{start, end, data_type, redact_type}],
  section26_categories,
  guard_findings: [{category, severity}],
  warnings: [{code, count}],
  safety: {status: "pass", residual_count: 0}
}
```

Highlights refer only to `sanitized_text`. They come from the internal
non-overlapping replacement plan, including consistency replacements. They do
not include a replacement value.

`POST /api/reidentify` returns:

```text
{
  restored_text,
  replaced_count,
  leftover_count,
  warnings: [{code, count}]
}
```

`leftover_count == 0` is the complete-restoration condition for this response.
A client may preview a partial result locally, but must not apply or insert it
when `leftover_count` is nonzero.

`POST /api/roundtrip` returns:

```text
{
  sanitized_text,
  ai_response_masked,
  restored_text,
  detected_entity_count,
  entity_type_counts,
  provider_used,
  section26_categories,
  guard_findings: [{category, severity}],
  warnings: [{code, count}],
  safety: {status: "pass", residual_count: 0},
  restoration: {status, replaced_count, leftover_count}
}
```

`restoration.status` is `complete` only when no known replacement remains.
Clients must not copy, apply, insert, or place a non-complete result into an
external composer or document.

`POST /api/detect` returns:

```text
{
  detected_entity_count,
  entity_type_counts,
  highlights: [{start, end, data_type, redact_type}]
}
```

`POST /api/analyze` returns:

```text
{
  overall_score,
  overall_grade,
  risk_label,
  direct_pii_count,
  fp_count,
  tb_count,
  section26_categories,
  reidentification: {
    score,
    grade,
    quasi_identifier_categories,
    high_risk_combination
  },
  breakdown: [{data_type, redact_type, count}],
  recommendations: [{level, title, desc}]
}
```

Scores are finite numbers from 0 through 100. Grades are one of
`A`, `B`, `C`, `D`, or `F`; risk labels are one of `Very Low Risk`,
`Low Risk`, `Medium Risk`, `High Risk`, or `Very High Risk`.
`quasi_identifier_categories` uses the closed values `gender`,
`date_of_birth`, `age`, `district`, `province`, `occupation`, and `religion`.
Recommendation levels are `high`, `medium`, or `info`; titles and descriptions
come only from server-owned allowlisted templates. This resolves the current
Office mismatch in favor of the server's structured recommendation objects.

`POST /api/guard` returns:

```text
{
  flagged,
  guard_findings: [{category, severity}]
}
```

`flagged == (guard_findings.length > 0)`. Findings are deduplicated in
first-finding order. Prompt-injection and PDPA Section 26 findings remain
warning/report signals, not automatic redaction or blocking.

The internal `POST /api/analyze-report` first-party DTO is:

```text
{
  report_pdf_b64,
  overall_score,
  overall_grade
}
```

The internal `POST /api/redact-pdf` first-party DTO is:

```text
{
  source_type,
  ocr_confidence,
  human_review,
  warnings: [{code, count}],
  detected_entity_count,
  entity_type_counts,
  fields: [{data_type, redact_type}],
  section26_categories,
  redacted_pdf_b64,
  after_png_b64
}
```

`source_type` is `pdf_text` or `pdf_hybrid`; `ocr_confidence` is null or a
finite number from 0 through 1. `fields` contains one entry per nonzero
data-type/redaction-class pair in canonical first-detection order. The response
does not repeat the caller-owned filename or return the separate unredacted
`before_png_b64` preview. It returns only the redacted artifact and its
post-redaction preview. That projection change does not establish exact
entity-to-box coverage or renew PDF acceptance: current bbox association
remains heuristic until the separate PDF interval-alignment work lands.

The internal `GET /api/audit-log` first-party DTO retains two exact event
variants:

```text
{
  status: "ok",
  total_count,
  limit,
  offset,
  logs: [
    {
      type: "process",
      timestamp,
      step,
      entity_count,
      validation_result,
      latency_ms,
      flags: [{code, count}]
    }
    |
    {
      type: "security",
      timestamp,
      layer,
      pii_scan_result,
      retry_count,
      error_type,
      rollback_occurred
    }
  ]
}
```

Audit strings and flags come from closed structural enums or count-only
templates. They never contain a session authority, replacement, source value,
path, provider body, or restored answer. Control success DTOs remain exactly
`{deleted: boolean}` for session disposal and
`{status: "shutting_down"}` for shutdown.

Audit `timestamp` is a finite non-negative Unix-seconds number;
`latency_ms` is a finite non-negative number; count fields are non-negative
integers. Process `step` is an allowlisted operation identifier and
`validation_result` is `prepared`, `blocked`, `pass`, or `warn`. Flag code is
one of `provider_call`, `leftover_replacement`, `residual_block`,
`ocr_review_required`, `source_pdf_text`, or `source_pdf_hybrid`; its count is
zero for a boolean event. Security `layer` is an allowlisted layer identifier,
`pii_scan_result` is `clean`, `unexpected_pii`, `blocked`, or `error`, and
`error_type` is a stable error code from this ADR or null.

Audit files can survive an upgrade. The v2 reader maps a recognized legacy row
into this DTO from allowlisted fields only and drops an unrecognized or
malformed row. It never passes through a retained row, flag, exception type, or
extra field. `total_count` counts projected rows after this filtering.

Count maps contain only nonzero entries, use data-type keys matching
`^[A-Z][A-Z0-9_]*$`, and treat omission as zero. Clients render a valid
unrecognized data type generically rather than failing open or treating it as
a known class. `detected_entity_count` equals the sum of
`entity_type_counts`; analyze also requires
`direct_pii_count == fp_count + tb_count == sum(breakdown.count)`.

The initial data-type vocabulary is `THAI_ID`, `PHONE`, `EMAIL`, `NAME`,
`SURNAME`, `ADDRESS`, `POSTAL_CODE`, `MEDICAL_ID`, `BANK_ACCOUNT`,
`CREDIT_CARD`, `DATE_OF_BIRTH`, `VEHICLE_PLATE`, `PASSPORT`, `STUDENT_ID`,
`IBAN`, `ETHNICITY`, `POLITICAL_OPINION`, `RELIGION`, `CRIMINAL`, `HEALTH`,
`DISABILITY`, `UNION`, `LOCATION`, `DATE`, `ORGANIZATION`, and `ID_NUMBER`.
Redaction class is `FP` or `TB`.

Detect highlights are sorted, non-overlapping, in bounds, and satisfy
`detected_entity_count == highlights.length`. Sanitize highlights have the same
ordering/bounds invariant and satisfy
`replacement_count == highlights.length`; consistency replacements may make
that count greater than `detected_entity_count`.

Section 26 category lists are unique closed-enum values in canonical scan
order. The initial categories are `RACE_ETHNICITY`, `POLITICAL_OPINION`,
`RELIGION`, `HEALTH`, `SEXUAL_BEHAVIOR`, `CRIMINAL_RECORD`, `DISABILITY`, and
`LABOR_UNION`. Guard category is `instruction_override`, `role_hijack`,
`exfiltration`, `hidden_chars`, or `suspicious_payload`; severity is `low`,
`medium`, or `high`.

Warning objects have a positive integer count, are deduplicated by code, and
accept only codes allowed for that DTO:

- sanitize has no warning code in initial v2; residual signals are errors;
- reidentify and roundtrip allow `generated_pii` and
  `foreign_replacement`; and
- redact-pdf allows `ocr_low_confidence` and `human_review_required`.

`generated_pii` counts detector findings in model-generated text;
`foreign_replacement` counts replacement-shaped values not owned by the
session; PDF warning counts are affected pages. No warning carries the matched
value.

Adding a Section 26 category, warning code, guard category/severity, or other
closed-enum value is a contract change. A new schema-valid data type is
additive, but still requires honest-label tests and synchronized client copy.
Detection findings contain source offsets, type, and redaction class, never
matched values or internal IDs.

### 5. Offset contract

All text offsets exposed by v2 are half-open Unicode code-point offsets
`[start, end)`. Each field names or fixes its reference string:

- sanitize highlights refer to the returned `sanitized_text`; and
- detect offsets refer to the submitted text through the existing
  length-preserving normalization contract.

JavaScript strings use UTF-16 indexes, so every JavaScript client uses one
tested code-point-to-UTF-16 conversion helper before slicing or highlighting.
Tests must cover non-BMP characters, combining sequences, Thai text, and
boundary positions. No client may apply a code-point offset directly to a
JavaScript string.

### 6. Safe error contract

Every API error, including framework validation, route, method, and unhandled
exceptions, uses this exact envelope:

```text
{
  error: {
    code,
    category,
    count,
    retryable,
    status
  }
}
```

`count` is a non-negative integer and is zero unless the table defines another
meaning. `status` equals the HTTP response status; clients reject a mismatch.
`category` is one of `contract`, `request`, `authentication`, `session`,
`privacy`, `document`, `provider`, `configuration`, `dependency`, `network`,
`upstream`, `service`, or `internal`.
The closed initial code table is:

| Code | HTTP | Category | Retryable | Count meaning |
|---|---:|---|---|---|
| `contract_version_required` | 426 | `contract` | false | 0 |
| `invalid_request` | 400 | `request` | false | 0 |
| `request_schema_invalid` | 422 | `request` | false | rejected field count |
| `authentication_required` | 401 | `authentication` | false | 0 |
| `control_forbidden` | 403 | `authentication` | false | 0 |
| `route_not_found` | 404 | `request` | false | 0 |
| `session_unavailable` | 404 | `session` | false | 0 |
| `method_not_allowed` | 405 | `request` | false | 0 |
| `rate_limited` | 429 | `service` | true | 0 |
| `payload_too_large` | 413 | `request` | false | 0 |
| `residual_pii` | 422 | `privacy` | false | blocking signal-category count |
| `document_invalid` | 422 | `document` | false | 0 |
| `provider_unavailable` | 502 | `upstream` | true | 0 |
| `provider_rejected` | 502 | `upstream` | false | 0 |
| `provider_response_invalid` | 502 | `upstream` | false | 0 |
| `ner_incomplete` | 502 | `upstream` | false | incomplete chunk count |
| `provider_configuration` | 503 | `configuration` | false | 0 |
| `dependency_unavailable` | 503 | `dependency` | false | 0 |
| `ocr_unavailable` | 503 | `dependency` | false | 0 |
| `ner_unavailable` | 503 | see below | see below | failed chunk count |
| `service_unavailable` | 503 | `service` | true | 0 |
| `restore_failed` | 500 | `internal` | false | 0 |
| `internal_error` | 500 | `internal` | false | 0 |

`provider_rejected` covers all non-retryable upstream 4xx responses, including
408. Upstream 429 remains retryable. The locked outer provider policy is at
most three attempts, 60 seconds per attempt, with 1-second then 2-second
backoff; only timeout, network, 429, and 5xx failures retry. Every other 4xx
fails immediately, and a provider declaring `handles_retries = true` receives
one outer attempt. After that policy is exhausted, timeout, network, 429, and
5xx failures map to `provider_unavailable`.

`ner_unavailable` uses category `configuration` or `dependency` with
`retryable: false`, and `network` or `upstream` with `retryable: true`. These
reserved TNER codes allow the later explicit-engine contract to land without
silently extending v2. No provider error exposes an upstream status or body.

The envelope never includes user text, a PII value, replacement value,
mapping, credential, session authority, provider body, guard excerpt, raw
Section 26 match, arbitrary exception message, or restored answer. Clients show
their own localized copy keyed by the stable code; they never display an
untrusted backend message.

### 7. Mandatory outbound safety

`/api/sanitize` always represents an outbound-capable operation. A caller
cannot downgrade it to preview or request a residual-PII override.

The signal policy is closed. “Residual” means a finding in text after masking;
it is not a separate finding type in raw-input inspection responses:

| Signal | Sanitize, stateless/hosted, CLI-provider, HTTP-roundtrip, and worker-provider paths | `/detect` | `/analyze` | `/guard` |
|---|---|---|---|---|
| anonymization failure or missing replacement record | block | not applicable | not applicable | not applicable |
| structured residual from the FP detector | block | report the source entity by safe highlight and count | report the source entity in aggregate counts and breakdown | not run |
| text-based residual from the TB detector | block | report the source entity by safe highlight and count | report the source entity in aggregate counts and breakdown | not run |
| detector-independent bare digit run of six or more digits outside a replacement | block | not run on unmasked source text | not run on unmasked source text | not run |
| PDPA Section 26 category | warn/report through a safe category projection where the path has a caller-facing result | not run | report by safe category | not run |
| prompt-injection finding | warn/report through a safe finding projection where the path has a caller-facing result | not run | not run | report by safe category and severity |

Sanitize and HTTP roundtrip expose the safe Section 26 and guard projections
defined above. Other provider adapters preserve the same non-blocking policy
without exposing matched text or excerpts. The inspection endpoints remain
warn/report operations: each reports only the scanners its exact DTO defines;
they do not imply that every scanner runs on every inspection route.

A blocked result uses `residual_pii`, never a 2xx warning. The count is the
number of distinct blocking rows observed, not the number or value of matched
entities. Negative controls remain mandatory so ordinary quantities do not
silently grow the detector-independent rule.

The core applies this policy before returning sanitized text. Provider-capable
paths scan again immediately before invocation; failure means no provider call
and no queue/provider handoff. The worker handler migrates in the fail-closed
branch while its outer envelope version remains 1.

Every successful sanitize or roundtrip response therefore has
`safety.status == "pass"` and `residual_count == 0`. First-party clients defend
the boundary again and block all Copy, Apply, Insert, clipboard, or composer
writes if the previously validated health contract is absent, stale, or
mismatched, or if the operation response is non-2xx, malformed, contains an
unknown field, or does not have that exact safety state.

Only sanitize and roundtrip DTOs contain `safety`. Detect, analyze, and guard
are inspection-only. Reidentify is application-safe only when
`leftover_count == 0` and neither `generated_pii` nor
`foreign_replacement` appears in warnings. A client may preview any other
reidentify result locally, but must not copy, apply, insert, or send it.
Roundtrip restoration status is:

- `complete` when `leftover_count == 0` and neither blocking restoration
  warning is present;
- `incomplete` when a known replacement remains; and
- `unsafe` when a blocking restoration warning is present.

### 8. Atomic migration and rollback

The fail-closed core and worker safety branch lands before the wire cutover.
The v2 cutover then moves the server, Extension, Desktop web UI, Desktop Rust
hotkey path, Office task pane, opt-in demo/playground, acceptance runner,
Docker smoke, packaged-sidecar smoke, and current-truth documentation
together. The health capability split and contract-assertion middleware land
in that same v2 runtime commit, not before or after it.

Before publication, all in-repository consumers must be migrated and strict
tests must prove that malformed or extra fields fail closed. The current Office
analyze recommendation mismatch must be covered by a real server-shape fixture,
not another empty-list fixture.

Mixed-version behavior is explicit:

- a v1 client against a v2 server lacks the fixed contract assertion and gets
  `contract_version_required` before body parsing;
- a v2 client against a v1 server rejects health before sending PII; and
- even if a test bypasses the health gate, the absent v2 response header and
  strict JSON validation prevent every write, including for a body whose v1
  and v2 shapes are otherwise identical.

Before a v2 release, rollback reverts server and clients together. After a v2
release, the default is a roll-forward fix; v1 is never silently reactivated.
Distributing a prior v1 artifact would knowingly restore the mapping exposure
and therefore requires a separate, explicit owner approval that acknowledges
that security regression.

## Required implementation evidence

The cutover is not complete until all of the following pass on the exact
candidate:

- exact positive and negative schema tests for every affected server response
  and first-party client, including the demo/playground;
- route-matrix tests proving health ignores and never reflects assertion or
  credential headers; an allowlisted preflight succeeds before operation
  middleware; disallowed preflight origins, methods, and headers do not receive
  permissive CORS responses; only the version response header is exposed; and
  the corresponding actual request still gets 426 before body,
  authentication, service, session publication, audit, or provider work when
  its assertion is absent or wrong;
- response-assertion tests proving every actual v2 API success and error has the
  fixed v2 header, preflight is exempt, and every client rejects an absent,
  duplicate, malformed, or mismatched assertion before any write;
- authentication coverage proving every data-plane, document, and introspection
  route enforces the configured API key, both control routes enforce the
  configured control token, strict request schemas reject every extra field,
  and the hosted adapter disables or explicitly allowlists local-only routes
  and developer metadata;
- recursive forbidden-key and forbidden-value assertions across every success
  and error response;
- Unicode code-point/UTF-16 offset tests, including emoji and combining text;
- restore-count and completion parity tests;
- selected-provider tests proving `provider_used` equals the request and a
  provider failure never causes cross-provider fallback;
- tests proving no provider, composer, clipboard, document, Copy, Apply, or
  Insert action occurs after an unsafe or malformed result;
- v1-client/v2-server tests proving the v2 server does not parse the body,
  enter a service operation, publish session state, or call a provider when
  the assertion is absent or wrong;
- v2-client/v1-server tests proving failed health prevents every operation,
  plus a deliberate health-bypass test proving strict response rejection
  prevents every client write;
- all capability combinations, including the Office control-token/API-key
  distinction;
- forced structured, text-based, and detector-independent residual tests for
  session, stateless, CLI-provider, HTTP-roundtrip, and worker-provider paths,
  each proving no provider/handoff occurs;
- a migrated acceptance runner plus Docker and packaged-sidecar smokes
  expecting contract version 2;
- full Python, root JavaScript, Office, Rust, version/readiness,
  `git diff --check`, and performance gates; and
- independent privacy/correctness review plus current-truth documentation
  audit.

Packaged-sidecar and development-proxy evidence remains weaker than installed
Desktop, real browser, or real Office-host acceptance. Live providers and
official AI for Thai deployment remain separate, owner-gated evidence.

## Consequences

- The cutover intentionally breaks unknown v1 callers. This is accepted because
  no real external consumer is evidenced and retaining v1 would preserve the
  mapping leak.
- First-party clients and the server cannot roll forward independently.
- Sanitized-space highlighting replaces original-space entity projection.
- Strict validators will expose existing mock/real-response drift rather than
  accepting it silently.
- Mandatory outbound blocking can reduce availability when the text-based
  detector reports a residual. The accepted policy favors privacy; there is no
  silent override.
- Contract tests become privacy-boundary tests, not subset-shape smoke tests.
- This ADR does not change current runtime behavior, close an acceptance gate,
  alter the worker envelope, modify `aiguard-aift`, or authorize a release or
  deployment.
