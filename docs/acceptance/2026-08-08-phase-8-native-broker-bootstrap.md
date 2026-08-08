# Phase 8 native-broker authenticated bootstrap and health

- Evidence date (Asia/Bangkok): `2026-08-08`
- Clean base commit: `74bbfaee298b2aba777b0a7037579f5dad0bfd16`
- Candidate branch: `codex/phase-8-native-broker-bootstrap`
- Product version: `2.5.0` (unchanged)
- Status: **Slice 2 implementation checkpoint locally and branch-CI green;
  independently reviewed**

This record covers Slice 2 only: authenticated native IPC admission, the
Windows named-pipe and macOS/Linux filesystem-UDS endpoints, atomic
single-instance bootstrap, broker-owned private-backend startup, protocol-v1
hello and health, maintenance-only drain/stop, and deterministic lifecycle
failure handling.

It does not implement a broker data plane, session ownership or disposal,
Chrome Native Messaging, Extension integration, Tauri commands, Desktop
migration, Office integration, provider calls, document operations, or release
packaging. Those remain the later accepted slices in
[`2026-08-07-native-broker.md`](../decisions/2026-08-07-native-broker.md).

All tests and evidence use synthetic non-sensitive values. No acceptance
artifact may contain request text, restored text, a mapping, a backend
credential, a private endpoint value, a child command secret, an exception
graph, or a machine-specific account/path value.

## Security invariants

1. A protocol role claim grants no authority. Admission records and checks the
   transport-authenticated OS peer/context, package-consistency evidence,
   claimed role, and admitted role as separate facts. Only one exact consistent
   combination creates negotiated protocol state.
2. OS peer identity establishes OS-user, logon-session, and process context
   only. It is not publisher attestation or cryptographic application
   authentication.
3. Canonical path, build identifier, and digest checks establish package
   consistency only. They do not protect against arbitrary malicious code
   already running as the same OS user, OS-account compromise, or replacement
   of unsigned installed binaries.
4. Windows uses only a named pipe with an explicit current-logon-user DACL,
   remote-client rejection, kernel-reported client PID/token/session checks,
   and a held process handle during package inspection. No permissive default
   pipe ACL or TCP client fallback exists.
5. macOS/Linux use only a filesystem Unix-domain stream socket in a verified
   user-private directory. The directory is `0700`, the socket is `0600`, peer
   credentials are mandatory, stale and non-socket paths fail closed, and
   symlink/path substitution is rejected. Linux abstract sockets are forbidden.
6. Single-instance ownership uses an OS-backed mutex/lock held for the complete
   broker lifetime. Endpoint existence is never the sole ownership decision.
7. The broker binds the random loopback backend listener before child startup,
   retains a guard handle, and transfers only a duplicate through the inherited
   bootstrap channel. No check-then-bind or check-then-connect credential
   delivery is allowed.
8. Backend data and control credentials are independent per boot, remain in
   broker/backend memory, and pass only through the inherited bootstrap
   channel. They never enter command arguments, public environment state,
   endpoint publication, stdout/stderr, logs, errors, or storefront-visible
   protocol messages.
9. The backend random address, listener, and credentials never cross native
   IPC. The broker exposes only protocol-v1 health and maintenance control in
   this slice and never forwards an HTTP-v2 data operation.
10. Broker death terminates the backend. Backend death invalidates broker
    health and causes deterministic teardown. Graceful shutdown is bounded;
    uncertain or timed-out shutdown is followed by forced process-tree teardown.
11. Connections, frames, negotiation time, and active handlers are bounded.
    Partial, malformed, oversized, disconnected, incompatible, or
    role-inconsistent peers fail with protocol-v1 fixed value-free errors.
12. Storefront roles cannot request global lifecycle control. Only a separately
    admitted `maintenance` peer may request `maintenance_drain_stop`, and that
    role cannot invoke data or session operations.

## Explicit non-goals

- No `sanitize`, `detect`, `analyze`, `guard`, `roundtrip`, `reidentify`, PDF,
  audit-data, scope, session, provider, retry, or remote-TNER execution.
- No broker session handles, mappings, data-plane forwarding, automatic data
  replay, or uncertain data-operation recovery.
- No Chrome native host or adapter, Extension permission/code change, Tauri
  command or Desktop code change, or Office code/architecture change.
- No localhost TCP fallback for a native client and no direct storefront access
  to the private backend.
- No protocol-v1 semantic, operation, role, limit, deadline, or error change.
- No installer/update migration beyond the minimum source/CI scaffolding needed
  to start and test the private backend mode.
- No product version bump, release, deployment, or installed-artifact
  acceptance claim.

## Tests-first ledger

The initial test-only tree failed before the Slice 2 modules existed:

- Python collection stopped with `ModuleNotFoundError` for the deliberately
  absent `app.private_backend_bootstrap` module.
- Rust compilation stopped with unresolved imports for the deliberately absent
  `admission`, `bootstrap`, `control`, `ownership`, and `transport` modules.

Both failures occurred before a Slice 2 assertion could pass. The acceptance
record and adversarial tests therefore preceded production implementation.

