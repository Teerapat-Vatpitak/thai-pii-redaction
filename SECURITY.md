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
  not intentionally persisted. Contract-v1 responses nevertheless send direct
  or reconstructable mapping fields to first-party clients over loopback;
  contract v2 must remove those explicit DTO fields.
- The extension may retain a security-sensitive opaque session ID, not a
  mapping collection, and necessarily handles input/output text transiently.
- Default PII detection and pseudonym generation run locally. Explicit remote
  TNER sends raw pre-mask chunks to AI for Thai. Local clients plus HTTP/worker
  roundtrips can currently proceed after residual warnings; mandatory
  fail-closed policy remains open.
- The control plane uses a boot token when the bundled desktop shell launches
  the sidecar. The contract-v1 local data plane is not authenticated.

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

- caller authentication configured by `AIGUARD_API_KEY` or the official
  platform adapter;
- transient in-process mappings with no persistence and no explicit mapping DTO
  in normal hosted results. The internal worker-v1 result can still include a
  mapping after an exact opt-in and is not the official delivery contract;
- application logs and public errors without request text, raw PII, or bearer
  authority. Current shared-server session-bearing audit can write a live
  session ID to stdout, so safe correlation and official log acceptance remain
  open;
- separation between the AI Guard caller credential and Pathumma/TNER provider
  credentials; and
- an intended protected roundtrip that sends only verified masked text. Current
  HTTP/worker paths can invoke the provider after residual warnings, so this is
  not yet an accepted guarantee.

Failures that expose request text/mappings in platform-visible logs or results,
bypass hosted caller authentication, or send raw PII to Pathumma are in scope.
Retention and access inside infrastructure operated by the hosting platform are
also part of the platform trust model, but must be reported to the relevant
platform owner when they are outside this repository's code.

## Data and logging rules

- Tests, demos, issues, and vulnerability reproductions use synthetic PII.
- Application logs are intended to contain only event types, counts, timings,
  and non-authorizing correlation IDs—never request text, entity values,
  mappings, provider response bodies, or secrets. Current session-bearing
  sanitize/reidentify JSONL filenames/entries retain the live session ID on
  disk or configured stdout; replacing it is an open hardening gate.
- Public errors expose stable categories, not payloads or upstream bodies.
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
