# AI for Thai remaining operations and acceptance request

- Prepared: 2026-07-27
- Narrowed against the official Participant Guide: 2026-08-07
- Status: ready to send after an official human recipient/support channel is
  confirmed; automated access messages prohibit replies
- Delivery deadline supplied by the project: 2026-08-17
- Presentation: 2026-08-19

This is a coordination draft, not platform acceptance. GitLab group access,
the [Participant Guide](https://app.notion.com/p/PARTICIPANT-GUIDE_1-3a7488d61198800fb15fdcf8b40e9afe),
and separate LLM access have arrived. The guide confirms `team08`, ports
`20070/20071`, the frontend/API proxy shape, the root CI template, local
Compose build, health checks, resources, log rotation, `APP_*` secrets, and
no-SSH operations. The remaining request is deliberately limited to facts the
guide does not answer. It contains no credential or account identifier.

Suggested subject: `AI Guard team08 — ขอ confirm outbound/LLM และ acceptance policy`

## Short Thai message

> เรียนทีม AI for Thai
>
> ทีม AI Guard ได้รับสิทธิ์ GitLab group, participant guide และข้อมูล
> LLM endpoint/model/credential ผ่านช่องทางส่วนตัวแล้วครับ จากคู่มือทีมเข้าใจ
> ว่า frontend ใช้ `team08.aiforthai.in.th/`, API ใช้ `/api/` โดย proxy ตัด
> prefix ก่อนส่งเข้า backend, deploy Docker Compose จาก GitLab `main`, และ
> secret ใช้ masked `APP_*` CI variables
>
> ทีมเตรียม adapter ตาม template แล้ว เพื่อให้ปิดเฉพาะ operational และ
> acceptance gap ก่อนวันที่ 17 สิงหาคม 2569 รบกวนช่วยยืนยันรายการต่อไปนี้ครับ
>
> 1. runner/container ออกอินเทอร์เน็ตไปยัง LLM endpoint ที่ออกให้ รวมถึง
>    Pathumma/TNER ได้หรือไม่ มี DNS/TLS/allowlist ที่ต้องแจ้งล่วงหน้าหรือไม่
> 2. reverse proxy ส่ง `Host` ค่าใดเข้า API และมี request/body/stream timeout
>    หรือขนาดคำขอสูงสุดที่เข้มกว่าค่าที่แอปกำหนดเองหรือไม่
> 3. LLM endpoint ที่ได้รับมี timeout ownership, quota, acceptable-use และ
>    logging policy อย่างไร
> 4. log ที่ `/logs/` และฝั่งแพลตฟอร์มเก็บนานเท่าไร มีการ redact เพิ่มหรือไม่
> 5. acceptance ต้องใช้ fixture/SLA/evidence ใด ใครเป็นผู้อนุมัติผล และใช้
>    ช่องทางใดสำหรับ support/escalation
>
> สำหรับ business endpoints, payload limits และ concurrency ทีมจะกำหนดและ
> ทดสอบเป็น product contract เอง เว้นแต่แพลตฟอร์มมีเพดานที่เข้มกว่าคู่มือ
> ส่วน caller authentication เป็น product contract ที่ทีมอนุมัติและทำใน
> local candidate แล้ว คำถามที่เหลือคือ trusted client-IP signal และพฤติกรรม
> cookie/origin ผ่าน public HTTPS proxy จริง
>
> หากมีเอกสาร policy เพิ่มเติม ส่งเป็น link ได้เลยครับ
> ทีมจะไม่ส่ง credential, raw PII หรือ mapping กลับทางข้อความ ขอบคุณครับ

## Answer ledger

| Area | Already received | Requested clarification |
|---|---|---|
| Access | GitLab sign-in, team-subgroup membership, Maintainer rights, repository pattern, and the team-owned root CI template are known. | Official human support/escalation channel. |
| Delivery | Standard frontend `/` and backend `/api/`, Compose build from protected GitLab `main`, and no-SSH manual operations are documented. | Confirm that any runner with the production Docker socket is a Protected runner limited to protected refs, or provide an isolated branch daemon/runner; then complete actual runner/platform acceptance. |
| Routing | `team08` uses host ports `20070/20071`; public `/api` is stripped; backend health is `/health`; FastAPI uses `root_path="/api"` only when generated URLs/docs are exposed. Business operations and caller authentication are product-owned; the accepted signed-cookie boundary is implemented locally. | Actual proxy Host value, trusted client-IP signal for login limiting, public HTTPS cookie/origin behavior, and any stricter platform request/stream ceiling. |
| Build | The supplied job runs local `docker compose ... up -d --build`; the documented path does not require a registry pull. | Cold-runner time, built-image digest, and observed architecture. |
| Limits | CPU-only, per-service limits, the adjustable approximately 13 GiB team budget, 20-minute jobs, and concurrency of three are documented. The product owns its request/result/concurrency limits. | Platform resource measurements and any stricter infrastructure ceiling. |
| Networking | Public TLS/proxy and loopback host binding are documented. | Outbound DNS/TLS/allowlist for the issued LLM service, Pathumma, and TNER. |
| Secrets | Masked `APP_*` variables are passed through a mode-600 temporary env file that the deploy job removes; secrets stay out of frontend code and the repository. LLM access was delivered privately. | Reissue/rotate the provider credential exposed during a local Compose probe, then confirm rotation/distribution and file-secret policy. |
| LLM | Endpoint, model identifier, and secret were issued; the current port uses an OpenAI-compatible protocol with private server-side authentication, and a developer-machine live run reached it. | Timeout ownership, quota, acceptable-use/logging policy, and a platform-originated live acceptance fixture. |
| Logging | `json-file` rotation is `50m` times three; `/logs/` is team-only realtime/search/download access; CI has a manual logs job. | Time-based retention, platform redaction, and incident procedure. |
| Health | Backend `/health` must return 200; the template documents bounded probe timing and `unless-stopped` restart. | Actual cold-start/restart behavior and termination grace. |
| Storage | Bind mounts, if any, stay below `/data/hack/team08`; the selected candidate uses none. | Available disk/image-layer capacity on the runner. |
| Acceptance | The guide defines check → deploy → health as baseline; delivery and presentation dates are known. | Platform soak/SLA, evidence format, approving owner, and sign-off path. |

## Safe attachments

Attach or link only:

- `docs/platform/ai-for-thai.md`;
- the container/resource summary without credentials;
- a synthetic API contract example only after the product operation set is
  frozen.

Do not attach request text, mappings, access keys, provider responses, local
audit logs, or screenshots that reveal account identifiers.

## Follow-up schedule

- As of 2026-08-07, no official human recipient or support channel has been
  confirmed. The planned 2026-07-30 and 2026-08-03 follow-ups therefore could
  not be sent; do not reply to the automated access messages.
- The next action is owner confirmation of a human recipient or support
  channel, followed by this narrowed request.
- The remaining outbound-network, LLM-policy, platform-log, and acceptance
  fields remain a risk to the 2026-08-17 deployment gate. Business operations
  are product-owned and no longer treated as missing platform specifications.
  Caller authentication is also not a guide question. Its owner-approved
  signed-cookie contract is implemented locally; trusted proxy identity,
  public HTTPS browser behavior, and platform acceptance remain open.
- Record answers in the integration document and a dated platform acceptance
  record; never copy credentials, account identifiers, raw requests, mappings,
  or provider bodies into the repository.
