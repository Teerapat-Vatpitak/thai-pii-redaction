# F-06 eager session lifecycle and authenticated disposal

- Evidence date (Asia/Bangkok): `2026-08-06`
- Clean base commit: `35b451768db420bb6c6c6e20120f6105bff5336d`
- Candidate branch: `codex/phase-7-session-lifecycle`
- Product version: `2.5.0` (unchanged)

This is current-source automated evidence for Phase 7 / F-06. It covers the
backend session lifetime, internal authenticated disposal, deterministic
cleanup, and their races. It is not packaged/installed, browser, Office-host,
live-provider, deployment, release, or official-platform evidence.

All runtime checks used synthetic values. This record contains no request text,
entity value, mapping, credential, provider body, restored answer, or
machine-specific artifact.

## Behavior established

`SessionService` owns one timer for the earliest active deadline. A session is
available immediately before its boundary and unavailable at `age >= TTL`.
The callback expires due sessions without a later request and reschedules for
the next session. Timer generations prevent canceled or stale callbacks from
reviving or re-cleaning state. A request that acquires the lifecycle lock
before its deadline completes atomically and receives a fresh TTL only after
successful completion.

The existing internal `DELETE /api/session/{session_id}` route requires exactly
one short-lived HMAC authorization derived from the configured control secret.
The signed message binds the contract context, target session, expiry, and a
random nonce. Missing, malformed, invalid, expired, duplicate-header,
cross-session, and replayed authority fails closed with a bounded error. Raw
boot-token use and an unset control secret do not authorize disposal. A fresh
authorization makes repeated disposal idempotent; the same authorization is
single-use.

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
| Phase 7 deterministic lifecycle module | PASS — 17 passed |
| Focused lifecycle/core/authentication matrix | PASS — 121 passed, 1 warning |
| Full Python suite | PASS — 2,220 passed, 5 skipped, 1 warning in 143.99 seconds |
| Documentation coverage | PASS — 6 passed |
| `python -m ruff check .` | PASS |
| `python -m ruff format --check .` | PASS |
| Version synchronization | PASS — `2.5.0` |
| Release-readiness check | PASS |
| `git diff --check` | PASS |
| Independent security review | PASS — cleanup failure-path gap fixed; no remaining Phase 7 blocker |

The warning is the existing Starlette/httpx TestClient deprecation warning.
The five skips are optional OpenCV OCR cases because `cv2` is not installed.
No CI was run because this branch was not pushed.

The principal commands were:

```powershell
$env:PYTHONUTF8='1'
.\.venv\Scripts\python.exe -m pytest tests\test_session_lifecycle.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_session_lifecycle.py tests\test_session_service.py tests\test_api_token.py -q
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe scripts\measure_perf.py
.\.venv\Scripts\python.exe scripts\check_version.py
.\.venv\Scripts\python.exe scripts\check_release_readiness.py
git diff --check
```

## Performance

The formal command remained red against the older committed sanitize anchor:

| Operation | Candidate | Committed baseline | Delta | Formal result |
|---|---:|---:|---:|---|
| Detect | 5.74 ms | 5.73 ms | approximately 0% | within 20% |
| Sanitize | 15.01 ms | 10.08 ms | +49% | over 20% |
| Restore | 0.24 ms | 0.28 ms | -14% | within 20% |
| PDF redact | 70.92 ms | 67.67 ms | +5% | within 20% |
| Resident memory | 153.3 MiB | 151.4 MiB | +1% | within 15% |

Phase 7 does not alter the sanitize detection, replacement, or residual-policy
algorithm, and the performance harness constructs `SessionService` without a
timer factory. The pre-existing longer-token/full-residual-scan trade remains
the established explanation for the red sanitize anchor and was owner-accepted
on 2026-08-06. This run is lower than the previously recorded exact-current
sanitize result, but the formal gate is still red and the baseline was not
changed.

## Review findings and fixes

The first independent review found that timer rescheduling could fail after a
session was detached, causing the fail-closed service transition to clean the
remaining registry without cleaning that detached object. Cleanup now runs in
`finally` for eager expiry, deterministic sweeps, raw drops, and authenticated
disposal. Sanitize publication also clears both an evicted session and the
staged replacement if replacement-timer startup fails.

The review also requested deterministic active-request races. Tests now prove
that authenticated disposal waits for active restore, shutdown waits for
active sanitize, stale expiry callbacks cannot remove a successfully refreshed
session, concurrent repeated disposal cleans once, and expiry/disposal/shutdown
races remain idempotent. A final read-only review reported no remaining Phase 7
security blocker.

The final primary diff audit found that a timer-start fail-closed transition
could retain bounded replay fingerprints and hashed tombstones after clearing
the session registry. That path now clears both metadata caches immediately;
the same reviewer found no blocker in the final change.

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
changed, and no live provider or real credential was used. No CI, push, merge,
release, deployment, package publication, or pull request was performed for
this record.
