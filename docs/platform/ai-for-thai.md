# AI for Thai integration

Updated: 2026-08-06

## Submitted service

AI Guard was submitted as a Thai PII detection and anonymization API service,
data-analysis system, and organizational automation component. Pathumma is a
protected downstream integration, not the identity of the product. TNER is an
explicit supplementary AI for Thai integration.

On current main, explicitly selecting TNER sends raw, pre-mask text chunks to
that remote detector. Default local detection does not. The separately
versioned sibling port may select or configure detectors differently, so its
runtime choice must be verified in that repository rather than inferred from
this document.

The historical submission capability concept was:

1. `detect` - identify PII and return spans/types;
2. `sanitize` - return masked text without returning the mapping by default;
3. `analyze` - return PDPA-oriented counts, risk, and Section 26 signals; and
4. `roundtrip` - optional protected Pathumma call with mapping lifetime limited
   to the job.

Current source has two distinct candidates and neither defines the official
contract:

- main-repository `app.hosted` is strict HTTP v2 and hard-allows health,
  detect, analyze, guard, sanitize, reidentify, and roundtrip. Its
  sanitize/reidentify pair retains process session state; roundtrip is
  request-transient;
- the separately versioned sibling remains HTTP v1. Its nginx
exact-match allowlist contains `health`, `detect`, `guard`, `roundtrip`,
`analyze-report`, and `redact-pdf`, plus `/v1/<same>` aliases. It intentionally
returns 404 for `/sanitize` and `/reidentify`.

These describe local candidates, not a completed official platform deployment
or approval of either route set.

Local session-based re-identification remains available to the desktop and
extension product. It is not assumed to survive platform container restarts or
cross-instance routing.

## Official onboarding state

The platform delivery shape is no longer unknown. The participant guide and
service-access messages received between 25 and 27 July establish that:

- the service is an HTTP/FastAPI application behind a same-origin HTTPS reverse
  proxy;
- the public `/api/...` prefix is stripped before the request reaches the API
  container, while FastAPI should use `root_path="/api"` so generated docs and
  URLs remain correct;
- the backend must expose an unprefixed `/health` route;
- GitLab CI deploys Docker Compose from `main`; service ports published on the
  host bind to `127.0.0.1` within the assigned range;
- containers are CPU-only, declare service resource limits and health checks,
  and use bounded log rotation;
- application secrets are masked CI variables and are not committed or exposed
  to frontend code; the deploy job materializes the runtime environment;
- operational access is through CI and platform log tooling rather than SSH;
  the documented CI job timeout is 20 minutes and team concurrency is three;
  and
- the guide examples contain both frontend and API services, but they do not
  yet answer whether this API-only submission must add a frontend.

GitLab sign-in and group membership are verified, with Maintainer rights in the
team subgroup. Historical deployment preparation used the separate port
repository described below; the new main-repository candidate does not migrate,
replace, or authorize a push of that sibling. No project has yet been pushed to
GitLab; repository selection and any push remain owner-gated.

The platform also issued a separate LLM endpoint, model identifier, and secret
through a private channel. This repository records only that they exist.
The dated developer-machine candidate established OpenAI-compatible
request/response behavior and server-side provider-auth placement: the gateway
speaks a `/v1` protocol, the `tokenmind` provider drives it through
`pii_redactor/openai_compat.py`, and the 2026-07-28 acceptance run reached the
live model twice. Quota, acceptable-use
policy, logging policy, timeout ownership, and an acceptance run originating
from platform infrastructure rather than a developer machine are still open.
Credentials, account identifiers, and provider bodies must never be copied into
this repository or its acceptance artifacts.

The automated access messages explicitly prohibit replies, while the guide says
to contact staff without naming an official support address. A targeted
[specification request](ai-for-thai-spec-request.md) is ready, but its recipient
or support channel still needs confirmation.

The existing HTTP-poll worker and versioned job envelope are therefore retained
only as a provisional local failure emulator. They are not the official
delivery path.

