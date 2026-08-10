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

- Current unreleased Desktop source no longer calls a fixed localhost service.
  Its only production data path is typed webview command → Rust Desktop client
  → authenticated native IPC → shared broker → broker-private authenticated
  HTTP-v2 backend. The Extension and Office paths still use the separately
  documented fixed localhost service. Host/origin restrictions on that service
  do not authenticate which process owns its port; Slice 4 does not strengthen
  those storefronts.
- The canonical pseudonym-to-original mapping lives in process memory and is
  not intentionally persisted. The published 2.5.0/v1 artifact sent direct or
  reconstructable mapping fields, raw Section 26 matches, and prompt-guard
  excerpts/rationales to first-party clients over loopback. Current unreleased
  source implements strict v2 DTOs without those fields and reduces findings
  to category/severity/count-only metadata. This is not a shipped-fix claim.
- The extension may retain a security-sensitive opaque HTTP session ID. The
  Desktop UI may retain only a connection/scope/generation-bound broker session
  handle; Python session IDs and mappings do not cross the broker. Both clients
  necessarily handle input/output text transiently.
- Default PII detection and pseudonym generation run locally. Installed Desktop
  fixes detection to local `thainer` and cannot select remote TNER. Outside that
  installed-product boundary, explicitly selected remote TNER sends raw pre-mask
  chunks to AI for Thai. Current-source outbound-capable local sanitization plus
  CLI, HTTP, and worker provider boundaries fail closed on the shared residual
  policy. This is automated source evidence; packaged, real-host, live-provider,
  and official hosted acceptance remains open.
- The native broker alone creates and retains private backend data/control
  credentials and owns the Python process. Current unreleased source makes
  session expiry eager at the
  exact TTL boundary and requires a short-lived, single-use disposal
  authorization derived inside the trusted control plane and bound to the
  target session. Only canonical unpadded base64url is accepted, and final
  expiry validation, replay consumption, and disposal serialize under the
  lifecycle lock. Missing configuration, malformed/noncanonical,
  expired/cross-session authority, and replay fail closed. The raw boot token
  no longer authorizes session disposal. Uvicorn access logging discards query
  values, replaces the bearer-like route value with a fixed marker, and
  suppresses unknown access-record shapes. Storefront code receives neither
  form of control authority. Desktop session/scope/window/app cleanup is now
  broker-backed and any unconfirmed cleanup disconnects fail closed; Extension
  and Office disposal remain open.
- A separately configured API key can authenticate HTTP callers, but normal
  fixed-port first-party clients still cannot authenticate the process that
  owns localhost. Desktop code neither reads nor uses this fixed-port key; its
  broker-generated private backend credential is never projected to Desktop,
  and Desktop has no backend/data-plane HTTP fallback.
- The owner closed the Slice 4 configuration P1 by selecting a credential-free
  installed Desktop/native-broker profile. It supports only local `thainer`;
  the backend provider allowlist is `fake` solely for internal conformance, and
  the webview exposes no provider command. Explicit unsupported engine/provider
  selectors fail before broker connection or launch with stable,
  value-free `ner_unavailable` or `provider_configuration` errors. Both native
  child seams construct their environment by querying only a fixed allowlist of
  ordinary runtime-variable names; provider/TNER credentials, URLs, transport
  controls, selectors, and fine-tuned model paths are never queried or copied.
  The policy then pins `AIGUARD_NER_ENGINE=thainer` and
  `AIGUARD_PROVIDERS=fake`. Desktop and broker
  no longer snapshot remote configuration independently, so a hostile parent
  environment or attaching Desktop cannot silently reconfigure a warm broker.
  Slice 4 integrated only after exact branch CI, cross-platform package smoke,
  and independent review passed.
- Credential-requiring providers and remote TNER for installed Desktop remain a
  separate future architecture capability. Any expansion requires an
  owner-approved ADR covering credential ownership, provisioning, permissions,
  storage, rotation, configuration identity/epoch, broker restart or
  reconfiguration, upgrade, uninstall, attestation, and cross-platform behavior.

The native broker's OS peer context and component path/build/digest checks
establish per-user process context and package consistency only. They are not
publisher attestation and do not claim protection from arbitrary malicious
code already running as the same OS user or replacement of an unsigned
installation. Desktop webview capabilities grant no shell, filesystem, native
networking, clipboard-read, or global-shortcut plugin access; navigation is
restricted to exact internal Tauri origins. A submitted Desktop data operation
is never replayed after timeout or disconnect, and malformed/unsafe results do
not authorize clipboard, UI, or file publication.

AppImage packaging stays fail closed across `linuxdeploy`'s ELF mutations. Its
pre-bundle resource is deliberately `{}`; only the checksum-pinned post-bundle
finalizer may hash the completed AppDir and repack it. For the pinned, scrubbed
no-sign/no-update invocation, it parses both little-endian x86-64 ELF64 runtime
prefixes, permits mutation only in the single non-executable, non-overlapping
16-byte `.digest_md5` section that appimagetool rewrites, and requires every
other prefix byte to match. Only after that source-level attestation does it
execute the repacked runtime to confirm its offset, re-extract it, and compare
the Desktop, broker, backend, and manifest bytes before atomic replacement.
Package smoke independently extracts and attests those bytes, then starts the
exact finalized outer file with `--appimage-extract-and-run`. Its four fixed,
create-new marker files live in a separately created canonical private
directory; an invalid supplied directory fails without falling back to package
cwd. After the cold run, the harness re-attests the retained root before a warm
verified-`AppRun` launch, then requires natural process-group and native-process
cleanup before recovery cleanup or deletion. This proves internal package
consistency and the named execution path, not normal FUSE/double-click,
installation, publisher provenance, or signing.

Historical dirty-tree Windows NSIS evidence provisionally exercised the
installed production package JavaScript, typed Tauri commands, broker path,
manifest consistency, and cleanup. It did not execute a provider or remote
TNER operation and does not close live-provider, provider-configuration,
clean-commit candidate, macOS/Linux package, upgrade, updater, uninstall, or
release gates. Checkpoint `3836024` passed CI but failed Linux AppImage
finalization before package smoke because its first prefix guard did not account
for the defined `.digest_md5` rewrite. Checkpoint `73dcca4` narrowed that
exception, but its harness bypassed the outer runtime and `AppRun`, so that run
did not establish AppImage execution. Checkpoint `8194c23` passed the separate
two-platform package workflow, including the exact outer AppImage path, while
its main CI failed only a non-portable canonical-path test construction.
Current checkpoint `492dad34361b09d7ffa58fa192a2447de7414418` repairs that
test construction. Exact [CI run
31349781519](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31349781519)
passed 14/14, and exact [cross-platform package run
31349781518](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31349781518)
passed 2/2. These automated results retain all evidence limits above.

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
  HTTP-v2/worker-v1 compatibility and shared provider-orchestration convergence
  are implemented in current source for CLI, HTTP/hosted roundtrip, and worker
  roundtrip; their packaged, live-provider, real-host, and official-platform
  gates remain open. Request-validation errors are fixed and do not
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
