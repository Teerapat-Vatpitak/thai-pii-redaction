# AI for Thai integration

Updated: 2026-08-07

## Submitted service

AI Guard was submitted as a Thai PII detection and anonymization API service,
data-analysis system, and organizational automation component. Pathumma is a
protected downstream integration, not the identity of the product. TNER is an
explicit supplementary AI for Thai integration.

On current source, explicitly selecting TNER sends raw, pre-mask text chunks to
that remote detector. Default local detection does not. A failed TNER request
now aborts the whole operation as bounded `ner_unavailable` metadata; an
invalid, incomplete, misaligned, or unknown BIO/token stream aborts as
`ner_incomplete`. Earlier candidates are discarded, later chunks and providers
are not called, and no session or PDF output is published. This is automated
source behavior, not a fresh live TNER certification. The separate sibling port
may select or configure detectors differently, so its runtime
choice must be verified in that repository rather than inferred from this
document.

The historical submission capability concept was:

1. `detect` - identify PII and return spans/types;
2. `sanitize` - return masked text without returning the mapping by default;
3. `analyze` - return PDPA-oriented counts, risk, and Section 26 signals; and
4. `roundtrip` - optional protected Pathumma call with mapping lifetime limited
   to the job.

Current source has two HTTP delivery surfaces. The accepted
[2026-07-28 deployment decision](../decisions/2026-07-28-tokenmind-detector-and-aift-port.md)
selects the separate sibling repository for AI for Thai; the participant guide
fixes the platform plumbing but leaves each team to define its business
operations and caller security:

- main-repository `app.hosted` is strict HTTP v2 and hard-allows health,
  detect, analyze, guard, sanitize, reidentify, and roundtrip. Its
  sanitize/reidentify pair retains process session state; roundtrip is
  request-transient. It remains the generic hosted reference, not the selected
  AI for Thai deployment vehicle;
- the selected sibling retains its public unversioned and `/v1` aliases for
  `health`, `detect`, `guard`, `roundtrip`, `analyze-report`, and
  `redact-pdf`. Nginx now injects contract 2 into current shared core and the
  frontend consumes the minimized v2 DTOs. It intentionally returns 404 for
  `/sanitize` and `/reidentify`.

The sibling route set is the product's candidate public contract, not evidence
of a completed platform deployment. The accepted
[caller-auth ADR](../decisions/2026-08-07-aift-caller-authentication.md) keeps
static/health public and requires every business request to present a
short-lived signed cookie obtained from an access-code exchange. The browser
never receives the separate proxy-to-core or provider secret. Immutable commit
`e075ca4` has exact provider-free local check/deploy evidence; live-provider,
soak, OCR, and browser runs predating that commit remain dated evidence only.
Official-platform acceptance remains open.

Local session-based re-identification remains available to the desktop and
extension product. It is not assumed to survive platform container restarts or
cross-instance routing.

## Official onboarding state

