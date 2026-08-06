# F-06 eager session lifecycle and authenticated disposal

- Evidence date (Asia/Bangkok): `2026-08-06`
- Clean base commit: `35b451768db420bb6c6c6e20120f6105bff5336d`
- Candidate branch: `codex/phase-7-session-lifecycle`
- Original Phase 7 commit: `f968833fd563b530bb68a5104ea9969ad537dd94`
- Corrective commit: `b9c0b745f07059850592977c904f22098c1e41b7`,
  directly on top of `f968833`
- Review-follow-up commit: `6cd109d11478a05e711064d227a8241ecb38ea39`,
  directly on top of `b9c0b745`
- Product version: `2.5.0` (unchanged)
- Status: **corrected; independent re-review pending**

This is current-source automated corrective evidence for Phase 7 / F-06. The
first independent merge review rejected `f968833` with six confirmed blockers;
this record covers their fixes, backend session lifetime, internal
authenticated disposal, log secrecy, deterministic cleanup, and races. It is
not independent merge approval or packaged/installed, browser, Office-host,
live-provider, deployment, release, or official-platform evidence.

All runtime checks used synthetic values. This record contains no request text,
entity value, mapping, credential, provider body, restored answer, or
machine-specific artifact.

## Behavior established

`SessionService` is the sole TTL authority for its managed vaults and owns one
timer for the earliest active deadline. A session is available immediately
before its boundary and unavailable at `age >= TTL`; managed vaults cannot make
a second conflicting expiry decision. Standalone vaults retain the same exact
idle boundary. The callback expires due sessions without a later request and
reschedules for the next session. Timer generations prevent canceled or stale
callbacks from reviving or re-cleaning state. A request admitted under the
lifecycle lock before its deadline completes atomically. Successful sanitize
and restore refresh once at commit. Failed and repeated failed restore leave
the original access time, deadline, and timer unchanged, including immediately
before expiry and while racing the eager callback.

The existing internal `DELETE /api/session/{session_id}` route requires exactly
one short-lived HMAC authorization derived from the configured control secret.
The signed message binds the contract context, target session, expiry, and a
random nonce. Only canonical unpadded base64url is accepted, and replay identity
is derived from canonical authenticated content. Missing, malformed,
noncanonical, invalid, expired, duplicate-header, cross-session, and replayed
authority fails closed with a bounded error. Final expiry validation, replay
consumption, and disposal occur under the lifecycle lock; authority that
expires while waiting is rejected without consumption or disposal. Raw
boot-token use and an unset control secret do not authorize disposal. A fresh
authorization makes repeated disposal idempotent; the same authorization is
single-use, including concurrent use.

Uvicorn access logging stays enabled for non-sensitive operations. The
disposal request target is reduced to `/api/session/[redacted]` at the backend
logging boundary before launcher output or Desktop sidecar forwarding. Query
values are discarded, and an unknown Uvicorn access-record shape is suppressed
fail-closed. Bounded real-Uvicorn HTTP regressions cover launcher-configured and
default CLI startup, capture stdout and stderr, and reject the session ID,
derived authorization, control secret, request PII, and query authority while
requiring a health access row and the fixed redacted disposal row.

Expiry, authenticated disposal, capacity eviction, shutdown, and lifecycle
failure detach only the owned session and clear its vault mappings, entity
references, trusted digests, and salt. Shutdown also cancels timer state and
clears bounded authorization-replay fingerprints and hashed tombstones.
Cleanup is idempotent and serialized against active sanitize/restore work. If a
required timer cannot start, the service closes and releases detached plus
registered sessions rather than continuing without eager expiry.

The reviewed session resource inventory found no session-owned provider
handle/state, child process or process handle, port/listener, temporary path,
or delivery queue in the current architecture. Providers are per-call
resources, and process-audit records use non-authorizing operation IDs rather
than a restoration namespace. Tests therefore exercise the resources the
session service actually owns and do not claim cleanup for nonexistent
ownership.

