# Security policy

## Supported versions

Only the latest published release is supported with security fixes. The
`main` branch may contain unreleased work; a fix is
considered shipped only when it appears in a published release or an explicitly
identified hosted deployment.

## Reporting a vulnerability

Do not open a public issue containing exploit details or real PII.

1. Preferred: use [GitHub private vulnerability reporting](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/security/advisories/new).
2. If that is unavailable, contact the maintainer through the channel listed on
   the [GitHub profile](https://github.com/Teerapat-Vatpitak). A public issue may
   ask for a private channel but must contain no exploit details.

Include the affected version or image digest, deployment context, reproduction
using synthetic data, and expected impact. Relevant impacts include raw PII
reaching a downstream AI, mapping/session exposure, log disclosure, PDF
redaction bypass, localhost API abuse, and hosted caller-authentication bypass.

There is no bug bounty. Reports are handled on a best-effort basis.

## Two security contexts

AI Guard runs in two contexts with different trust boundaries. A report should
state which context it affects.

### Local desktop and extension

- The backend binds to localhost and restricts accepted hosts/origins to the
  local extension and Tauri shell by default. These controls do not
  authenticate which process owns the fixed port; native-broker identity is an
  open hardening gate.
- The canonical pseudonym-to-original mapping lives in process memory and is
  not intentionally persisted. The published 2.5.0/v1 artifact sent direct or
  reconstructable mapping fields, raw Section 26 matches, and prompt-guard
  excerpts/rationales to first-party clients over loopback. Current unreleased
  source implements strict v2 DTOs without those fields and reduces findings
  to category/severity/count-only metadata. This is not a shipped-fix claim.
- The extension may retain a security-sensitive opaque session ID, not a
  mapping collection, and necessarily handles input/output text transiently.
- Default PII detection and pseudonym generation run locally. Explicit remote
  TNER sends raw pre-mask chunks to AI for Thai. Current-source
  outbound-capable local sanitization plus CLI, HTTP, and worker provider
  boundaries fail closed on the shared residual policy. This is automated
  source evidence; packaged, real-host, live-provider, and official hosted
  acceptance remains open.
- The control plane uses a boot token when the bundled desktop shell launches
  the sidecar. A separately configured API key can authenticate HTTP callers,
  but normal fixed-port first-party clients do not receive it and still cannot
  authenticate the process that owns localhost.

For the browser in-page flow, raw text is typed into provider-controlled page
DOM before Mask runs. Page code can observe or transmit it; AI Guard does not
intercept or attest the provider's network request. The side panel is the
stronger raw-entry boundary.

The highest-severity local failure is real, unmasked PII reaching an external AI
through an intended AI Guard send path.

### Hosted platform service

Calling a hosted service sends raw input to the hosting platform and AI Guard
container. The local claim "PII never leaves the device" does not apply.

Hosted security relies on:

- an accepted hosted adapter authenticating every approved public operation.
  The current main-repository `app.hosted` candidate requires
  `AIGUARD_API_KEY` plus a provider allowlist and gates every non-health route,
  but that local candidate is not official-platform authentication evidence;
- no explicit mapping DTO in hosted results and no deliberate mapping write to
  disk. The current candidate is mixed: sanitize/reidentify retain process
  session state without a hosted disposal route, while roundtrip uses a
  request-transient mapping. The internal worker-v1 result can still include a
  mapping after an exact opt-in and is not the official delivery contract;
- application logs and public errors without request text, raw PII, or bearer
  authority. Current-source API process-audit callers use fresh
  non-authorizing operation UUIDs rather than live restoration session IDs.
  The separately versioned sibling port, official log transport/retention, and
  platform-visible scan remain unverified;
- separation between the AI Guard caller credential and configured
  downstream-provider credentials; and
- an intended protected roundtrip that sends only verified masked text.
  Current-source CLI, HTTP, and worker paths rescan and fail closed immediately
  before provider calls, but the separately versioned sibling port, live
  providers, and official hosted composition still need independent
  verification before this becomes an accepted platform guarantee.

Failures that expose request text/mappings in platform-visible logs or results,
bypass hosted caller authentication, or send raw PII to a downstream provider
are in scope. Retention and access inside infrastructure operated by the
hosting platform are also part of the platform trust model, but must be
reported to the relevant platform owner when they are outside this
repository's code.

## Data and logging rules

- Tests, demos, issues, and vulnerability reproductions use synthetic PII.
- Application logs are intended to contain only event types, counts, timings,
  and non-authorizing correlation IDs—never request text, entity values,
  mappings, provider response bodies, or secrets. Current-source sanitize,
  reidentify, and roundtrip callers pass fresh operation UUIDs to disk or
  configured stdout; the legacy field is still named `session_id`. In file
  mode, fresh IDs create operation-specific files and no timed retention policy
  exists; configured stdout mode creates no file. Published 2.5.0 predates this
  source change; official-platform logging remains outside this evidence.
- Current unreleased HTTP v2 errors expose only stable codes plus bounded safe
  metadata; they omit payloads, upstream bodies, pseudonyms, mappings, and raw
  exception messages. The published 2.5.0/v1 artifact predates this boundary.
  Worker-envelope compatibility and provider-orchestration convergence remain
  separate work. Request-validation errors are fixed and do not
  echo rejected body/query values; an outer HTTP boundary also contains
  pre-response-start JSON rendering failures. Current HTTP endpoint, direct
  stateless/session transaction and restore, provider, PDF/OCR fallback, and
  worker handler/runner regressions require caught ordinary exception objects to lose
  traceback, cause, context, arguments, ordinary custom attributes, and common
  built-in payload slots that could link back to request, vault, credential,
  page-image, or response state. Ordinary `ExceptionGroup` members are scrubbed
  recursively, but Python's read-only group message/member shell cannot be
  overwritten safely; it is dropped without logging or export. Process signals,
  whether raised directly or inside a `BaseExceptionGroup`, may propagate.
- PDF temporary files are bounded and removed after processing.
- Session/container restart may discard mappings by design; persistence added
  for convenience would be a security-significant architectural change.

## Supply-chain and distribution model

Desktop installers are currently unsigned by design, so SmartScreen or
Gatekeeper warnings are expected. Releases publish `SHA256SUMS` and GitHub build
provenance. Verify with the instructions in the README. The reasoning, and the
conditions that would reverse it, are recorded in
[docs/decisions/2026-07-29-store-distribution-and-signing.md](docs/decisions/2026-07-29-store-distribution-and-signing.md).

Build inputs are pinned where the project can reliably pin them. Verification
proves artifact origin and integrity, not bit-for-bit reproducibility. A finding
that allows unreviewed code or an unexpected asset to receive first-party
release provenance is in scope.

Expected/out of scope by itself: the unsigned-publisher warning, loss of an
in-memory session after restart, and denial-of-service against a correctly
localhost-only personal backend. Resource exhaustion or cross-tenant impact on
an official hosted service remains in scope once that deployment exists.