The platform delivery shape is no longer unknown. The official
[Participant Guide](https://app.notion.com/p/PARTICIPANT-GUIDE_1-3a7488d61198800fb15fdcf8b40e9afe)
was rechecked on 2026-08-07. Together with the service-access messages received
between 25 and 27 July, it establishes that:

- the service provides HTTP frontend/API containers behind a same-origin HTTPS
  reverse proxy; the guide permits any Docker-capable framework;
- the assigned team is `team08`: the standard frontend is
  `https://team08.aiforthai.in.th/` on host port `20070`, the backend is under
  `/api/` on host port `20071`, and team-only realtime logs are under `/logs/`;
- the public `/api/...` prefix is stripped before the request reaches the API
  container; when FastAPI exposes generated docs or URLs, the guide shows
  `root_path="/api"`;
- the backend must expose an unprefixed `/health` route;
- the project lives under the team's GitLab subgroup, owns a root
  `.gitlab-ci.yml` copied from the supplied template, and deploys Docker
  Compose from `main`; branch builds may run checks but do not deploy;
- service ports published on the host bind to `127.0.0.1` within the assigned
  `20070`-`20079` range. Internal services need no host port, and teams may add
  them without staff action;
- containers are CPU-only, declare service resource limits and health checks,
  and use `json-file` rotation capped at `50m` times three files. The guide's
  example grants 2 GiB/2 CPU to the frontend and 4 GiB/4 CPU to the API and
  permits adjustment while the team total stays below about 13 GiB;
- application secrets are masked CI variables and are not committed or exposed
  to frontend code; the deploy job materializes every `APP_*` variable into
  `.env`;
- operational access is through CI and platform log tooling rather than SSH;
  the documented CI job timeout is 20 minutes and team concurrency is three;
  and
- the standard public shape contains both `/` frontend and `/api/` backend
  paths. The selected sibling already supplies both, so API-only acceptance is
  not a deployment blocker.

GitLab sign-in and group membership are verified, with Maintainer rights in the
team subgroup. The existing ADR selects the separate port repository described
below; the new main-repository candidate does not migrate or replace it. No
project has yet been pushed to GitLab. Project creation and any push remain
owner-gated.

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
[specification request](ai-for-thai-spec-request.md) is now narrowed to
outbound-network, LLM-policy, platform-log, and formal-acceptance questions; its
human recipient or support channel still needs confirmation.

The existing HTTP-poll worker and versioned job envelope are therefore retained
only as a provisional local failure emulator. They are not the official
delivery path.

## Port repository (selected deployment vehicle)

The accepted deployment design exists in a **separate port repository**
(`aiguard-aift`, targeted at the event's GitLab). It has not been pushed or
accepted as an official deployment.
This repo keeps its local-first role (extension, desktop, CLI, Office add-in);
the port is a thin service shell around a vendored slice of the core:

- a vendored `core/` slice — a per-file SHA-256 manifest pins the upstream
  commit `8c6efef` across 75 files — plus an OCR-baked image and a port-owned
  stateless auth wrapper. The wrapper changes admission only; detection,
  masking, provider, PDF, mapping and restoration remain vendored shared-core
  logic;
- an nginx `api/` layer that re-adds the `/api` prefix the platform proxy
  strips, exposes only a six-endpoint exact-match allowlist plus auth aliases,
  injects contract 2 and the service key for proxied business and health routes,
  clears both internal headers on auth routes, and removes query values from
  access and request-error output. The separate caller cookie gates business
  routes before they reach shared core; and
- a five-scene product page and a stateless roundtrip (mask → thaillm-8b →
  restore within one request). The roundtrip consumes its literal transient
  mapping internally and returns the minimized v2 projection with count/type,
  safety and restoration status, but no mapping, token/original pair, or
  token-bearing entity projection. The sibling has no independent service
  version; preserving its public aliases does not make it a v1 service or a
  second product release line. Its inherited `2.5.0` metadata is development
  product metadata, not hosted-release evidence.

The shell matches the guide's assigned shape locally: `team08`, frontend
`127.0.0.1:20070:3000`, API `127.0.0.1:20071:8000`, internal-only core,
per-service limits, mandatory health checks, `50m` times three log rotation,
masked `APP_*` materialization, `main`-only deployment, and no-SSH operations.
Its current Compose caps total memory at 6.5 GiB and CPU at 3.0, within the
guide's adjustable team budget. Exact local Docker build and health pass; this
is not a runner or platform acceptance result.

The pre-F09 port passed a full local Docker phase: the ก-ฌ checklist, fail-loud
and 503 failure modes, and a service-level soak (an 8-way 10-minute run with no
5xx, a 429 under overload rather than a crash, PII-free logs, and restart
recovery). This is exact historical evidence, not current fail-closed
certification. Immutable port commit
`e075ca46807a1d318447ed4280821941d20608ba` vendors `8c6efef` and passed
exact local BusyBox `check` in 28.0 seconds plus provider-free `deploy` in
244.3 seconds. All three services were healthy with matching revision labels;
the auth contract covers 11 cases, and the executable frontend/nginx/Compose/
upstream-object checks pass. Independent security/compatibility review found
no remaining static blocker. Exact live `acceptance` was not run because the
Tokenmind credential exposed by a read-only local Compose expansion must first
be rotated/reissued; the ignored local `.env` copy has been removed. Earlier
live Tokenmind, fake/live soak, scanned-OCR, and browser results remain dated
working-tree evidence. Pushing to GitLab and the real platform run remain
owner-gated. The
[tokenmind detector + port ADR](../decisions/2026-07-28-tokenmind-detector-and-aift-port.md)
records the decision and the thaillm-8b detector numbers.

## Measured container profile and official allocation

Measured from the then-current Dockerfile on 22 July 2026, using the default
offline CRF engine. These numbers predate the `app.hosted` entrypoint and route
surface and are historical. They are not the selected sibling's current image
profile:

| Item | Observation | Local target / platform use |
|---|---|---|
| Model | PyThaiNLP `thainer-1.4` CRF, about 1.8 MB | CPU only; baked into image; runtime downloads disabled. |
| Image | The dated local image was 115,898,138 bytes after excluding non-service build context. | Rebuild and identify the selected sibling's OCR-baked image by digest; the guide's CI builds Compose locally rather than requiring a registry pull. |
| Startup | Health ready in about 2 seconds locally | Platform readiness timeout should leave margin for slower hosts. |
| Memory | A post-workload Docker sample used 177.2 MiB of a constrained 1 GiB container; the earlier high-water observation was about 198 MB. | Historical main-image measurement only. The guide lists 2 GiB for frontend and 4 GiB for API as adjustable examples under an approximately 13 GiB team total; the sibling currently caps 6.5 GiB across web/api/core. |
| CPU | Eight concurrent feature requests completed on one constrained vCPU without OOM. | Historical main-image measurement only. The sibling currently caps 3 CPU across web/api/core; measure actual platform p95 and peak use. |
| Disk | No database or persistent mapping volume. | The sibling currently declares no bind mounts. Any future persistent mount must be an absolute path below `/data/hack/team08`; the guide does not state a disk quota. |
| GPU | Not used | Do not request a GPU for the default service. |

These are operational observations, not a platform quota or current-candidate
acceptance result. The sibling Compose declares per-service limits within the
guide's adjustable team allocation. The exact sibling candidate adds these
local observations:

| Item | Exact local observation for `e075ca4` | Boundary |
|---|---|---|
| Images | Web `ff8d654a...` = 26,020,221 bytes; API `2df7e1ac...` = 26,006,890 bytes; core `2d938778...` = 809,367,137 bytes. All were healthy with revision labels matching the commit. | These are local content IDs, not registry digests or platform-built identities. |
| Detect | 100/100 requests after warmup: p50 6.02 ms, p95 7.58 ms, max 12.57 ms. | Local loopback/provider-free result, not a platform SLA. |
| Report/PDF | Report route 0.5 seconds; one-page scanned PDF 221.0 seconds, average about 1.93/2 core CPUs, 6 GiB peak, `memory.events max=8247`, no OOM/restart, service still healthy. | Correctness passed for one synthetic page, but the resource result is red: the configured 20-page/300-second surface is not deploy-ready. Authoritative entity-to-box coverage also remains open. |

The exact synced image must still be measured on the platform.

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
  and the sibling's synced current-core result use minimized projections
  without token/original pairs or reconstructable token-bearing entities.
  Exact local response checks pass; official-platform acceptance remains
  unverified;
- application logs and public errors must not contain request text, raw PII, or
  bearer authority. Current-source shared-server API callers use fresh
  non-authorizing operation UUIDs rather than live restoration session IDs,
  while retaining the legacy audit field name. Local disk/configured-stdout
  regressions cover that source path. The sibling's current container logs
  passed synthetic PII, query, cookie and four-secret scans, including the
  nginx rate-limit warning path. Official platform log transport, retention,
  and visible scan remain unverified;
- the repository's current shared outbound policy fails closed for structured
  FP findings, text-based TB findings, detector-independent contiguous runs of
  six or more digits, and missing replacement records. CLI, HTTP, and worker
  paths rescan immediately before their provider calls. This is source-level
  automated evidence plus one dated pre-final sibling live Tokenmind smoke:
  the sibling carried `8c6efef`, masked the synthetic fixture, returned a
  minimized safe result, and wrote no tested request/cookie/secret value to
  runtime logs. Exact final-candidate live acceptance now waits for credential
  rotation; official hosted deployment remains. The
  port uses thaillm-8b through the tokenmind gateway, the only provider its
  hosted allowlist enables; and
- provider credentials and the AI Guard caller key are separate secrets.

Do not use the local-product claim "PII never leaves the device" for this
deployment.

## Official HTTP adapter boundary

The broad main FastAPI server remains local-first. `app.hosted` narrows it to a
seven-route, API-key-protected v2 reference, but it still uses `/api/health` and
does not by itself implement the platform prefix/proxy shape. The accepted
deployment decision instead uses the separate nginx-backed port. Its public
unversioned and `/v1` aliases proxy strict contract 2; they are not a v1
service-version claim. The guide
does not prescribe business operations or application authentication; those
are product-owned choices. The table below distinguishes locally encoded guide
requirements from evidence that still requires the real platform:

| Area | Local candidate implementation | Still unconfirmed or unaccepted |
|---|---|---|
| Route prefix | Nginx re-adds the `/api` prefix stripped by the platform and exposes the product's exact six-route allowlist. | Real reverse-proxy behavior and each selected operation on platform infrastructure. |
| FastAPI root | The public nginx shell keeps internal `/api/*` routes and intentionally closes generated docs, so it does not depend on exposed FastAPI docs URLs. | Platform request-path behavior; enable `root_path="/api"` only if generated docs become public. |
| Health | The port exposes unprefixed `/health`; web, proxy, and core health checks use the guide's 15-second interval and bounded retries, with service-specific startup periods. | Cold-start behavior, restart recovery, and termination grace on the runner/platform. |
| Host policy | The expected public host is `team08.aiforthai.in.th`; the port forwards the incoming host and allows that value plus loopback. | The actual forwarded Host value on the platform. |
| Public surface | The ADR-owned nginx allowlist withholds session/mapping routes. Static/health are public; business routes require an access-code exchange for a 30-minute signed secure cookie. Nginx separately injects contract 2 and its internal core key. Unit tests cover expiry and key rotation; container checks cover unauthenticated, tampered, cross-site and successful cookie flows. | Trusted proxy client-IP behavior for login limiting, downstream quota failure, public HTTPS cookie/origin behavior, and the exact route through the platform proxy. The guide defines no business-operation allowlist or caller-auth header. |
| Frontend | The sibling includes a five-scene same-origin product page on port `20070`, matching the standard `/` route. | Real browser behavior through the platform proxy. |
| Deployment | The sibling is based on the supplied template and encodes `team08`, ports `20070/20071`, local Compose build, main-only deploy, per-service limits, health, masked `APP_*`, bounded logs, and manual ops. | Actual GitLab runner execution, cold-build time, platform logs, and official acceptance. |

Do not change detection, masking, mapping lifecycle, residual leak checks,
provider calls, or restoration to satisfy this layer. The sibling's route
allowlist is a product boundary fixed by the existing ADR and tests, not a
platform-prescribed list. Do not expose mapping-return options, demo routes,
shutdown/session controls, or any other operation without a product decision
and privacy tests.

The remaining external answers are narrower: outbound-network policy; actual
proxy Host behavior; LLM quota, timeout, acceptable-use, and logging policy;
platform log retention/redaction; and formal acceptance owner/evidence. App
payload, concurrency, and timeout limits remain explicit product settings
unless the platform reports a stricter ceiling. Caller authentication,
current-core adaptation, response minimization, independent review, and exact
provider-free local check/deploy are complete. Exact live acceptance waits for
credential rotation. Before first push the team must also resolve the red PDF
resource/capability boundary and confirm a protected production runner or an
isolated daemon; the GitLab action remains separately owner-gated.

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
| Access | Login, team-subgroup membership, and Maintainer rights work. The guide gives the repository pattern `ai4thai-service-hackathon/<team-XX>/<repo-name>` and a root CI template. | Official human support/escalation channel and the exact project URL after owner-authorized creation. |
| Delivery | The standard shape is frontend `/` plus backend `/api/`; the selected sibling schedules its organizer pipeline only from protected `main`. | Staff confirmation that a runner with the production Docker socket is Protected and limited to protected refs, or an isolated branch daemon/runner; then actual GitLab runner and platform acceptance. |
| Routing | Team `08` uses frontend port `20070` and API port `20071`; public `/api` is stripped, backend health is `/health`, and exposed FastAPI docs use `root_path="/api"`. Business routes and caller auth are team-owned; the current candidate implements the accepted signed-cookie boundary. | Actual forwarded Host value and real proxy/cookie behavior. |
| Build | The supplied job runs `docker compose up -d --build --remove-orphans`; the documented path builds locally and does not require a registry pull. Exact local provider-free check/deploy passed on `e075ca4`, with local content IDs recorded above. | Cold-runner build time, exact platform-built digest, and platform architecture observation. |
| Limits | CPU-only; every service has declared limits. The guide lists frontend 2 GiB/2 CPU and API 4 GiB/4 CPU as adjustable examples below an approximately 13 GiB team total. CI timeout is 20 minutes and team concurrency is three. Exact local detect latency is recorded above; the one-page PDF resource gate is red at 221 seconds and the 6 GiB core ceiling. | Platform p50/p95 and peak resource evidence; any infrastructure ceiling stricter than the app's explicit request/result/concurrency/timeouts; a narrowed/disabled or redesigned PDF path. |
| Networking | Host ports bind to loopback; TLS and public routing are platform-owned. | Outbound DNS/TLS/allowlist policy for the issued LLM endpoint, Pathumma, and TNER. |
| Secrets | The guide supplies masked `APP_*` CI variables. The candidate passes them through a mode-600 temporary env file removed by the deploy job; secrets stay out of frontend code and the repository. The product separates caller access code, cookie signing key, proxy-to-core key, and Tokenmind key. A stale ignored local `.env` was removed without reading it after Compose exposed the provider credential in agent output. | Reissue/rotate that provider credential before any further use; confirm distribution policy and whether file-mounted secrets are allowed. |
| LLM | Endpoint, model identifier, and secret have been issued; the current port uses the OpenAI-compatible protocol and private server-side authentication. A dated developer-machine live run reached the service. | Credential rotation, timeout ownership, quota, acceptable use, logging, and a platform-originated live acceptance fixture. |
| Logs | Docker uses `json-file` rotation at `50m` times three. `/logs/` provides realtime, searchable, downloadable team-only Dozzle access; CI also has a manual logs job. | Time-based retention beyond rotation, captured fields, and platform-side redaction/incident procedure. |
| Health | Backend `/health` must return 200. The guide template uses interval 15s, timeout 5s, three retries, 40s startup; Compose uses `unless-stopped`. | Actual cold-start/restart behavior and termination grace on platform infrastructure. |
| Storage | Internal services need no host port. Any bind mount must be absolute below `/data/hack/team08`; the selected sibling declares none. | Platform disk-capacity observation for the OCR-baked image. |
| Acceptance | The guide defines check → deploy → health as the baseline and provides no business fixture or formal SLA. Synthetic data and PII-free evidence remain mandatory for AI Guard. | Platform soak, evidence format, approving owner, and sign-off path. |

## Acceptance sequence

1. Build the exact commit and identify the image by immutable digest.
2. Boot with no runtime model download and pass the platform health check.
3. Exercise every product-approved sibling operation with synthetic Thai input
   and validate UTF-8 spans and minimized response projections. The selected
   six-route public allowlist includes roundtrip and analyze-report and excludes
   sanitize/reidentify; the guide does not prescribe a business route set.
4. Exercise the accepted caller-auth/abuse boundary, including unauthorized,
   invalid-credential, rate-limit, and downstream-quota failures.
5. Confirm that no approved response exports a mapping.
6. Complete a protected roundtrip through the configured downstream provider
   if outbound access and credentials are approved. The current local port uses
   Tokenmind; that does not establish final platform approval.
7. Inject malformed, timeout, provider-failure, and oversized requests.
8. Restart during work and verify safe recovery. Test duplicate/retry behavior
   against the product's explicit HTTP/provider policy.
9. Run the soak set and scan every application/platform-visible log for PII
   honeytokens.
10. Record actual p50/p95 latency, peak RAM/CPU, image digest, and limits.

Official acceptance evidence belongs in this file or a linked dated run report;
credentials and raw PII never do.
