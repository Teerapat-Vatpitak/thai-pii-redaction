# AI for Thai integration

Updated: 2026-07-28

## Submitted service

AI Guard was submitted as a Thai PII detection and anonymization API service,
data-analysis system, and organizational automation component. Pathumma is a
protected downstream integration, not the identity of the product. TNER is an
explicit supplementary AI for Thai integration.

The hosted core offered to the platform is:

1. `detect` - identify PII and return spans/types;
2. `sanitize` - return masked text without returning the mapping by default;
3. `analyze` - return PDPA-oriented counts, risk, and Section 26 signals; and
4. `roundtrip` - optional protected Pathumma call with mapping lifetime limited
   to the job.

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
team subgroup, so the team creates its own project rather than waiting for a
staff-provisioned template. The deployment is built as a separate port
repository, not pushed from this repo (see "Port repository" below). No project
has yet been pushed to GitLab; that step is owner-gated.

The platform also issued a separate LLM endpoint, model identifier, and secret
through a private channel. This repository records only that they exist.
Request/response compatibility and authentication placement are now settled in
code — the gateway speaks an OpenAI-compatible `/v1` protocol, the `tokenmind`
provider drives it through `pii_redactor/openai_compat.py`, and the 2026-07-28
acceptance run reached the live model twice — while quota, acceptable-use
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