Restart constructs an empty service; old session IDs, mappings, replay state,
and callbacks cannot be revived. The hosted route allowlist still excludes
session disposal.

## Local verification

| Gate | Result |
|---|---|
| Focused lifecycle/core/authentication/API matrix | PASS — 312 passed, 1 warning |
| Hosted/API/shutdown/cleanup matrix | PASS — 526 passed, 1 warning |
| Full Python suite | PASS — 2,255 passed, 5 skipped, 1 warning in 172.24 seconds |
| Documentation coverage | PASS — 6 passed |
| Root/desktop/extension JavaScript | PASS — 123 passed |
| Desktop Rust tests | PASS — 31 passed |
| `python -m ruff check .` | PASS |
| `python -m ruff format --check .` | PASS — 217 files |
| Version synchronization | PASS — `2.5.0` |
| Release-readiness check | PASS — 39 tests plus both scripts |
| Performance gate | RED — both exact follow-up runs recorded; baseline unchanged |
| `git diff --check` | PASS |
| Corrective read-only security review | PASS — two follow-up gaps fixed; final focused checks found no blockers |
| Corrective branch CI | PASS — `b9c0b745`, run `31090571421`, 11/11 jobs |
| Post-CI independent merge re-review | BLOCKED on `b9c0b745` — callback fail-closed and stale-status findings corrected here |
| Follow-up branch CI | PASS — `6cd109d1`, run `31092753172`, 11/11 jobs |
| Final independent merge re-review | PENDING — do not treat Phase 7 as merge-approved |

The warning is the existing Starlette/httpx TestClient deprecation warning.
The five skips are optional OpenCV OCR cases because `cv2` is not installed.
Corrective commit `b9c0b745` passed all 11 jobs in
[run 31090571421](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31090571421).
Review-follow-up `6cd109d1` passed all 11 jobs in
[run 31092753172](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31092753172).
Its final independent re-review remains pending.

The principal commands were:

```powershell
$env:PYTHONUTF8='1'
.\.venv\Scripts\python.exe -m pytest tests\test_session_lifecycle.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_session_lifecycle.py tests\test_session_service.py tests\test_step4_vault.py tests\test_api_token.py tests\test_api_hardening.py tests\test_http_v2_contract.py tests\test_uvicorn_log_secrecy.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_session_lifecycle.py tests\test_session_service.py tests\test_step4_vault.py tests\test_api_token.py tests\test_api_hardening.py tests\test_http_v2_contract.py tests\test_step11_api.py tests\test_api_demo.py tests\test_hosted_readiness.py tests\test_platform_api_contract.py tests\test_safe_errors.py tests\test_launcher.py tests\test_uvicorn_log_secrecy.py tests\test_worker_handler.py tests\test_worker_runner.py tests\test_worker_acceptance_runner.py -q
.\.venv\Scripts\python.exe -m pytest -q
npm run test:js
cargo test --manifest-path desktop\src-tauri\Cargo.toml
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe scripts\measure_perf.py
.\.venv\Scripts\python.exe scripts\check_version.py
.\.venv\Scripts\python.exe scripts\check_release_readiness.py
git diff --check
```

## Performance

Two consecutive exact follow-up commands remained red against the older
committed anchors:

| Operation | First run | Repeat | Committed baseline | Formal result |
|---|---:|---:|---:|---|
| Detect | 5.70 ms | 7.50 ms | 5.73 ms | first within; repeat +31% |
| Sanitize | 15.12 ms | 19.16 ms | 10.08 ms | +50% / +90% |
| Restore | 0.24 ms | 0.27 ms | 0.28 ms | both within |
| PDF redact | 74.58 ms | 84.23 ms | 67.67 ms | first within; repeat +24% |
| Resident memory | 151.4 MiB | 151.5 MiB | 151.4 MiB | both within |