## Port repository (deployment vehicle)

Historical deployment preparation exists in a **separate port repository**
(`aiguard-aift`, targeted at the event's GitLab). It has not been pushed or
accepted as an official deployment.
This repo keeps its local-first role (extension, desktop, CLI, Office add-in);
the port is a thin service shell around a vendored slice of the core:

- a vendored `core/` slice — a per-file SHA-256 manifest pins the upstream
  commit with the hosted-readiness knobs from PR #101 — plus an OCR-baked
  image. That pinned core predates F09 and requires a separately authorized
  re-vendor and privacy/soak rerun before any first push;
- an nginx `api/` layer that re-adds the `/api` prefix the platform proxy
  strips, exposes only a six-endpoint exact-match allowlist, injects the service
  key, and logs without the query string; and
- a five-scene product page and a stateless roundtrip (mask → thaillm-8b →
  restore within one request). The current sibling v1 roundtrip consumes its
  literal transient mapping internally, but its returned token-bearing
  `entities[]` uses original-space offsets and permits reconstruction against
  caller-held source text. Hosted response minimization therefore remains open.
  The sibling remains separately versioned; it is not migrated to the
  main-repository HTTP v2 contract.

The pre-F09 port passed a full local Docker phase: the ก-ฌ checklist, fail-loud
and 503 failure modes, and a service-level soak (an 8-way 10-minute run with no
5xx, a 429 under overload rather than a crash, PII-free logs, and restart
recovery). This is exact historical evidence, not current fail-closed
certification. Evidence lives in the port repo's `docs/evidence/`. Pushing to
GitLab and the real platform run remain owner-gated. The
[tokenmind detector + port ADR](../decisions/2026-07-28-tokenmind-detector-and-aift-port.md)
records the decision and the thaillm-8b detector numbers.

## Measured container profile

Measured from the then-current Dockerfile on 22 July 2026, using the default
offline CRF engine. These numbers predate the `app.hosted` entrypoint and route
surface and are historical until the exact current image is rebuilt:

| Item | Observation | Local target / platform use |
|---|---|---|
| Model | PyThaiNLP `thainer-1.4` CRF, about 1.8 MB | CPU only; baked into image; runtime downloads disabled. |
| Image | The dated local image was 115,898,138 bytes after excluding non-service build context. | Pull from a registry; do not build optional ML/OCR extras into this image. |
| Startup | Health ready in about 2 seconds locally | Platform readiness timeout should leave margin for slower hosts. |
| Memory | A post-workload Docker sample used 177.2 MiB of a constrained 1 GiB container; the earlier high-water observation was about 198 MB. | Request 1 GB RAM; 512 MB is a measured minimum test, not the production request. |
| CPU | Eight concurrent feature requests completed on one constrained vCPU without OOM | Request 1 vCPU initially; measure platform p95 before changing. |
| Disk | No database or persistent mapping volume | Request 10 GB for image/layer updates, bounded temp files, and rotated logs. |
| GPU | Not used | Do not request a GPU for the default service. |

These are operational observations and the repository's initial request
profile, not authority to exceed the team allocation in the participant guide.
The official Compose file must declare per-service limits within that
allocation, then the profile must be re-measured on the platform.

The [2026-07-24 Docker record](../acceptance/2026-07-24-docker-run.md) contains
the image ID, exact local constraints, endpoint latency, non-root check, and
PII-free log scan. It is local readiness evidence only.

## Trust boundary

The platform receives the raw request before AI Guard can sanitize it. The
intended hosted boundaries, with current hardening exceptions called out, are:

- canonical mappings are not deliberately written to disk. Main
  sanitize/reidentify retain an in-process session mapping until
  service-managed eager expiry at the exact `age >= TTL` boundary, eviction, or
  restart and expose no hosted disposal route; main roundtrip and sibling
  roundtrip use request-transient mappings;
- normal hosted results must not export explicit mapping DTOs. Current main v2
  uses minimized projections without token/original pairs or reconstructable
  original-space entities. The sibling port's v1 roundtrip still returns
  token-bearing entity projections with original-space offsets that permit
  reconstruction against caller-held source text. Main exact-image acceptance,
  sibling response minimization, and official-platform acceptance remain
  unverified;
- application logs and public errors must not contain request text, raw PII, or
  bearer authority. Current-source shared-server API callers use fresh
  non-authorizing operation UUIDs rather than live restoration session IDs,
  while retaining the legacy audit field name. Local disk/configured-stdout
  regressions cover that source path. The separately versioned sibling port and
  official platform log transport, retention, and visible scan remain
  unverified;
- the repository's current shared outbound policy fails closed for structured
  FP findings, text-based TB findings, detector-independent contiguous runs of
  six or more digits, and missing replacement records. CLI, HTTP, and worker
  paths rescan immediately before their provider calls. This is source-level
  automated evidence only: the separately versioned sibling still carries a
  pre-F09 core, so it requires an authorized core sync and masked-only/
  fail-closed recertification alongside packaged compositions, live providers,
  and official hosted deployment. The port uses thaillm-8b through the
  tokenmind gateway, the only provider its hosted allowlist enables; and
- provider credentials and the AI Guard caller key are separate secrets.

Do not use the local-product claim "PII never leaves the device" for this
deployment.

## Official HTTP adapter boundary

The broad main FastAPI server remains local-first. `app.hosted` narrows it to a
seven-route, API-key-protected v2 candidate, but it still uses `/api/health` and
does not by itself implement or prove the platform prefix/proxy contract. The
separate port repository realizes a different v1 nginx-backed shell. The table
below describes that historical sibling candidate; neither candidate's public
contract or platform behavior is confirmed:

| Area | Local candidate implementation | Still unconfirmed or unaccepted |
|---|---|---|
| Route prefix | Nginx re-adds the stripped `/api` prefix and exposes an exact six-route allowlist while main keeps `/api/*`. | Approved public operations and proxy behavior. |
| FastAPI root | The port supplies hosted root-path/configuration rather than changing the local server default. | Generated URL behavior on platform infrastructure. |
| Health | The port exposes unprefixed `/health` for Compose/proxy checks. | Probe interval, grace, restart, and termination policy. |
| Host policy | PR #101 provides the env-gated host allowlist and the port config narrows the candidate. | Exact proxy Host header(s). |
| Public surface | Nginx uses an exact allowlist and server-side key injection. | Official operation list and caller authentication/header rules. |
| Frontend | The sibling includes a five-scene product page. | Whether that frontend is required and accepted. |
| Deployment | The sibling includes platform-shaped Compose/CI, loopback publication, health, limits, masked variables, and bounded logs. | Exact repository/registry/template rules and official platform acceptance. |

Do not change detection, masking, mapping lifecycle, residual leak checks,
provider calls, or restoration to satisfy this layer. Main's generic candidate
currently includes reidentify, while the sibling excludes it; neither choice
is official approval. Do not expose mapping-return options, demo routes,
shutdown/session controls, PDF endpoints, or any other operation on the
official surface unless the confirmed contract requires and protects it.

The remaining answers are narrow but security-sensitive: approved operations,
caller-authentication/header rules, payload and timeout limits, proxy
hostnames, frontend requirement, exact repository/registry/template-file
rules, and acceptance owner. Until those are confirmed, changing the adapter
would encode guesses in a public boundary. Before any first push, the candidate
also needs its pinned core re-vendored from current main and the privacy,
Docker, and soak evidence rerun; do not patch a divergent core in the sibling.

## Provisional worker emulator evidence

The deterministic pre-platform runner is:

```powershell
$env:PYTHONUTF8='1'
.\.venv\Scripts\python.exe scripts\run_worker_acceptance.py
```

It covers the stable operations, malformed/version/size failures, concurrent
handling, provider timeout, a substituted handler crash, duplicate conflicts,
result-submit failure, and same-process duplicate suppression. It also scans
worker-visible logs and public error results with a synthetic honeytoken. See
the [dated acceptance record](../acceptance/2026-07-24-worker-emulator-run.md).

This is readiness evidence, not platform evidence. The result cache is
process-local and never persisted, but it transiently holds the complete
worker result until eviction or clear; an opt-in version-1 sanitize result can
therefore include its internal mapping. The cache can avoid repeating a
provider call after a failed submit followed by redelivery in the same
process. It cannot prove exactly-once behavior after a process or container
crash. That requires the official acknowledgement semantics and, if necessary,
a platform-supported idempotency store.

## Remaining specification checklist

Answered fields stay recorded here so a later message cannot silently return
the design to the old queue assumption.

| Area | Known | Still required |
|---|---|---|
| Access | Login and group membership work; participants create the project in the team subgroup. | Exact repository URL/rules, mandatory template files, and official support/escalation channel. |
| Delivery | HTTP/FastAPI through the platform reverse proxy; Compose deploys from GitLab `main`. | Whether an API-only service is accepted and which files/template are mandatory. |
| Routing | Public `/api` is stripped; backend health is `/health`; FastAPI docs use `root_path="/api"`. | Exact proxy Host header, approved public operations, and caller-authentication model/header. |
| Registry | GitLab is the delivery control plane. | Image registry/repository rule, architecture, tag/digest rule, and whether CI builds or pulls. |
| Limits | CPU-only, declared service limits, bounded logs, 20-minute CI jobs, and team CI concurrency of three. | Request/result bytes, API concurrency, request/overall timeout, and exact acceptance thresholds. |
| Networking | Host ports bind to loopback; TLS and public routing are platform-owned. | Outbound DNS/TLS/allowlist policy for the issued LLM endpoint, Pathumma, and TNER. |
| Secrets | Masked CI variables feed the runtime environment; provider access was issued privately. | Required variable names, caller/provider separation, rotation, and whether file-mounted secrets are allowed. |
| LLM | Endpoint, model identifier, and secret have been issued; the current port uses the OpenAI-compatible protocol and private server-side authentication, and a developer-machine live run reached the service. | Timeout ownership, quota, acceptable use, logging, and a platform-originated live acceptance fixture. |
| Logs | Bounded container rotation and platform log viewing are required. | Retention, audience/access, stdout/stderr fields, and platform-side redaction/incident procedure. |
| Health | Backend `/health` plus container health checks are required. | Interval, startup grace, restart policy, and termination grace. |
| Acceptance | Synthetic data and PII-free evidence remain mandatory. | Required operations, fixtures, soak/SLA, evidence format, approving owner, and sign-off path. |

## Acceptance sequence

1. Build the exact commit and identify the image by immutable digest.
2. Boot with no runtime model download and pass the platform health check.
3. Exercise every approved public operation with synthetic Thai input and
   validate UTF-8 spans and strict response projections. Main `app.hosted` has
   a seven-route v2 allowlist including stateful sanitize/reidentify; the
   sibling v1 candidate has a different six-route allowlist that includes
   roundtrip and analyze-report and excludes sanitize/reidentify. Neither is
   the official operation contract.
4. Confirm that no approved response exports a mapping.
5. Complete a protected roundtrip through the configured downstream provider
   if outbound access and credentials are approved. The current local port uses
   Tokenmind; that does not establish final platform approval.
6. Inject malformed, timeout, provider-failure, and oversized requests.
7. Restart during work and verify safe recovery. Test duplicate/retry behavior
   only when the official HTTP contract defines it.
8. Run the soak set and scan every application/platform-visible log for PII
   honeytokens.
9. Record actual p50/p95 latency, peak RAM/CPU, image digest, and limits.

Official acceptance evidence belongs in this file or a linked dated run report;
credentials and raw PII never do.