The AI for Thai deployment is built in a **separate port repository**
(`aiguard-aift`, targeted at the event's GitLab), not pushed from this repo.
This repo keeps its local-first role (extension, desktop, CLI, Office add-in);
the port is a thin service shell around a vendored slice of the core:

- a vendored `core/` slice — a per-file SHA-256 manifest pins the upstream
  commit, which now includes the hosted-readiness knobs from PR #101 — plus an
  OCR-baked image;
- an nginx `api/` layer that re-adds the `/api` prefix the platform proxy
  strips, exposes only a six-endpoint exact-match allowlist, injects the service
  key, and logs without the query string; and
- a five-scene product page and a stateless roundtrip (mask → thaillm-8b →
  restore within one request; the mapping returns to the caller and no vault is
  held server-side).

The port passed a full local Docker phase: the ก-ฌ checklist, fail-loud and 503
failure modes, and a service-level soak (an 8-way 10-minute run with no 5xx, a
429 under overload rather than a crash, PII-free logs, and restart recovery).
Evidence lives in the port repo's `docs/evidence/`. Pushing to GitLab and the
real platform run remain owner-gated. The
[tokenmind detector + port ADR](../decisions/2026-07-28-tokenmind-detector-and-aift-port.md)
records the decision and the thaillm-8b detector numbers.

## Measured container profile

Measured from the production Dockerfile on 22 July 2026, using the default
offline CRF engine:

| Item | Observation | Local target / platform use |
|---|---|---|
| Model | PyThaiNLP `thainer-1.4` CRF, about 1.8 MB | CPU only; baked into image; runtime downloads disabled. |
| Image | Current local image is 115,898,138 bytes after excluding non-service build context. | Pull from a registry; do not build optional ML/OCR extras into this image. |
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
hosted guarantees are:

- mappings remain transient and are not persisted;
- normal sanitize/analyze results do not export mappings;
- application logs and public errors do not contain request text or raw PII;
- the LLM receives only the masked prompt on the protected roundtrip — on the
  port repo that is thaillm-8b through the tokenmind gateway, which is the only
  provider the hosted allowlist enables; and
- provider credentials and the AI Guard caller key are separate secrets.

Do not use the local-product claim "PII never leaves the device" for this
deployment.

## Official HTTP adapter boundary

The shared core does not need a platform fork. The current local FastAPI server,
however, is not ready to be exposed by the documented reverse proxy without a
small, explicit hosted adapter/configuration layer:

| Area | Official guide / current code | Required adapter delta |
|---|---|---|
| Route prefix | Public `/api/...` is stripped before the container; current routes are declared as `/api/*`. | Expose only the approved operations as unprefixed backend routes while preserving the local `/api/*` contract. |
| FastAPI root | Generated platform URLs must understand the public prefix. | Set `root_path="/api"` only in the hosted configuration. |
| Health | Platform expects backend `/health`; current health is `/api/health`. | Add the unprefixed hosted health route used by Compose/proxy checks. |
| Host policy | Current trusted hosts are only `localhost` and `127.0.0.1`. | Add only the documented proxy host(s); do not broadly disable host validation. |
| Public surface | The local server contains endpoints beyond the submitted hosted operations, and its declared API-key middleware does not cover every possible provider-backed route. | Confirm the official operation list and caller authentication, then fail closed with an explicit route allowlist and uniform protection. |
| Frontend | Guide examples show frontend plus API; the submitted product is an API service. | Confirm that API-only deployment is accepted before adding any frontend service. |
| Deployment | Local Compose is a developer profile. | Add platform-specific Compose/CI, loopback port mapping, health check, resource limits, masked-variable mapping, and bounded logs without weakening local defaults. |

Do not change detection, masking, transient mapping, residual leak checks,
provider calls, or restoration to satisfy this layer. Do not expose
`/api/reidentify`, mapping-return options, demo routes, shutdown/session
controls, or PDF endpoints unless the official contract explicitly requires
and protects them.

The remaining answers are narrow but security-sensitive: approved operations,
caller-authentication/header rules, payload and timeout limits, proxy
hostnames, frontend requirement, project/template ownership, and acceptance
owner. Until those are confirmed, adapter code would encode guesses in a
public boundary.

Update (2026-07-28): this adapter is realized in the port repo's nginx layer —
prefix re-add, exact six-endpoint allowlist, key injection, unprefixed
`/health` — not by forking the main server. PR #101 added the env-gated pieces
the server itself owns (host allowlist via `AIGUARD_ALLOWED_HOSTS`, provider
allowlist via `AIGUARD_PROVIDERS`, audit-to-stdout, and public-input caps),
while the main server keeps its local `/api/*` contract unchanged. The open
contract questions above still gate the real platform run.

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
process-local and intentionally contains no durable mapping or payload. It can
avoid repeating a provider call after a failed submit followed by redelivery
in the same process. It cannot prove exactly-once behavior after a process or
container crash. That requires the official acknowledgement semantics and, if
necessary, a platform-supported idempotency store.

## Remaining specification checklist

Answered fields stay recorded here so a later message cannot silently return
the design to the old queue assumption.

| Area | Known | Still required |
|---|---|---|
| Access | Login and group membership work. | Who creates the project/template, repository URL, and official support/escalation channel. |
| Delivery | HTTP/FastAPI through the platform reverse proxy; Compose deploys from GitLab `main`. | Whether an API-only service is accepted and which files/template are mandatory. |
| Routing | Public `/api` is stripped; backend health is `/health`; FastAPI docs use `root_path="/api"`. | Exact proxy Host header, approved public operations, and caller-authentication model/header. |
| Registry | GitLab is the delivery control plane. | Image registry/repository rule, architecture, tag/digest rule, and whether CI builds or pulls. |
| Limits | CPU-only, declared service limits, bounded logs, 20-minute CI jobs, and team CI concurrency of three. | Request/result bytes, API concurrency, request/overall timeout, and exact acceptance thresholds. |
| Networking | Host ports bind to loopback; TLS and public routing are platform-owned. | Outbound DNS/TLS/allowlist policy for the issued LLM endpoint, Pathumma, and TNER. |
| Secrets | Masked CI variables feed the runtime environment; provider access was issued privately. | Required variable names, caller/provider separation, rotation, and whether file-mounted secrets are allowed. |
| LLM | Endpoint, model identifier, and secret have been issued. | Protocol/compatibility, auth placement, timeout, quota, acceptable use, logging, and live acceptance fixture. |
| Logs | Bounded container rotation and platform log viewing are required. | Retention, audience/access, stdout/stderr fields, and platform-side redaction/incident procedure. |
| Health | Backend `/health` plus container health checks are required. | Interval, startup grace, restart policy, and termination grace. |
| Acceptance | Synthetic data and PII-free evidence remain mandatory. | Required operations, fixtures, soak/SLA, evidence format, approving owner, and sign-off path. |

## Acceptance sequence

1. Build the exact commit and identify the image by immutable digest.
2. Boot with no runtime model download and pass the platform health check.
3. Complete a synthetic Thai detect request and validate UTF-8 spans.
4. Complete sanitize and analyze requests; confirm no mapping unless explicitly
   required by an approved contract.
5. Complete a protected Pathumma roundtrip if outbound access and credentials
   are approved.
6. Inject malformed, timeout, provider-failure, and oversized requests.
7. Restart during work and verify safe recovery. Test duplicate/retry behavior
   only when the official HTTP contract defines it.
8. Run the soak set and scan every application/platform-visible log for PII
   honeytokens.
9. Record actual p50/p95 latency, peak RAM/CPU, image digest, and limits.

Official acceptance evidence belongs in this file or a linked dated run report;
credentials and raw PII never do.
