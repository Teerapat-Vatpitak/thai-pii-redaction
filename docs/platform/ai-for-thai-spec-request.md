# AI for Thai account and deployment specification request

- Prepared: 2026-07-24
- Status: ready for the owner to send
- Delivery deadline supplied by the project: 2026-08-17
- Presentation: 2026-08-19

This is a coordination draft. It is not evidence that AI for Thai has issued
an account or accepted the provisional worker contract.

## Short Thai message

> เรียนทีม AI for Thai
>
> ทีม AI Guard เข้าร่วม onboarding แล้ว และกำลังเตรียม service สำหรับ
> deployment ให้เสร็จก่อนวันที่ 17 สิงหาคม 2569 ขณะนี้ยังไม่ได้รับ
> username/account และ specification ของแพลตฟอร์ม จึงขอข้อมูลตามรายการ
> ด้านล่าง เพื่อให้สร้าง image, ตั้งค่า secret และทดสอบ acceptance ได้ตรงกับ
> ระบบจริง หากบางรายการยังไม่กำหนด รบกวนระบุว่าไม่ใช้หรือให้ค่า default
> ชั่วคราว พร้อมช่องทางติดต่อเมื่อ deployment ติดขัด ขอบคุณครับ

## Required answers

| Area | Requested field |
|---|---|
| Account | Username/account, project or namespace, role, activation date, support contact. |
| Registry | Registry host, repository path, architecture, tag/digest rule, login method. |
| Runtime | Docker/Compose/Kubernetes/GitLab runner, worker or HTTP mode, start command, working directory. |
| Delivery | Queue/service technology, complete request envelope, content type, ordering, delivery guarantee. |
| Completion | Result destination, ack/nack rule and timing, retry owner, retry count/backoff, duplicate job rule. |
| Limits | CPU, RAM, disk, image size, input/result byte limits, concurrency, request/job timeout. |
| Networking | Inbound port/path, outbound DNS/TLS policy and allowlist for Pathumma/TNER. |
| Secrets | Injection method, required variable/header names, rotation, and whether secrets may be read from files. |
| Logging | Captured stdout/stderr fields, retention, access, redaction requirement, prohibited content. |
| Health | Startup/readiness/liveness probes, grace period, restart policy, termination grace. |
| Acceptance | Required operations and fixtures, soak/SLA requirement, evidence format, approving contact. |

## Safe attachments

Attach or link only:

- `docs/platform/ai-for-thai.md`;
- the container/resource summary without credentials;
- the internal version-1 envelope as an explicitly provisional example.

Do not attach request text, mappings, access keys, provider responses, local
audit logs, or screenshots that reveal account identifiers.

## Follow-up schedule

- GitLab login is verified. Check `Projects`, group membership, notifications,
  and pending to-do items for the deployment project without copying the
  username or credential into this repository.
- Ask staff to add the verified account to the deployment project and send the
  repository URL if it remains absent. Also request the promised separate LLM
  endpoint contract and secret-delivery method.
- If unanswered on 2026-07-28, send this checklist in writing.
- If account/spec remains unavailable on 2026-08-01, explicitly flag risk to
  the 2026-08-17 deployment gate.
- Record the received specification in the dated platform acceptance record;
  never copy credentials into the repository.
