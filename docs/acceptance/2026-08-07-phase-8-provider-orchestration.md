# Phase 8 shared provider orchestration

- Evidence date (Asia/Bangkok): `2026-08-07`
- Clean base commit: `a9fbcd3e84fa8834bf323a025b9d45ca89b6127a`
- Reviewed code candidate: `593b9d1e55ff0d1a20ef3117f29a5b7c0a5af7ca`
- Branch CI head: `593b9d1e55ff0d1a20ef3117f29a5b7c0a5af7ca`
- Candidate branch: `codex/phase-8-provider-orchestration`
- Product version: `2.5.0` (unchanged)
- Status: **source candidate branch CI green; integration pending**

This record covers one Phase 8 unit: shared orchestration of protected provider
requests across the direct CLI/core path, HTTP and hosted roundtrip, the
provisional worker roundtrip, and Tokenmind. It does not cover PDF source-to-box
mapping, the native broker, a release, deployment, real Office hosts, or live
provider/platform acceptance.

All automated evidence must use synthetic values. This record and its test
artifacts must contain no request PII, mapping, credential, provider body,
restored response, or unsafe exception graph.

## Caller-visible outcome

Every protected adapter delegates provider attempts to one shared
orchestration layer. The selected provider receives the same immutable masked
text on every attempt, and a fresh outbound-policy check runs immediately
before each actual provider invocation. The shared policy owns retries:

| Failure | Retry |
|---|---|
| timeout | yes |
| network | yes |
| HTTP 429 | yes |
| HTTP 5xx | yes |
| other HTTP 4xx | no |
| malformed or non-text response | no |
| pre-attempt validation or outbound-policy failure | no |
| response validation/tail failure | no |
| restore failure | no |

There are at most three provider invocations. Each invocation receives its own
60-second timeout. Delays are fixed at one second before attempt two and two
seconds before attempt three. Provider response headers cannot change this
schedule. No provider may retry internally, and no fallback provider is
selected.

Tokenmind's `complete()` performs exactly one HTTP request per invocation. It
retains its request shape and protocol validation but no longer owns a total
deadline, retry loop, retry sleep, or `Retry-After` behavior.

## Boundary invariants

- HTTP contract v2 keeps its exact success and fixed-error projections.
- Worker envelope v1 keeps its exact success and fixed-error projections.
- CLI snapshot and rollback behavior remains stateful and transactional.
- HTTP/hosted and worker roundtrip remain stateless and publish no mapping.
- Hosted provider and route allowlists do not expand.
- Provider construction, call, response validation, restore, and tail failures
  expose only fixed safe metadata after their original error graphs are
  discarded.
- Raw PII, mappings, credentials, provider bodies, restored responses, and
  unsafe exception graphs do not cross log, error, HTTP, or worker boundaries.

## Tests-first contract

Before production code changes, the focused contract tests must fail against
the clean base for these missing behaviors:

1. the worker uses the same three-attempt, 60-second, fixed-delay policy as CLI
   and HTTP;
2. Tokenmind makes one HTTP request for one `complete()` invocation, including
   a retryable response carrying `Retry-After`;
3. the outbound policy is re-evaluated immediately before every actual retry
   and can block the next request;
4. timeout, network, 429, and 5xx are the only retryable classes;
5. malformed/non-text results, other 4xx responses, validation, response-tail,
   restore, and sleep failures are not retried; and
6. no internal plus outer stacked retry path remains.

The final focused matrix must also pin immutable masked input, exact attempt
count/timeouts/delays, CLI rollback after exhaustion or a later outbound-policy
failure, fixed HTTP-v2 and worker-v1 errors, exception-graph disposal, no
fallback, and unchanged hosted allowlists.

## Evidence ledger

| Gate | Result |
|---|---|
| Tests-first collection | EXPECTED FAIL — 13 failed and 172 passed against unchanged production code; failures covered Tokenmind internal retries, worker single-attempt behavior, retry-capability bypass, and an attempt count above three |
| Focused provider/core/HTTP/worker/hosted tests | PASS — 186 provider-path tests and 383 broader contract/path tests passed; the existing Starlette/httpx warning remained |
| Full Python suite | PASS — 2,314 passed, 5 skipped, 1 existing warning in 233.16 seconds |
| Root JavaScript tests | PASS — 123 passed across 16 files; syntax checks passed |
| Desktop Rust tests | PASS — 31 passed |
| Office manifest/type/unit/build gates | PASS — local and upstream manifest validation, package-manifest validation, TypeScript, 129 tests across 12 files, and the 13-module build passed |
| Ruff lint and format | PASS — lint passed and all 219 files were formatted |
| Type and security checks used by the repository | PASS with recorded pre-existing toolchain debt — Office TypeScript and the privacy/security regressions passed; read-only npm audits found only unchanged development-tool advisories described below |
| Version and release-readiness checks | PASS — synchronized `2.5.0`; both scripts passed; 39 version/workflow/release tests passed |
| Performance gate | PASS against the exact clean base — every paired delta is inside the 20% time and 15% memory budgets; the formal stale-anchor command remains red as recorded below |
| `git diff --check` and final privacy/correctness review | PASS — no duplicated provider loop, fallback, wire drift, mapping publication, unsafe boundary, allowlist expansion, unrelated change, or version drift found |
| Exact-head branch CI | PASS — [11/11 jobs](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31177831416) on the reviewed code candidate |
| Post-integration main CI and commit alignment | Pending |

