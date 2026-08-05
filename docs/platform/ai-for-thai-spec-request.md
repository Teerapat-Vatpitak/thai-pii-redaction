# AI for Thai account and deployment specification request

- Prepared: 2026-07-27
- Status: ready to send after the official human recipient/support channel is
  confirmed; automated access messages prohibit replies
- Delivery deadline supplied by the project: 2026-08-17
- Presentation: 2026-08-19

This is a coordination draft, not platform acceptance. GitLab group access,
the participant deployment guide, and separate LLM access have arrived. The
remaining request is deliberately limited to facts needed by the official HTTP
adapter and acceptance run. It contains no credential or account identifier.

Suggested subject: `AI Guard — ขอ confirm HTTP deployment contract สำหรับ acceptance`

## Short Thai message

> เรียนทีม AI for Thai
>
> ทีม AI Guard ได้รับสิทธิ์ GitLab group, participant guide และข้อมูล
> LLM endpoint/model/credential ผ่านช่องทางส่วนตัวแล้วครับ จากคู่มือทีมเข้าใจ
> ว่า service จะเป็น FastAPI HTTP หลัง reverse proxy ที่ตัด `/api` prefix และ
> deploy Docker Compose จาก GitLab `main`
>
> เพื่อให้แก้เฉพาะ platform adapter โดยไม่เดา contract และเตรียม acceptance
> ให้เสร็จก่อนวันที่ 17 สิงหาคม 2569 รบกวนช่วยยืนยันรายการต่อไปนี้ครับ
>
> 1. ต้องใช้ repository URL, registry/tag rule และ project/template file ใด
>    บ้าง และส่งเฉพาะ API service ได้หรือจำเป็นต้องมี frontend service ด้วย
> 2. operation ที่ต้องเปิดสาธารณะมีอะไรบ้าง และ caller authentication ใช้
>    header/session แบบใด
> 3. request/result size, API concurrency, request/overall timeout, outbound
>    network allowlist และ proxy Host header ที่ backend จะได้รับ
> 4. LLM endpoint ที่ได้รับมี timeout ownership, quota, acceptable-use และ
>    logging policy อย่างไร
> 5. log retention/access/redaction, acceptance fixture/SLA/evidence,
>    ผู้อนุมัติผล และช่องทาง support/escalation อย่างเป็นทางการ
>
> หากมี template หรือเอกสาร contract อยู่แล้ว ส่งเป็น link ได้เลยครับ
> ทีมจะไม่ส่ง credential, raw PII หรือ mapping กลับทางข้อความ ขอบคุณครับ

## Answer ledger

| Area | Already received | Requested clarification |
|---|---|---|
| Access | GitLab sign-in and group membership work; participants create the project in the team subgroup. | Exact repository URL/rules, mandatory template files, and official support/escalation channel. |
| Delivery | FastAPI HTTP, reverse proxy, Docker Compose, GitLab `main`. | API-only versus mandatory frontend; required project files. |
| Routing | Public `/api` is stripped; backend health is `/health`; FastAPI docs use `root_path="/api"`. | Proxy Host header, exact public operations, and caller authentication. |
| Registry | GitLab is the delivery control plane. | Registry/repository, architecture, image tag/digest and build/pull rule. |
| Limits | CPU-only, service limits, bounded logs, CI timeout/concurrency are documented. | Request/result bytes, API concurrency, request/overall timeout, acceptance thresholds. |
| Networking | Public TLS/proxy and loopback host binding are documented. | Outbound DNS/TLS/allowlist for the issued LLM service, Pathumma, and TNER. |
| Secrets | Masked CI variables feed runtime; LLM access was delivered privately. | Exact required variable/header names, caller/provider separation, rotation, file-secret policy. |
| LLM | Endpoint, model identifier, and secret were issued; the current port uses an OpenAI-compatible protocol with private server-side authentication, and a developer-machine live run reached it. | Timeout ownership, quota, acceptable-use/logging policy, and a platform-originated live acceptance fixture. |
| Logging | Bounded rotation and platform log viewing are documented. | Retention, audience/access, captured fields, platform redaction and incident procedure. |
| Health | Backend `/health` and service health checks are required. | Probe interval, startup grace, restart and termination policy. |
| Acceptance | Delivery and presentation dates are known. | Required operations/fixtures, soak/SLA, evidence format, approving owner and sign-off path. |

## Safe attachments

Attach or link only:

- `docs/platform/ai-for-thai.md`;
- the container/resource summary without credentials;
- a synthetic API contract example only after the public operation set is
  confirmed.

Do not attach request text, mappings, access keys, provider responses, local
audit logs, or screenshots that reveal account identifiers.

## Follow-up schedule

- As of 2026-08-05, no official human recipient or support channel has been
  confirmed. The planned 2026-07-30 and 2026-08-03 follow-ups therefore could
  not be sent; do not reply to the automated access messages.
- The next action is owner confirmation of a human recipient or support
  channel, followed by this narrowed request.
- The unresolved public-operation/authentication and acceptance fields remain
  a risk to the 2026-08-17 deployment gate.
- Record answers in the integration document and a dated platform acceptance
  record; never copy credentials, account identifiers, raw requests, mappings,
  or provider bodies into the repository.
