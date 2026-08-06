# F-06 eager session lifecycle and authenticated disposal

- Evidence date (Asia/Bangkok): `2026-08-06`
- Clean base commit: `35b451768db420bb6c6c6e20120f6105bff5336d`
- Candidate branch: `codex/phase-7-session-lifecycle`
- Original Phase 7 commit: `f968833fd563b530bb68a5104ea9969ad537dd94`
- Corrective commit: this record's commit, directly on top of `f968833`
  (`fix(security): close Phase 7 lifecycle review blockers`)
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
| Focused lifecycle/core/authentication/API matrix | PASS — 307 passed, 1 warning |
| Hosted/API/shutdown/cleanup matrix | PASS — 521 passed, 1 warning |
| Full Python suite | PASS — 2,250 passed, 5 skipped, 1 warning in 139.26 seconds |
| Documentation coverage | PASS — 6 passed |
| Root/desktop/extension JavaScript | PASS — 123 passed |
| Desktop Rust tests | PASS — 31 passed |
| `python -m ruff check .` | PASS |
| `python -m ruff format --check .` | PASS — 217 files |
| Version synchronization | PASS — `2.5.0` |
| Release-readiness check | PASS — 39 tests plus both scripts |
| Performance gate | RED — sanitize +58%; established privacy trade, baseline unchanged |
| `git diff --check` | PASS |
| Corrective read-only security review | PASS — two follow-up gaps fixed; final focused checks found no blockers |
| Independent merge re-review | PENDING — do not treat Phase 7 as merge-approved |
| Corrective branch CI | Pending push; original `f968833` branch run passed 11/11 before rejection |

The warning is the existing Starlette/httpx TestClient deprecation warning.
The five skips are optional OpenCV OCR cases because `cv2` is not installed.
Corrective branch CI has not run because this commit has not yet been pushed.

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

The corrective candidate's formal command remained red against the older
committed sanitize anchor:

| Operation | Candidate | Committed baseline | Delta | Formal result |
|---|---:|---:|---:|---|
| Detect | 5.95 ms | 5.73 ms | +4% | within 20% |
| Sanitize | 15.94 ms | 10.08 ms | +58% | over 20% |
| Restore | 0.25 ms | 0.28 ms | -11% | within 20% |
| PDF redact | 76.15 ms | 67.67 ms | +13% | within 20% |
| Resident memory | 151.9 MiB | 151.4 MiB | less than +1% | within 15% |

Neither original Phase 7 nor this correction alters the sanitize detection,
replacement, token shape, or residual-policy algorithm, and the performance
harness constructs `SessionService` without a timer factory. The pre-existing
longer-token/full-residual-scan trade remains the established explanation for
the red sanitize anchor and was owner-accepted on 2026-08-06. The formal gate
is still red and the baseline was not changed.

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
read-only review is complete, but the fresh independent merge re-review remains
pending and is recorded only after it occurs.

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
deferred. At this corrective checkpoint, no push, merge, release, deployment,
package publication, or pull request has been performed.
