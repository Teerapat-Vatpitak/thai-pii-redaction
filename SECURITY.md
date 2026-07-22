# Security policy

## Supported versions

Only the latest published release is supported with security fixes. The
`main` branch may contain unreleased platform or competition work; a fix is
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
  local extension and Tauri shell by default.
- The pseudonym-to-original mapping lives in process memory and is never
  intentionally written to disk or sent over the network.
- The extension holds an opaque session ID, not the mapping.
- PII detection and pseudonym generation run locally. An external provider is
  called only after the outbound leak guard accepts the masked text.
- The control plane uses a boot token when the bundled desktop shell launches
  the sidecar. The data plane remains compatible with the local extension
  channel described in the architecture docs.

The highest-severity local failure is real, unmasked PII reaching an external AI
through an intended AI Guard send path.

### Hosted platform service

Calling a hosted service sends raw input to the hosting platform and AI Guard
container. The local claim "PII never leaves the device" does not apply.

Hosted security relies on:

- caller authentication configured by `AIGUARD_API_KEY` or the official
  platform adapter;
- transient in-process mappings with no persistence;
- mappings omitted from normal queue results;
- PII-free application logs and safe public error bodies;
- separation between the AI Guard caller credential and Pathumma/TNER provider
  credentials; and
- a protected roundtrip that sends the downstream provider only masked text.

Failures that expose request text/mappings in platform-visible logs or results,
bypass hosted caller authentication, or send raw PII to Pathumma are in scope.
Retention and access inside infrastructure operated by the hosting platform are
also part of the platform trust model, but must be reported to the relevant
platform owner when they are outside this repository's code.

## Data and logging rules

- Tests, demos, issues, and vulnerability reproductions use synthetic PII.
- Application logs contain event types, counts, timings, and safe identifiers -
  never request text, entity values, mappings, provider response bodies, or
  secrets.
- Public errors expose stable categories, not payloads or upstream bodies.
- PDF temporary files are bounded and removed after processing.
- Session/container restart may discard mappings by design; persistence added
  for convenience would be a security-significant architectural change.

## Supply-chain and distribution model

Desktop installers are currently unsigned by design, so SmartScreen or
Gatekeeper warnings are expected. Releases publish `SHA256SUMS` and GitHub build
provenance. Verify with the instructions in the README.

Build inputs are pinned where the project can reliably pin them. Verification
proves artifact origin and integrity, not bit-for-bit reproducibility. A finding
that allows unreviewed code or an unexpected asset to receive first-party
release provenance is in scope.

Expected/out of scope by itself: the unsigned-publisher warning, loss of an
in-memory session after restart, and denial-of-service against a correctly
localhost-only personal backend. Resource exhaustion or cross-tenant impact on
an official hosted service remains in scope once that deployment exists.
