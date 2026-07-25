# AI for Thai integration

Updated: 2026-07-24

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

## What onboarding has and has not provided

The onboarding material received on 22 July is a general Docker, Docker
Compose, and GitLab CI fundamentals deck. It demonstrates FastAPI containers,
health checks, Compose networks/volumes, and CI runners. It does **not** define
the AI for Thai queue envelope, registry, credentials, retry rules, resource
ceilings, timeout, payload size, result size, logging retention, or outbound
network policy.

On 24 July, onboarding staff stated in the deployment group that:

- a GitLab user had been sent by email and the team was preparing the
  deployment repository; and
- the team would provide a separate LLM endpoint that is not subject to the
  normal per-account service limit.

The owner subsequently verified that the GitLab account can sign in to the
NECTEC GitLab instance. The Home page did not yet show a project, merge
request, work item, or pending to-do. This closes the account-login blocker but
not project provisioning. The repository URL, membership/role, CI variables,
and deployment instructions remain unverified. The separate LLM endpoint,
request contract, authentication, and policy have not yet been received.

The same discussion clarified that ordinary Pathumma, Arnthai, and Partii calls
made with a participant account consume that account's limit. Rotating personal
accounts may be useful during informal testing, but it is not an accepted
production credential or retry design. Hosted acceptance should use the
platform-issued endpoint and secret once provided.

The existing HTTP-poll worker transport is therefore still an adapter
placeholder, not a claim about the official wire protocol.

## Measured container profile

Measured from the production Dockerfile on 22 July 2026, using the default
offline CRF engine:

| Item | Observation | Request / policy |
|---|---|---|
| Model | PyThaiNLP `thainer-1.4` CRF, about 1.8 MB | CPU only; baked into image; runtime downloads disabled. |
| Image | Current local image is 115,898,138 bytes after excluding non-service build context. | Pull from a registry; do not build optional ML/OCR extras into this image. |
| Startup | Health ready in about 2 seconds locally | Platform readiness timeout should leave margin for slower hosts. |
| Memory | A post-workload Docker sample used 177.2 MiB of a constrained 1 GiB container; the earlier high-water observation was about 198 MB. | Request 1 GB RAM; 512 MB is a measured minimum test, not the production request. |
| CPU | Eight concurrent feature requests completed on one constrained vCPU without OOM | Request 1 vCPU initially; measure platform p95 before changing. |
| Disk | No database or persistent mapping volume | Request 10 GB for image/layer updates, bounded temp files, and rotated logs. |
| GPU | Not used | Do not request a GPU for the default service. |

These are operational observations, not platform limits. Re-measure inside the
allocated environment.

The [2026-07-24 Docker record](../acceptance/2026-07-24-docker-run.md) contains
the image ID, exact local constraints, endpoint latency, non-root check, and
PII-free log scan. It is local readiness evidence only.

## Trust boundary

The platform receives the raw request before AI Guard can sanitize it. The
hosted guarantees are:

- mappings remain transient and are not persisted;
- normal sanitize/analyze results do not export mappings;
- application logs and public errors do not contain request text or raw PII;
- Pathumma receives the masked prompt on the protected roundtrip; and
- provider credentials and the AI Guard caller key are separate secrets.

Do not use the local-product claim "PII never leaves the device" for this
deployment.

## Adapter boundary

The core handler accepts the internal versioned envelope:

```json
{
  "contract_version": 1,
  "job_id": "platform-job-id",
  "operation": "detect|sanitize|analyze|roundtrip",
  "payload": {}
}
```

The missing `contract_version` field remains accepted as version 1 only for
the original provisional fixtures. New fixtures and adapters must send it.
Unsupported versions fail before an operation sees the payload. The provisional
envelope defaults to a 1 MiB maximum; `AIGUARD_MAX_JOB_BYTES` may lower that
local limit while the platform value remains unknown.

The official adapter may translate a different queue message into this shape.
Only the adapter owns platform polling/consumption, acknowledgement, retries,
result submission, and authentication. Core operations must remain independent
of those details.

## Local emulator evidence

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

## Specification capture checklist

Complete this table immediately when the platform account/spec arrives:

| Area | Required answer |
|---|---|
| Account | Login verified; still need project membership/role and the support contact. |
| Registry | Repository/registry URL, namespace, tag/digest rule, architecture, and pull credentials. |
| Runtime | Docker/Compose/Kubernetes/runner, command, working directory, port or worker mode. |
| Job delivery | Queue technology, envelope, content type, ordering, at-least/at-most-once semantics. |
| Completion | Ack/nack timing, result endpoint/queue, duplicate job behavior, retry ownership. |
| Limits | CPU, RAM, disk, image, request/result bytes, concurrency, timeout, max processing time. |
| Networking | Inbound host/port, outbound allowlist for the platform LLM endpoint, Pathumma, and TNER; DNS and TLS policy. |
| Secrets | Injection method, header names, rotation, separation of caller/provider keys, and the promised LLM endpoint credential. |
| Logs | Capture destination, retention, access, redaction, stdout/stderr policy. |
| Health | Probe protocol/path, interval, startup grace, restart policy. |
| Acceptance | Required operations, fixtures, performance/SLA, owner and escalation path. |

## Acceptance sequence

1. Build the exact commit and identify the image by immutable digest.
2. Boot with no runtime model download and pass the platform health check.
3. Complete a synthetic Thai detect job and validate UTF-8 spans.
4. Complete sanitize and analyze jobs; confirm no mapping unless explicitly
   required by an approved contract.
5. Complete a protected Pathumma roundtrip if outbound access and credentials
   are approved.
6. Inject malformed, duplicate, timeout, provider-failure, and oversized jobs.
7. Restart during work and verify the platform retry/ack outcome.
8. Run the soak set and scan every application/platform-visible log for PII
   honeytokens.
9. Record actual p50/p95 latency, peak RAM/CPU, image digest, and limits.

Official acceptance evidence belongs in this file or a linked dated run report;
credentials and raw PII never do.