Neither original Phase 7 nor this correction alters the sanitize detection,
replacement, token shape, or residual-policy algorithm, and the performance
harness constructs `SessionService` without a timer factory, so it cannot
exercise this follow-up's callback change. The pre-existing
longer-token/full-residual-scan trade remains the established explanation for
the red sanitize anchor and was owner-accepted on 2026-08-06. Detect and PDF
crossed their stale anchors only in the immediate repeat, demonstrating the
already recorded machine variability without changing those paths. Both red
results are retained here, and the baseline was not changed.

## First merge-review findings and corrective disposition

The first independent merge review rejected original commit `f968833` with six
confirmed blockers:

1. Restore used a touching lookup before reverse mapping, so failed attempts
   renewed retention. Restore now uses non-touching admission and refreshes
   access/timer once only after success.
2. Managed service and vault clocks made competing TTL decisions. Managed
   vault idle expiry is now disabled; `SessionService` owns the exact boundary,
   while standalone vault expiry remains `age >= TTL`.
3. Base64url decoding accepted non-zero unused pad bits and replay identity
   hashed supplied text. Decode/re-encode canonical equality is now mandatory,
   and the fingerprint hashes canonical authenticated bytes.
4. Authorization expiry was checked before lock acquisition. The authoritative
   clock is now invoked inside the lifecycle lock immediately before replay
   insertion and disposal.
5. Uvicorn logged the bearer-like disposal path and Desktop forwarded it. A
   fixed-value access-log filter now removes the route value before either
   output boundary while retaining safe operational logs.
6. Current-state documents claimed raw-token disposal, lazy hosted expiry, and
   merge-review PASS. They now describe the corrected behavior and carry
   **corrected; independent re-review pending**.

The two corrective read-only reviewers then found two gaps in the initial
correction. Deadline/clock calculation was outside part of the scheduler's
fail-closed guard, and aggregate-only finiteness validation could hide a later
invalid deadline; the scheduler now validates every deadline and its clock and
clears/closes on any scheduling prerequisite failure. The initial access-log
filter assumed Uvicorn's current private tuple shape; unknown shapes are now
suppressed, queries are discarded, and real regressions cover both launcher and
default CLI startup. Deterministic reviewer-remediation tests pass, and both
reviewers' final focused checks found no remaining blocker.

The earlier internal Phase 7 review still explains the detached-cleanup,
timer-start, active-request, and metadata-cache corrections already present in
`f968833`; it did not cover the six later merge blockers. The corrective
read-only review is complete.

Corrective commit `b9c0b745` then passed branch CI 11/11. Its post-CI
independent re-review found that `_expiry_timer_fired` removed the live timer
before an unguarded clock read, so an ordinary clock failure could retain every
mapping with the service still open and no eager timer. It also found the
pre-push/CI status text had become stale. The follow-up validates callback time,
routes every ordinary callback failure through the same close/invalidate/clear
path, preserves process-signal propagation, and adds deterministic exception,
`NaN`, and infinity regressions. This record now carries the exact first CI
evidence. Follow-up `6cd109d1` also passed branch CI 11/11; another fresh
independent merge re-review remains pending.

## Evidence boundaries and deferrals

The control secret and derived authorization remain inside trusted
native/backend code. Browser, Office, and extension code receive neither, and
no client-side disposal was implemented.

Phase 8 still owns:

- the native localhost broker and authenticated backend identity;
- broker-backed Desktop, extension, and Office disposal;
- fail-closed explicit TNER behavior;
- shared protected-provider orchestration; and
- authoritative PDF source-to-box intervals.

All eight Office real-host/package gates remain pending. No Office application
was opened, no add-in was sideloaded, no certificate or machine trust was
changed, and no live provider or real credential was used. Phase 8 remains
deferred. At this evidence checkpoint both corrective branch runs are green,
but no merge, release, deployment, package publication, or pull request has
been performed.