| Required adversarial case | Evidence |
|---|---|
| Valid authenticated Desktop admission | Central admission unit + live platform transport hello/health |
| Valid Extension role representation | Central admission and protocol hello/health without an adapter |
| Valid Maintenance admission | Central admission plus maintenance-only drain/stop |
| Claimed-role mismatch / unknown role | Fixed `broker_unauthorized` before negotiated authority |
| Unauthorized OS user | Injected peer-context unit on every host; live ACL/mode assertion on the current host |
| Insecure endpoint permissions | Windows DACL inspection; Unix directory/socket mode rejection |
| Stale endpoint | Lock-owning stale socket cleanup; symlink/non-socket rejection |
| Startup race / already-running broker | Live concurrent `connect_or_start` clients launch exactly one owner, converge on that broker, and attach to an already-valid endpoint |
| Incompatible broker / malformed hello | Protocol-v1 fixed errors and connection close |
| Partial, truncated, oversized frames | Incremental transport tests with bounded buffers and disconnect handling |
| Broker crash | Ownership release/stale cleanup and backend termination evidence |
| Backend startup/health failure | No endpoint readiness; child/listener/credential teardown |
| Bootstrap/publication uncertainty | Replacement backend cannot inherit the prior listener or credentials |
| Shutdown timeout / forced teardown | Bounded graceful attempt followed by proven process-tree death |
| Endpoint cleanup | Graceful removal and safe next start |
| Secret/error/log leakage | Synthetic sentinel scans of Rust/Python errors and captured output |
| Descriptor/handle inheritance | Only the bootstrap channel and transferred listener reach the child |
| Bounded connection/resource behavior | A live authenticated control client receives canonical `broker_busy` at the fixed active-connection ceiling without stopping the broker |

## Evidence ledger

| Gate | Result |
|---|---|
| Tests-first Python collection | EXPECTED FAIL — missing `app.private_backend_bootstrap` during collection |
| Tests-first Rust compile | EXPECTED FAIL — unresolved imports for all five declared Slice 2 modules |
| Focused Python Slice 2 tests | PASS — 8 private-bootstrap/prebound-backend tests; 154 when run with the 146 Slice 1 protocol regressions, plus two expected Unix-only skips on Windows |
| Focused Rust Slice 2 tests | PASS — Windows 33 runtime/resource tests; real WSL2 Linux 38, including Unix endpoint substitution, peer-credential, process-inheritance, prebind, and lifecycle cases |
| Protocol/conformance regression | PASS — 146 Python protocol tests, 20 Rust conformance groups, and two allocation-before-copy decoder regressions |
| Windows named-pipe construction/security | PASS locally — explicit protected current-logon-SID DACL readback, remote rejection, kernel PID/token/path inspection, held process handles, exact-one-owner race, partial frames, disconnects, cleanup, and restart |
| macOS filesystem-UDS construction/security | PASS in exact-head CI — 37 Slice 2 runtime/resource tests exercise audit-token, `getpeereid`, `libproc`, UDS mode/path hardening, retained terminal responses, process groups, the bootstrap lifeline, lifecycle, and cleanup on the macOS runner |
| Linux filesystem-UDS construction/security | PASS on a real WSL2 Linux 6.18 kernel — `0700`/`0600`, held lock, stale/symlink substitution controls, `SO_PEERCRED`, stable `pidfd`, bounded connect, parent death, descriptor sealing, cleanup, and restart |
| Full Python suite | PASS — 2,486 passed, five expected optional OpenCV skips, two expected Unix-only backend-bootstrap skips on Windows, and the existing Starlette/httpx deprecation warning |
| Root JavaScript tests | PASS — 123 |
| Desktop Rust tests | PASS — 31; no Desktop source changed |
| Office gates | PASS — unified/local manifests, TypeScript, 129 tests, and production build; no Office source changed |
| Ruff, rustfmt, and warning-as-error Clippy | PASS |
| Type/static/security checks | PASS — Office TypeScript, `pip check`, workflow YAML/pin checks, and zero production npm advisories; read-only audits report two root and 20 Office development-tree advisories outside shipped runtime |
| Version/release/documentation checks | PASS — synchronized `2.5.0`, release readiness, 58 focused lock/workflow/version/docs/release-asset tests |
| Performance/resource evidence | PASS with stale-anchor explanation — the formal harness remains red only against its old sanitize anchor; three alternating candidate/base medians are detect 5.72/5.83 ms, sanitize 15.53/15.89 ms, restore 0.24/0.25 ms, PDF 73.48/71.69 ms (+2.5%), and RSS 151.8/151.9 MiB, within branch budgets. Four repeated backend cycles pass on Windows and Linux without accumulating beyond the one-handle/FD allowance. |
| `git diff --check` and final privacy/scope audit | PASS locally — no protocol/`VERSION` drift, storefront adapter, data operation, HTTP fallback, secret-bearing publication, or payload-derived diagnostic found |
| Independent security review | PASS — the complete security-sensitive diff was rechecked independently after fixes; no unresolved finding remains. Windows ACL/admission, Unix ownership/peer credentials/stale paths, startup races, backend/process ownership, inherited resources, role binding, shutdown bounds, secret handling, and absence of storefront fallback/data plane all passed review. |
| Implementation branch CI | PASS — all 14 jobs, including Windows, Ubuntu, and macOS native-broker runtime plus Windows packaged-backend smoke, passed at [`b1da3bee96af060681ba7ad06765daa717f2d706`](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31251561221) |
| Main integration and post-main CI | Delivery-loop evidence verified separately after this source checkpoint |

## Acceptance boundary

A green Slice 2 establishes authenticated bootstrap/control-plane health only.
It does not establish data-plane correctness, session ownership/disposal,
storefront migration, Chrome/Tauri behavior, Office support, or installed
package acceptance. Those claims remain open even when every gate in this
record passes.