The principal commands were:

```powershell
$env:PYTHONUTF8='1'
.\.venv\Scripts\python.exe -m pytest tests\test_provider_orchestration.py tests\test_tokenmind_provider.py tests\test_step5_ai_client.py tests\test_api_demo.py tests\test_worker_handler.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_step9_pipeline.py tests\test_stateless_leak_regression.py tests\test_leak_guard.py tests\test_http_v2_contract.py tests\test_hosted_readiness.py tests\test_provider_registry.py tests\test_restore_boundary.py tests\test_worker_acceptance_runner.py tests\test_worker_runner.py tests\test_platform_api_contract.py tests\test_foreign_tokens.py tests\test_obfuscated_residuals.py -q
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe scripts\measure_perf.py
.\.venv\Scripts\python.exe scripts\check_version.py
.\.venv\Scripts\python.exe scripts\check_release_readiness.py
npm run test:js
cargo test --manifest-path desktop\src-tauri\Cargo.toml
npm test --prefix office-addin
npm run build --prefix office-addin
git diff --check
```

The five skips are optional OpenCV OCR cases because `cv2` is not installed.
The warning is the existing Starlette/httpx TestClient deprecation warning.
Branch CI also passed its headless packaged-backend smoke, but that smoke does
not invoke a provider and cannot certify packaged orchestration. No optional
live provider, real host, installed application, or deployment gate ran.

## Performance

The required formal command ran and remained red against old absolute anchors:

| Operation | Candidate | Committed baseline | Formal result |
|---|---:|---:|---|
| Detect | 6.82 ms | 5.73 ms | within 20% |
| Sanitize | 21.48 ms | 10.08 ms | +113%, over the stale anchor |
| Restore | 0.33 ms | 0.28 ms | within 20% |
| PDF redact | 82.20 ms | 67.67 ms | +21%, over the stale anchor |
| Resident memory | 151.8 MiB | 151.4 MiB | within 15% |

The changed provider orchestration is outside the measured detect, sanitize,
restore, and PDF execution paths. Three alternating 20-iteration runs compared
the candidate worktree with exact clean base `a9fbcd3` in the same environment:

| Operation | Clean base median | Candidate median | Candidate delta | Budget |
|---|---:|---:|---:|---:|
| Detect | 7.45 ms | 6.98 ms | -6.3% | within 20% |
| Sanitize | 20.15 ms | 17.72 ms | -12.1% | within 20% |
| Restore | 0.28 ms | 0.26 ms | -7.1% | within 20% |
| PDF redact | 79.94 ms | 78.83 ms | -1.4% | within 20% |
| Resident memory | 154.4 MiB | 155.3 MiB | +0.6% | within 15% |

The branch itself is inside the repository performance budgets. The committed
baseline was not moved.

## Security and privacy review

The final source search found only three protected orchestration entry points:
CLI/core, HTTP/hosted, and worker. Their one shared attempt function is the only
production caller of the one-attempt provider primitive, and that primitive is
the only production caller of `provider.complete()`. Tokenmind contains no
retry loop. No provider registry or hosted allowlist changed.

Synthetic retained-error regressions pin disposal of credentials, request and
response bodies, mappings, providers, tracebacks, causes, contexts, and custom
attributes at the CLI, HTTP, and worker boundaries. Retry regressions pin the
same masked text and selected provider, exact check/call/delay order, safe
fixed projections, transactional rollback, and stateless mapping containment.

Read-only `npm audit` runs surfaced one moderate advisory in the root
development tree and 19 advisories in the Office development-tool tree (12
high, 7 moderate). The Office runtime dependency set is empty. This branch
changes no package manifest, lockfile, JavaScript, or Office source, and the
repository's configured Office CI installs with `--no-audit`; these are
pre-existing build-tool findings, not evidence that the protected-provider
change is unsafe. They are recorded without claiming that the dependency trees
are vulnerability-free.

Local mocks and source tests can close only current-source automated behavior.
They cannot certify live Pathumma/Tokenmind, an installed application, a real
browser or Office host, the selected sibling deployment, official platform
logs/resources, or any release artifact.
