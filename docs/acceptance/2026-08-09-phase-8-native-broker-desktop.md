# Phase 8 native-broker Desktop migration

- Initial evidence date (Asia/Bangkok): `2026-08-09`
- Reconciled through: `2026-08-10`
- Exact clean base: `33989cac356330ff4efdb080c470b8bb63561c6a`
- Candidate branch: `codex/phase-8-native-broker-desktop`
- Last fully gated executable/implementation checkpoint:
  `492dad34361b09d7ffa58fa192a2447de7414418`
- Executable-checkpoint CI:
  [run 31349781519](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31349781519)
  — **PASS, 14/14 jobs including installed Windows NSIS**
- Executable-checkpoint cross-platform package smoke:
  [run 31349781518](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31349781518)
  — **PASS, 2/2 jobs: relocated macOS, direct extracted DEB, and exact outer
  AppImage `--appimage-extract-and-run` plus verified warm `AppRun`**
- Immediate predecessor `8194c23e0a6dfc1530257424664235740b5337c2`:
  [CI run 31348501253](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31348501253)
  failed 10/14 because four Rust jobs exposed only non-portable path spelling in
  the new canonical-root test; its installed-Windows NSIS job passed. Separate
  [cross-platform run 31348501256](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31348501256)
  passed 2/2, including relocated macOS, extracted DEB, and finalized outer
  AppImage `--appimage-extract-and-run` plus verified warm `AppRun`
- Predecessor `73dcca49766bd8a92261e13c8be4ec6ca107bb25`:
  [CI run 31345691672](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31345691672)
  passed 14/14 including installed Windows NSIS;
  [cross-platform run 31345691667](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31345691667)
  failed after relocated macOS and extracted DEB passed because the AppImage
  harness bypassed the outer runtime/`AppRun` and produced no marker
- Earlier predecessor `3836024c0faa2a3645354d33c26c30f2090ba13e`:
  [CI run 31329794579](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31329794579)
  passed 14/14; its
  [cross-platform run 31329794568](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31329794568)
  failed after relocated macOS passed because Linux AppImage finalization
  rejected appimagetool's defined `.digest_md5` rewrite before package smoke
- Immediate predecessor `6ad3422beeb6d5ee15f4fe9d9bd51b8a5f9eb0ea`:
  [CI run 31328047804](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31328047804)
  passed 14/14 including installed Windows NSIS;
  [cross-platform run 31328047802](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31328047802)
  failed after relocated macOS and extracted DEB passed because AppImage
  component verification failed before AppImage Desktop launch
- Earlier predecessor `8be9523580e5e9789d2b0916d008477a98d37319`:
  [CI run 31327288545](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31327288545)
  passed 14/14 including installed Windows NSIS;
  [cross-platform run 31327288595](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31327288595)
  failed after macOS relocation passed and Linux process inspection failed
  before Desktop launch
- Historical dirty-tree Windows NSIS SHA-256:
  `7277341A62CEF70C8431BE4AEA51E9C0CA916E8C01ABDC8D0267C087869AE681`
- Product version: `2.5.0` (unchanged)
- Scope: **Phase 8 Slice 4 only**
- Current owner-decision correction base:
  `fcdbeed25f9e6d81c66102c06923390c45611f98`
- Status: **the owner-selected credential-free installed configuration is
  implemented in the current working candidate, closing the identified P1 in
  source. The cited exact CI and package evidence remains evidence for
  `492dad3`, not the correction. Slice 4 integration awaits an exact committed
  candidate, complete gates/package smoke, and independent review; Slices 5--6
  must build only from the integrated result.**

This record covers migration of the existing Tauri Desktop UI and Rust hotkey
path onto the authenticated protocol-v1 native broker established by Slices
1--3. It does not change broker protocol v1, add a role or operation, migrate
the browser Extension, implement Chrome Native Messaging, change Office,
certify updater/upgrade/uninstall behavior, deploy or release anything, or
change product `VERSION`. It does add the native-component manifest to ordinary
Tauri bundle layouts. Installed Windows NSIS, relocated macOS app, extracted
Linux DEB, and finalized outer-AppImage plus verified warm-`AppRun` smoke are
different evidence classes and are not treated as interchangeable installation
evidence. The AppImage path is not normal FUSE/double-click evidence.

All tests and artifacts use synthetic PII. Machine-readable smoke evidence
contains no request/response values, mappings, Python session identifiers,
provider bodies, credentials, private backend endpoints, native endpoint names,
or raw Rust/Python exception text.

## Evidence classes

The same feature-gated smoke drives production package JavaScript through
typed Tauri commands, the native broker, the frozen backend, and shared core.
Where it starts those bytes still matters:

| Evidence class | What it proves | Current record |
|---|---|---|
| source/native tests | contracts, policy, caller path, and deterministic runtime faults in the test environment | last fully gated executable checkpoint `492dad3` passed the recorded local and 14-job CI matrix; current correction adds focused inherited-environment, warm-broker, unsupported-selector, startup, and provider-admission regressions, whose working-candidate evidence remains provisional pending an exact commit and full gates |
| installed Windows NSIS | the NSIS installer placed a runnable exact package in an isolated Windows root | `492dad3` passed two launches with zero broker/backend process delta; exact installer SHA-256 and metrics are recorded below |
| relocated macOS app | a copied `.app` layout still ran from a new path on a native macOS runner | `492dad3` passed two relocated-layout launches with zero broker/backend process delta; this is not installer, notarization, or `/Applications` evidence |
| extracted Linux DEB | the exact DEB layout ran directly after extraction on a native Linux runner | `492dad3` passed both direct-layout repetitions with zero broker/backend process delta; this is not package-manager installation evidence |
| finalized outer AppImage plus verified warm `AppRun` | the exact outer file crossed `--appimage-extract-and-run`, then its retained live root was re-attested before the warm `AppRun` launch | `492dad3` passed with zero broker/backend process delta and `execution_mode=outer_appimage_extract_and_run_then_verified_apprun`; the independent extracted layout attested bytes only, and this is not normal FUSE/double-click or installation evidence |
| live provider/TNER | current shared provider and explicit-TNER behavior with real credentials/quota | not exercised; package smoke pins an offline detector and fake provider |
| manual visual/updater/lifecycle | human visual use, updater check/install, relocation through the supported installer path, upgrade/drain, interrupted upgrade, stale cleanup, and uninstall | not exercised; remains Slice 6 |

The predecessor results are retained as historical diagnostics. The `8be9523`
macOS job is relocation-only evidence. Its exact archive hash and metrics are
recorded below, but the failed overall cross-platform workflow does not
establish a Linux result or a green cross-platform gate. The `6ad3422` results
and `3836024` results are retained as predecessor diagnostics. Checkpoint
`73dcca4` passed exact CI but retains a diagnostic cross-platform failure on the
unfaithful AppImage entrypoint. Checkpoint `8194c23` has a red overall CI only
because of its non-portable canonical-path test, while its independent package
run passed 2/2. Last fully gated checkpoint `492dad3` repairs the test construction; its
exact CI passed 14/14 and its exact package workflow passed 2/2.

## Exact migration boundary

Before Slice 4:

```text
Desktop webview --fetch--> http://127.0.0.1:8000 HTTP-v2 --> Python core
Desktop hotkey  --reqwest-> http://127.0.0.1:8000 HTTP-v2 --> Python core
Tauri sidecar owner ------> fixed port / Python process / boot token lifecycle
```

The webview constructed HTTP requests; the Rust hotkey duplicated HTTP-v2
handling; and Tauri owned, discovered, started, authenticated to,
health-checked, retried, and stopped the Python backend.

After Slice 4:

```text
Desktop webview -> typed allowlisted Tauri command -+
                                                   +-> Rust Desktop client
Desktop hotkey ------------------------------------+   (role: desktop;
                                                       UI/hotkey scope)
                                                       -> authenticated native IPC
                                                       -> shared native broker
                                                       -> private authenticated HTTP-v2 backend
                                                       -> shared Python core
```

The webview migration boundary ends at typed Tauri commands. The webview can
select only fixed Desktop operations and typed fields; it cannot send an
arbitrary broker message, operation, JSON object, URL, HTTP request, filesystem
path, or shell command. The Rust client reuses the machine-readable v1 policy
for hello, role admission, request/response validation, deadlines, framing, fixed errors,
message limits, and no-replay behavior. Slices 2--3 remain authoritative for
broker ownership, endpoint recovery, private backend generations,
connection/scope/session ownership, uncertain completion, and disposal.

The UI may retain only an opaque broker-issued session handle. The webview
never receives a Python session ID, mapping, provider/TNER credential, backend
data or control credential, boot key, backend URL/port, or private native
endpoint detail. The native process boundary is also deterministic: installed
Desktop accepts only the local `thainer`/`fake` profile, and both child seams
construct a name-allowlisted runtime environment without querying provider/TNER
credential values before pinning that profile.

Production Desktop contains no direct backend/data-plane HTTP client. The
existing updater is a separate Rust-side client restricted to its configured
HTTPS release host.

## Tauri command surface

The complete webview broker surface is:

| Tauri command | Protocol-v1 operation |
|---|---|
| `desktop_health` | `broker_health` |
| `desktop_analyze` | `analyze` |
| `desktop_sanitize` | `sanitize` |
| `desktop_reidentify` | `reidentify` |
| `desktop_copy_masked` | `reidentify`, then native validation and clipboard publication |
| `desktop_analyze_report` | `analyze_report` |
| `desktop_redact_pdf` | `redact_pdf` |
| `desktop_audit_log` | `audit_log` |
| `desktop_session_dispose` | `session_dispose` |
| `desktop_scope_reset` | `scope_close` |
| `desktop_scope_rotate` | local renderer-generation rotation plus out-of-band `scope_close` |

`scope_open` is internal to the Rust manager. Existing `quit_app`,
`update_check`, and `update_install` remain non-broker product commands. There
is no generic raw-send, arbitrary-operation/JSON/URL/HTTP, shell, filesystem,
clipboard-read, global-shortcut, or native-networking grant in the webview
capability. Global hotkeys call the typed Rust client directly rather than
crossing the Tauri webview surface.

The typed native client still supports the complete accepted Desktop role.
`detect`, `guard`, and `roundtrip` are exercised in native tests but are not
registered in the webview handler and are not exercised by the installed
package smoke because no current Desktop screen uses them. This prevents
rendered-content compromise from spending provider authority through an
unused bridge.

The exact Desktop role remains:

```text
analyze, analyze_report, audit_log, broker_health, detect, guard,
redact_pdf, reidentify, roundtrip, sanitize, scope_close, scope_open,
session_dispose
```

No `desktop-v2`, admin, debug, backend, or unrestricted role was added.

## Lifecycle and failure behavior

- The first PII-free health request connects to an existing broker or invokes
  the Slice 2 on-demand single-owner start path. No Desktop Python child exists.
- Each Tauri window label owns one `desktop_ui` scope. Hotkeys own one separate
  `desktop_hotkey` scope. A handle cannot cross scope, connection, role,
  process, or backend generation.
- No data request is automatically replayed. A later explicit user action
  creates a new request; it never resends the earlier request ID or payload.
- Transport/integrity failures clear the connection plus local scope/session
  authority. Uncertain session mutations clear the UI/hotkey handle and show
  fixed restart-workflow guidance.
- Dispose, reset/new-document, window close, app quit, and hotkey publication
  failure remove local authority before native cleanup. Any unconfirmed
  session/scope cleanup disconnects, making broker connection teardown the
  fail-closed fallback. No unsuccessful disposal is shown as success.
- Desktop quit closes only its own UI/hotkey scopes. It does not invoke
  maintenance drain/stop or destroy another admitted Desktop connection's
  sessions. No Extension lifecycle or integration claim is made in Slice 4.
- The existing single-main-window and Tauri single-instance behavior is
  preserved. Independent admitted Desktop processes still converge on one
  broker and never share scopes.
- Rust and JavaScript both validate exact operation-specific result shapes and
  safety state before UI, clipboard, or file output. Native transport success
  alone is not publication authority.

## Provider, PDF, and TNER boundaries

The typed native roundtrip remains Desktop → broker → private HTTP v2 → shared
provider orchestration for internal conformance only. Rust contains no provider
client, retry, fallback, or raw provider access, and roundtrip is not exposed to
the current webview. The installed data plane admits only `fake` for that
conformance path; `pathumma`, `tokenmind`, `claude`, `ollama`, or any other
provider fails as `provider_configuration` before backend submission. The
installed package smoke executes no provider operation.

PDF bytes cross the bounded broker data plane as protocol-v1 base64. The
existing Python PDF path remains authoritative for extraction, exact source
intervals, file limits, flattening, OCR policy, redaction, and containment.
Rust performs no PDF parsing or redaction. The live and packaged Slice 4 flows
use the repository's real synthetic PDF.

Remote TNER remains an explicit capability of the broader core, CLI, HTTP,
hosted, and worker boundaries. It is not supported by installed Desktop or its
shared broker. An installed-process request for `AIGUARD_NER_ENGINE=tner` (or
any engine other than `thainer`) fails as `ner_unavailable` before broker
connection or launch, with no silent local fallback and no credential value in
the error.

### Installed credential/configuration decision

The owner selected the credential-free option for the current installed
Desktop product:

- local `thainer` is the only supported detector;
- the managed backend receives `AIGUARD_PROVIDERS=fake` only for internal
  conformance, and the webview has no provider command;
- unsupported explicit detector/provider selectors fail as stable,
  non-secret `ner_unavailable` or `provider_configuration` errors before any
  broker connection/launch or backend use;
- Desktop-to-broker and broker-to-backend child creation queries only a fixed
  allowlist of ordinary runtime-variable names. It never queries or copies AI
  for Thai, Anthropic, Tokenmind, provider/detector selector, Tokenmind transport,
  fine-tuned model, or inherited broker API/control values, then pins
  `thainer`/`fake`; and
- Desktop and broker no longer snapshot remote configuration independently, so
  an attaching process cannot silently reinterpret a warm broker.

No credential store is introduced. Credential-requiring providers and remote
TNER in installed Desktop are deferred to a separate owner-approved ADR that
must cover credential ownership, provisioning, permissions, storage, rotation,
configuration identity/epoch, broker restart/reconfiguration semantics,
upgrade, uninstall, attestation, and cross-platform behavior. Broader
non-Desktop interfaces retain their existing explicit provider/TNER
capabilities.

This closes the identified P1 in source. Focused working-candidate regressions
cover hostile parent selectors, both child environments, warm-broker attach,
broker/backend startup, and pre-backend provider rejection. That evidence is
provisional until the correction is committed and the full exact-head,
package, and independent-review gates pass; Slice 4 integration remains
pending until then.

## Webview security review surface

- capability: exact `main` window with an empty plugin permission set; tray,
  shortcut, clipboard, updater networking, and broker work stay Rust-side;
- CSP: no backend localhost/127.0.0.1 destination; scripts are self-only and
  the former inline theme bootstrap is a static file;
- navigation: exact internal `tauri://localhost` or `tauri.localhost` origins;
- no shell/filesystem/native-network/clipboard-read/global-shortcut grant;
- no arbitrary native command or operation input;
- external update notes and backend-derived display values use `textContent`
  or HTML escaping; report rendering retains its XSS regression;
- frontend errors are selected from the protocol-v1 fixed code set and show no
  endpoint, credential, native path, session ID, or exception string.

Inline style permission is retained from the existing static UI because many
fixed templates use style attributes; script execution remains self-only. It
was not widened for Slice 4.

## Tests-first evidence

This acceptance record was the first Slice 4 file. Before production code was
added, the new targets failed as expected:

- `cargo test --manifest-path native-broker/Cargo.toml --test slice4` did not
  compile because `desktop_client` did not exist;
- `pytest -q tests/test_desktop_native_broker_migration.py` produced seven
  expected failures for the missing allowlist/client and live legacy direct
  HTTP/sidecar/CSP paths;
- `vitest run desktop/tests/api-native-broker.test.js` produced eleven expected
  failures because the frontend still used HTTP and lacked typed invoke,
  disposal, scope reset, and fixed native error projection.

No Slice 4 production module had been added or modified at that checkpoint.

## Required migration matrix

The table maps every requested case to deterministic evidence. `S4 live` is
`native-broker/tests/slice4.rs`; `S3` names unchanged Slice 3 tests; `JS` is
the Desktop Vitest suite; `static` is
`tests/test_desktop_native_broker_migration.py`; and `package` is the
feature-gated production-JavaScript/typed-Tauri smoke launched from the
isolated historical Windows NSIS installation. The same smoke now exists for
relocated macOS, an extracted Linux DEB layout, and the finalized outer
AppImage. On predecessor `6ad3422`, CI passed and macOS plus extracted DEB
passed, but AppImage component verification failed before AppImage launch.
Predecessor `3836024` passed CI and macOS but failed Linux finalization before
package smoke. Predecessor `73dcca4` passed CI, macOS, and DEB but used an
unfaithful inner AppImage entrypoint. Predecessor `8194c23` crossed the exact
outer AppImage with `--appimage-extract-and-run` and then a re-attested warm
`AppRun`; its package workflow passed 2/2, while its main CI failed only the
non-portable path-spelling unit test. Current-checkpoint `492dad3` repairs that
test construction. Its exact CI passed 14/14, and its exact package workflow
passed 2/2 across installed Windows NSIS, relocated macOS, extracted DEB, and
outer-AppImage/warm-`AppRun` execution. These paths are recorded separately and
cannot be promoted to interchangeable installed-package evidence.

| # | Required case | Evidence |
|---:|---|---|
| 1 | Desktop health through broker | S4 live + package |
| 2 | cold broker startup | S4 live single-owner launcher + package cold run |
| 3 | existing broker connection | S4 live existing connection |
| 4 | simultaneous Desktop startup | S4 live barrier/convergence |
| 5 | wrong broker version | S4 authenticated fault broker |
| 6 | invalid Desktop role admission | S4 manifest role mismatch before connect |
| 7 | detect | S4 live; not exposed to or exercised by package webview |
| 8 | analyze | S4 live + package |
| 9 | guard | S4 live |
| 10 | fresh sanitize | S4 live + package |
| 11 | session sanitize continuation | S4 live exact handle continuity + package |
| 12 | reidentify | S4 live + package |
| 13 | session dispose | S4 live + package |
| 14 | scope close | S4 live + package |
| 15 | roundtrip | S4 live only; not exposed to or exercised by package webview |
| 16 | analyze-report | S4 live + package real PDF report result |
| 17 | PDF | S4 live + package real synthetic PDF |
| 18 | request timeout | S4 deterministic post-hello timeout |
| 19 | disconnect before submission | S4 explicit client disconnect |
| 20 | disconnect after submission | S4 fault broker reads once then disconnects |
| 21 | uncertain mutation completion | S4 fixed uncertain mutation + S3 unknown mutation tests |
| 22 | generation teardown | S4 restart/stale generation + S3 generation tests |
| 23 | stale session handle | S4 disposed and post-restart handles |
| 24 | broker restart | S4 real broker kill/restart |
| 25 | backend restart | unchanged S3 real-backend forced teardown/restart |
| 26 | malformed broker response | S4 extra-field fault response |
| 27 | oversized response | S4 operation response-limit frame |
| 28 | request-ID reuse | S3 denial; S4 proves random uniqueness to terminal limit |
| 29 | unauthorized operation | protocol role matrix/static + unchanged S3 role denial |
| 30 | no HTTP fallback | static source + installed package-binary negative scan; updater fixed HTTPS is separate |
| 31 | no provider fallback | static source + S4 live; package executes no provider operation |
| 32 | no backend endpoint exposure | static UI/CSP/manifest/result scans |
| 33 | no credential exposure | VERIFIED FOR BRANCH CHECKPOINT `dc4aff6` — webview/result/package projection passes; both native child seams construct only a named safe runtime environment, never query restricted credential/configuration values, and pin `thainer`/`fake`; exact branch CI 31393684276 and package smoke 31393684282 passed before integration |
| 34 | no Python session ID exposure | S4 handle shape/cross-owner test + S3 projection |
| 35 | value-free errors | S4 fixed error set/debug checks + JS safe messages |
| 36 | window/app shutdown cleanup | Desktop Rust cleanup tests + package zero-child delta |
| 37 | multiple Desktop instances | S4 independent connections and simultaneous start |
| 38 | repeated launch/connect/quit stability | S4 24 cycles + package five runs |

The unchanged Slice 1 conformance targets pin the complete role, operation,
schema, error, deadline, size, canonical serialization, hello/version, request
ID, and no-replay contract. No Desktop-specific policy copy is authoritative;
the two necessary JS constants (PDF raw limit and fixed localized error map)
have conformance tests against `protocol-v1.json`.

## Legacy-path negative proof

Source and packaged-output tests prove production Desktop does not:

- call backend/data-plane localhost HTTP or scan/select ports;
- start Python or launch the legacy sidecar;
- read/store backend API keys, boot keys, or backend URLs;
- run backend health/retry independently;
- use `reqwest`, Tauri shell, arbitrary URL/network, or fallback paths; or
- implement or directly invoke providers.

The Rust updater still performs its separately allowlisted fixed-host HTTPS
work. A parent process can contain arbitrary environment values, but the
installed-product path does not use credential values as configuration or pass
the restricted variables into broker/backend children. Unsupported selectors
fail before broker connection or launch. Focused environment fixtures record
only value-free booleans and the fixed `thainer`/`fake` identity.

`sidecar.rs` and the Tauri shell dependency are removed. The frozen Python
binary remains packaged because it is the broker-owned private backend, not
Desktop runtime authority. The `package-smoke` feature is test-only, absent
from default features, and runs only when both compiled into the candidate and
explicitly requested by the native process environment. Its three additional
Tauri commands carry only bounded timing/success/fixed-stage evidence; they do
not accept or return product payloads.

## Controlled performance and resources

An earlier controlled core comparison on the same dirty branch uses exact base
`33989cac356330ff4efdb080c470b8bb63561c6a` in a detached worktree on the same
Windows host. Later Slice 4 package/lifecycle edits do not touch the measured
core paths, but this is still provisional branch evidence rather than an
immutable final-candidate measurement. The committed core baseline remains
unchanged.

### In-process core control

| Metric | Exact base | Candidate | Change |
|---|---:|---:|---:|
| detect | 8.80 ms | 8.12 ms | -7.7% |
| sanitize | 24.32 ms | 21.93 ms | -9.8% |
| restore | 0.27 ms | 0.26 ms | -3.7% |
| PDF redact | 105.14 ms | 107.10 ms | +1.9% |
| RSS | 155.3 MiB | 155.6 MiB | +0.2% |

Both exact base and candidate are red against the older committed timing
anchors; their branch-relative result is flat or faster except +1.9% PDF and
+0.2% RSS. The baseline was not moved.

### Desktop path

The historical dirty-tree installed evidence measures the actual feature-gated
webview, production JavaScript API, typed Tauri commands, Rust client, broker,
and private backend. It is not directly comparable with the earlier direct-Rust
portable harness, so those older per-operation values are not promoted here.

| Installed Windows metric | Provisional dirty-tree candidate |
|---|---:|
| cold process lifetime | 5,058.208 ms |
| warm process-lifetime median | 994.843 ms |
| cold Desktop ready | 4,121.709 ms |
| warm Desktop ready | 631.752--669.630 ms |
| broker process delta after five runs | 0 |
| backend process delta after five runs | 0 |

| Five-run peak resource | Slice 4 installed candidate |
|---|---:|
| Desktop RSS / handles | 34.812 MiB / 538 |
| Broker RSS / handles | 7.469 MiB / 108 |
| Backend RSS / handles | 195.898 MiB / 317 |

One initial installed launch passed before the separate five-launch run that
produced these numbers. The unchanged package then passed one plus three more
launches while the Unix process checker was hardened, followed by two final
launches under mandatory, fail-closed `psutil` resource sampling and exact-path
Windows residual-process checks. The latest run completed in 11,355.060 ms,
reached Desktop readiness in 9,846.395 ms, recorded positive finite resource
values for all three processes, and again left zero broker/backend process
delta. The twelve total launches show substantial host and cache timing
variability; because the product bytes did not change, no
timing improvement or regression is inferred from the follow-up runs. The
native live client also completed 24
connect/health/open/close/drop cycles with no handle growth beyond its
two-handle allowance and no more than 32 MiB RSS variance.

## Historical dirty-tree installed Windows smoke

The ordinary Windows NSIS build ran the normal bundle hook, placed
`native-components-v1.json` beside the installed Desktop, native broker, and
frozen Python backend, and pinned the exact final bytes Tauri installed. The
feature-gated candidate installer is:

- file: `AI Guard_2.5.0_x64-setup.exe`;
- SHA-256:
  `7277341A62CEF70C8431BE4AEA51E9C0CA916E8C01ABDC8D0267C087869AE681`;
- source identity: uncommitted dirty tree on
  `codex/phase-8-native-broker-desktop`; and
- isolated install root: `artifacts/slice4-nsis-installed`.

Twelve installed launches passed: the first run, a separate five-launch pass,
one plus three follow-up launches against the unchanged package, and two final
runs under mandatory fail-closed resource sampling. The installed
`desktop.exe` loaded the feature-gated package script in the real webview. That
script waited for the production app readiness result and then called the
production JavaScript API through actual typed Tauri commands. It exercised:

- broker/private-backend health;
- analyze;
- fresh sanitize and same-session continuation sanitize;
- native reidentification validation before masked clipboard publication;
- reidentify;
- analyze-report and a real synthetic report PDF;
- redaction of a real synthetic input PDF;
- audit;
- explicit session disposal and scope reset; and
- repeated app shutdown with zero broker/backend process delta.

The retained evidence contains exactly eleven bounded timings and no text,
session handle, result, provider body, credential, or endpoint. Fixed-stage
failure evidence is likewise payload-free. The smoke did not exercise detect,
guard, roundtrip, a fake-provider roundtrip, a live provider, or live TNER.

This demonstrates that the historical Windows migration was not source-only or
merely a portable directory. It remains provisional dirty-tree evidence and
does not certify any clean executable checkpoint or, at that historical point,
close the credential/configuration decision, macOS/Linux package runs, manual visual or
updater behavior, relocation, upgrade, uninstall, release, or deployment.

## Clean-branch package checkpoints

Clean predecessor `c6dcad168395e44cc52a72674f0ff9d72483cbcf`
[passed all 14 CI jobs](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31325662048),
including a fresh NSIS build, silent install into an isolated Windows root, and
two feature-gated installed launches. Later commit
`0424716aabe5dcdbe07e79c9cd070879e6c7a44a` had a green native macOS job that
built, relocated, and twice smoked the exact `.app` layout in
[cross-platform run 31326610316](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31326610316).
That workflow is not green overall because its Linux job failed, and the macOS
job did not install through DMG or copy to `/Applications`.

Earlier predecessor `8be9523`
[CI run 31327288545](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31327288545)
passed all 14 jobs, including two launches from the exact isolated Windows NSIS
installation. Artifact `9042030989` contains the tested installer and
value-free evidence. The `AI-Guard-windows-x64-setup.exe` payload is 70,507,888
bytes with SHA-256
`dfa777757ec9961679dcd5074fa48cffb446166fb2b229d418e1f5eb816ebc6c`.
Its two launches measured 15,059.672 ms cold and 1,351.655 ms warm process
lifetime, left zero broker/backend process delta, and recorded peak RSS/handles
of Desktop 40.176 MiB/536, broker 9.871 MiB/114, and backend 193.91 MiB/330.
In
[cross-platform run 31327288595](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31327288595),
macOS job `93279571751` built, relocated, and smoked the exact app successfully.
Linux job `93279571732` failed in the extracted-layout step before Desktop
launch with `Unix process executable inspection unavailable`: the baseline
scan treated an unrelated protected same-UID process as fatal. This is a
diagnostic harness failure, not a successful or failed Desktop package launch.
The overall run is red and supplies no Linux DEB/AppImage result.

That predecessor's exact relocated macOS app archive SHA-256 is
`5ec08f3d0d2ab051fa4f1b43d33fc31bd1770b86d33d06a402993c689335b96b`.
Its two launches measured 8,680.034 ms cold and 2,317.7 ms warm process
lifetime, left zero broker/backend process delta, and recorded peak RSS/open
handles of Desktop 102.766 MiB/14, broker 5.859 MiB/10, and backend
227.453 MiB/22. These are relocated-app metrics inside a failed overall
workflow, not a cross-platform or installation pass.

Predecessor `6ad3422` restricts the Linux baseline scan with a process-name
prefilter, then keeps exact `/proc/<pid>/exe` path comparison and fail-closed
inspection for actual component candidates.
Independent review of
that fix found no new blocker. Its 56 focused package/workflow tests, Ruff,
format, diff-check, and real WSL clean-parser probe pass locally. Checkpoint
[CI run 31328047804](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31328047804)
passes all 14 jobs, including the two-run installed Windows NSIS smoke.
Artifact `9042210975` contains the tested installer and value-free evidence.
The `AI-Guard-windows-x64-setup.exe` payload is 70,498,389 bytes with SHA-256
`c014a400ae622815a94be6a4f2686e7dac900cdff10ec1fdeaa3d5c4ab56a1b3`.
Its two launches measured 13,624.080 ms cold and 1,020.995 ms warm process
lifetime, left zero broker/backend process delta, and recorded peak RSS/handles
of Desktop 40.270 MiB/536, broker 9.836 MiB/114, and backend 192.801 MiB/330.

[Cross-platform run 31328047802](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31328047802)
is red. The checkpoint macOS job passed, and the extracted DEB completed both
production-WebKit smoke runs. AppImage exact-component digest verification
failed before AppImage Desktop launch because Tauri/linuxdeploy mutated the ELF
component bytes after the pre-bundle manifest hashes were computed. Therefore
the run supplies neither an AppImage pass nor a full Linux/cross-platform pass.

The checkpoint's relocated macOS app artifact is `9042161197`. Its tested app
archive is 69,655,119 bytes with SHA-256
`8d22957bba783737df954dee5c2a76a012ebeb1bb6f4c1f04886e93916245939`.
Component SHA-256 values are Desktop
`8b1b2a1652285824844b5dd6a49acd88bdd49715da36b8c6faef036c61fa5b53`,
broker `a83bc75150b391aa7c66dcc849f68197d7abe4e943df128e4e3b4b7e6df5bb07`,
backend `6f728945ab0bd360a64918f7ac982a72d5676f1c7d220a5e417e45e713151a55`,
and manifest
`93e9f5ddaeaaa7c40e926e5e115f646a19eaa4b99f09b948d15d8af8ae07bd88`.
Two launches measured 7,564.331 ms cold and 2,585.182 ms warm process lifetime,
left zero broker/backend process delta, and recorded peak RSS/open handles of
Desktop 103.781 MiB/14, broker 5.922 MiB/10, and backend 227.234 MiB/22. This is
relocated-app evidence inside a failed workflow, not installation,
notarization, or cross-platform acceptance.

Predecessor `3836024` leaves the AppImage pre-manifest deliberately invalid,
hashes the actual post-linuxdeploy AppDir Desktop, broker, and backend bytes,
and repacks with checksum-pinned linuxdeploy AppImage plugin asset `497460911`.
Its CI run 31329794579 passed 14/14, but cross-platform run 31329794568 failed
Linux finalization before package smoke because its raw-prefix guard rejected
appimagetool's defined `.digest_md5` rewrite. The macOS job passed.

Predecessor executable/implementation checkpoint `73dcca4` copies the trusted
original runtime prefix before repacking. For the pinned, scrubbed
no-sign/no-update AppImage invocation, it parses both prefixes as little-endian
x86-64 ELF64 and permits mutation only in the single non-executable,
non-overlapping 16-byte `.digest_md5` section that appimagetool rewrites after
appending SquashFS. The section range must remain identical and every other
runtime-prefix byte must match. Only after that attestation does it execute the
repacked runtime to confirm its offset, re-extract the image, compare the
Desktop, broker, backend, and manifest bytes, and atomically replace the
candidate. Seventy-six focused package/workflow tests pass. Exact-delta review
found and closed executable-`PT_LOAD` overlap, then found no P0/P1/P2. Exact
[CI run 31345691672](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31345691672)
passed all 14 jobs, including the isolated installed-Windows NSIS smoke. Its
tested installer is 70,501,752 bytes with SHA-256
`e59053e5a18e115d7dddf7ca1b35922bf7b17d20c5bb5452bdaca1454bff6fe2`.
Two launches measured 12,950.533 ms cold and 1,184.758 ms warm, left zero
broker/backend process delta, and recorded peak RSS/handles of Desktop
39.957 MiB/541, broker 9.836 MiB/114, and backend 193.285 MiB/326.

[cross-platform run 31345691667](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31345691667)
is red. The relocated macOS job passed and Linux DEB completed both smoke
repetitions. Linux AppImage build, finalization, and independent extraction
passed, but the workflow then bypassed the outer runtime and `AppRun`, launched
the inner Desktop binary directly, and received no evidence marker. This is a
package-harness entrypoint defect, not proof that the finalized AppImage fails.
It supplies no AppImage or full Linux/cross-platform pass.

The `73dcca4` macOS artifact is `9047326014`. Its exact tested archive is
69,655,237 bytes with SHA-256
`5051d58ca1668d15b114e30d948087bf511ec51d61d010f6e40c649a19f11d9e`.
Component SHA-256 values are Desktop
`8b1b2a1652285824844b5dd6a49acd88bdd49715da36b8c6faef036c61fa5b53`,
broker `a83bc75150b391aa7c66dcc849f68197d7abe4e943df128e4e3b4b7e6df5bb07`,
backend `e379ca783eadf78f16928dc68d664373a55324830f05106544e128b566482d80`,
and manifest
`590dd248ea6a396541e511ab9964355fe94d7eb25445daa41bf557ad9c0c3cbd`.
Two launches measured 7,892.874 ms cold and 2,476.736 ms warm, left zero
broker/backend process delta, and recorded peak RSS/open handles of Desktop
103.828 MiB/12, broker 5.891 MiB/10, and backend 227.297 MiB/22. This is
relocated-app evidence, not installation, notarization, or a green
cross-platform workflow.

Predecessor `8194c23e0a6dfc1530257424664235740b5337c2` moves AppImage smoke
markers out of the runtime/package working directory. The Python harness
precreates a canonical private isolation root and passes its `evidence`
subdirectory through `AIGUARD_DESKTOP_PACKAGE_SMOKE_ROOT`. Rust accepts a
supplied root only when it is absolute, canonical, an actual directory, not a
symlink/reparse alias, and exactly mode `0700` on Unix; an invalid supplied root
fails without falling back to the package directory. Native-start, ready,
bounded value-free JSON evidence, and allowlisted failure-stage writers share
that root, use four fixed names, and create without overwriting an existing
entry. Direct Windows/macOS/DEB layout smoke intentionally retains the
environment-absent package-directory path.

[CI run 31348501253](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31348501253)
completed red with 10 of 14 jobs passing. Jobs `93334826977`, `93334827045`,
`93334827055`, and `93334827066` failed only
`package_smoke::tests::private_marker_root_requires_a_canonical_private_directory`:
Linux `Path` equality hid an inserted `.` component, while Windows and macOS
canonicalized the initial temporary root to a different path spelling. The
installed-Windows package job `93334827088` separately passed both
`direct_package_layout` launches with zero broker/backend process delta and
uploaded artifact `9048319122`. The upload wrapper is 70,494,887 bytes with ZIP
digest
`545833b2d71d0cd8d77036e62da7a310a7e4cbc0dd272c6a6f3bbc10fbac71f6`;
neither value is claimed as the installer payload size or SHA-256.

[Cross-platform package run 31348501256](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31348501256)
passed both jobs. macOS job `93334826678` twice ran the relocated app and
uploaded artifact `9048238724`; the exact tested archive SHA-256 is
`48881bf929258fe980ff43b2dc4fa948b0a122e55cbb1508bdf9e817a533a624`.
Linux job `93334826622` finalized the AppImage, directly ran the extracted DEB,
and crossed the exact finalized outer AppImage with
`--appimage-extract-and-run`. The independent `--appimage-extract` layout was
used only to attest bytes. After the outer runtime emitted native-start, the
harness verified its retained live root; the warm repetition re-attested that
root and launched its `AppRun`. The result records
`execution_mode=outer_appimage_extract_and_run_then_verified_apprun`, not a raw
inner-binary launch or two outer launches. Artifact `9048343920` contains the
tested DEB with SHA-256
`5f6dde7aed7335ccb6944560fc4aecc993c09a6c6f5cbd18964b0ae2074ca127`,
the finalized AppImage with SHA-256
`0b139d9f03d88d1a2984445de8d2e08d29fe42ce6120072524dd9ed5ed8cc17d`,
and the tested-packages archive with SHA-256
`e20ea749aeb9743588ee441474628ce34a12d4fd676f2a7e18a874db92251c7a`.
The normalized x86-64 runtime was 944,632 bytes with SHA-256
`1cc49bcf1e2ccd593c379adb17c9f85a36d619088296504de95b1d06215aebbf`,
and the pinned output-plugin digest
`a45d3e227bc7f397e9cf6bfa4c9507494efa2293357b6e86690a3de2ca992e79`
matched. These are exact predecessor package results even though the same
checkpoint's main CI was red.

Last fully gated checkpoint `492dad34361b09d7ffa58fa192a2447de7414418`
retains that production contract and changes only portable canonical-path test
construction: it canonicalizes the temporary base first and compares raw
`OsStr` values on non-Windows so literal `.`/`..` aliases remain rejectable.
Focused Python package/workflow verification passes 100 with one expected
Windows skip because that host cannot preserve Unix execute bits. Full local
Rust runs of 19 default and 26 all-feature tests preceded the final
portability-only edit. After it, the exact private-root test passed on Windows
and real WSL; exact CI confirms all 26 Desktop tests on Ubuntu, Windows, and
macOS. Affected Ruff, Python format, rustfmt, strict all-target/all-feature
Clippy, and diff-check gates pass.
[CI run 31349781519](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31349781519)
and
[cross-platform package run 31349781518](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31349781518)
passed 14/14 and 2/2 respectively. The CI source matrices recorded 2,574 passed,
32 skipped, and one warning on Ubuntu Python; 2,571 passed, 35 skipped, and one
warning on Windows Python; and 2,200 passed plus 289 skipped in the core-only
matrix. Root Vitest passed 148 tests in 20 files, Office passed 129 tests in 12
files, and combined Cargo source jobs passed 90 native-broker plus 26 Desktop
tests—116 total with no failure or ignored test. The platform-native runtime
matrices also passed, including 26 Desktop tests on each host.

Windows package job `93338310651` passed two
`execution_mode=direct_package_layout` launches from the exact isolated NSIS
installation. Artifact `9048710352` contains the 70,500,529-byte tested
installer with SHA-256
`6ca6f5dc3fcdfc3dfc51c210ace1734bcede7f77298d1e3ea7019d9d8b5a425c`.
The GitHub artifact wrapper is separately 70,501,963 bytes with SHA-256
`961f9e8e25e150e0e5ad7e7124d56569b100e4fb671adfa7f5c51b3f4f8ab4ee`.
Cold/warm process time was 12,700.550/1,254.659 ms; readiness was
11,551.914/899.431 ms; workflow time was 5,427.6/456.5 ms. Broker/backend
process deltas were zero, and peak RSS/handles were Desktop 40.277 MiB/539,
broker 9.871 MiB/115, and backend 192.410 MiB/330. This is isolated silent NSIS
installation evidence, not manual UI, updater, upgrade, or uninstall evidence.

macOS package job `93338310626` passed two relocated
`direct_package_layout` launches. Artifact `9048609980` has GitHub wrapper
SHA-256
`fec48c469442f2ce758dc02911b5f9c744538424b7d89f086ac2076107c9e0e5`
and wrapper size 69,659,580 bytes; the internal exact tested-app archive
SHA-256 is
`15a64e25af00f30e288f62c837725cccb9e9588fc0f90d668a57d6d1164f0de8`.
Component SHA-256 values are Desktop
`a8c8e9169e3eb48ac3552b52fe7a23dfaff21ed1c491b683cb0a2fbb3cb7237d`,
broker `a83bc75150b391aa7c66dcc849f68197d7abe4e943df128e4e3b4b7e6df5bb07`,
backend `42f98ccf7f51d9eeff1b29da399c6b497e0199d43c58a6e0fa442dd9bfe5536e`,
and manifest
`5d9e3fa516cee93803273b6da6c9f817bfce1dd5dcc589332efec7f8f997fc43`.
Cold/warm process time was 6,622.296/2,033.435 ms; readiness was
5,466.663/1,927.510 ms; workflow time was 3,103/335 ms. Process deltas were
zero, and peak RSS/open handles were Desktop 105.391 MiB/13, broker
5.891 MiB/10, and backend 227.484 MiB/22. This remains relocation-only, not
installation, notarization, or `/Applications` evidence.

Linux package job `93338310580` passed the directly extracted DEB and finalized
AppImage. Artifact `9048696066` has GitHub wrapper SHA-256
`3d7f55e86bbaa489a88a2a0c1048b069d5b3ffca47ad8ed28e9c43508633a3b9`
and wrapper size 268,480,689 bytes. Its internal DEB SHA-256 is
`7411b1c976d66a7e4e4a48f757ad751eb69ac0a8a4105d318559ab64fc30bfb7`,
the finalized AppImage SHA-256 is
`915d4ebb139ee69a1d9514d6fdb306ab7e2bbd02e12a858bb4deaedcf5a1f5f7`,
and the exact tested-packages archive SHA-256 is
`b72f101287dcf09dc7f46ae84c8329a295811600d5a3fb8a7666619d068a0f0f`.
The extracted DEB direct layout measured 5,578.529/1,231.631 ms cold/warm with
peak Desktop/broker/backend RSS of 192.605/5.062/202.703 MiB. The exact outer
AppImage plus verified warm `AppRun` measured 5,229.620/1,295.145 ms with peak
RSS of 196.895/5.031/202.582 MiB and
`execution_mode=outer_appimage_extract_and_run_then_verified_apprun`. Both left
zero broker/backend process delta. The DEB result is extraction, not
package-manager installation; the AppImage result is not normal
FUSE/double-click or installation evidence.

## Evidence ledger

| Gate | Result |
|---|---|
| Tests-first red checkpoint | PASS — expected 1 compile, 7 Python, and 11 JS failures before production code |
| Slice 1 protocol/conformance | PRIOR LOCAL PASS — included in the full Windows native-broker matrix |
| Slice 2 runtime/bootstrap | PRIOR LOCAL PASS — included in the full Windows native-broker matrix; its formerly unguarded manifest fixture now uses the existing broker test guard |
| Slice 3 data plane | PRIOR LOCAL PASS — included in the full Windows native-broker matrix and exercised by the live Slice 4 path |
| Slice 4 Desktop migration | INTEGRATED — branch checkpoint `dc4aff6705e296890424b3fa4e88a8689300c7ed` passed full branch CI 31393684276 (14/14), cross-platform package smoke 31393684282 (2/2), and independent review before squash integration |
| Installed configuration correction | VERIFIED — focused regressions cover unsupported selectors before broker use, warm-broker attachment, both name-allowlisted and pinned child seams, broker/backend startup, and pre-backend non-`fake` provider rejection; the exact branch CI and package smoke above re-exercised the complete required gates |
| Focused Python | PRIOR LOCAL PASS — 56 passed, two expected Unix-only skips on Windows; the package-only subset passed 32 |
| Current package/workflow Python | LOCAL PASS FOR `492dad3` — 100 passed, one expected Windows skip because that host cannot preserve Unix execute bits |
| Full Python | PRIOR LOCAL PASS — 2,544 passed, seven optional-platform skips |
| Current Python CI matrices | PASS FOR `492dad3` — Ubuntu 2,574 passed/32 skipped/one warning; Windows 2,571 passed/35 skipped/one warning; core-only 2,200 passed/289 skipped |
| Root JavaScript | PRIOR LOCAL PASS — 145 passed in 20 files |
| Current JavaScript/Office CI | PASS FOR `492dad3` — root Vitest 148 tests in 20 files; Office 129 tests in 12 files |
| Desktop Rust all features | PRIOR LOCAL PASS — 23 passed, none failed or ignored |
| Current Desktop Rust | PASS FOR `492dad3` WITH TIMING QUALIFIER — full local runs of 19 default and 26 all-feature tests plus rustfmt/strict Clippy preceded the final portability-only edit; afterward the exact private-root test passed on Windows and real WSL, and exact CI passed all 26 Desktop tests on Ubuntu, Windows, and macOS |
| Native broker | PRIOR LOCAL PASS — full Windows matrix passed 120 active tests with 8 intentional fixture ignores; Windows library 13 passed and WSL2 Linux library 14 passed; Slice 4 integration passed 9 active plus 3 invoked subprocess fixtures on both Windows and WSL2 Linux |
| Current combined Cargo source jobs | PASS FOR `492dad3` — native-broker suites passed 90 (14 + 20 + 22 + 1 + 33) and Desktop passed 26; 116 total with zero failures or ignored tests |
| Ruff/rustfmt/Clippy | PRIOR LOCAL PASS — all 234 Python files formatted and checked; affected Rust fmt and strict all-target/all-feature Clippy passed |
| Controlled exact-base core performance | PASS with disclosed stale-anchor result; installed webview path has measurements but no matching exact-base comparison |
| Historical dirty-tree installed Windows NSIS | PROVISIONAL PASS — exact dirty-tree installer passed 12 total launches; final runs required complete positive resource evidence and exact-path residual checks; zero residual broker/backend processes; not clean-checkpoint evidence |
| Clean predecessor installed Windows NSIS | PASS FOR `c6dcad1` ONLY — CI run 31325662048 passed 14/14, including two launches from an isolated NSIS install root; not checkpoint evidence |
| Earlier-predecessor installed Windows NSIS | PASS FOR `8be9523` ONLY — CI run 31327288545 passed 14/14, including two launches from the exact isolated install root; artifact 9042030989; NSIS SHA-256 `dfa777757ec9961679dcd5074fa48cffb446166fb2b229d418e1f5eb816ebc6c` |
| Immediate-predecessor installed Windows NSIS | PASS FOR `6ad3422` ONLY — CI run 31328047804 passed 14/14, including two launches from the exact isolated NSIS installation; artifact 9042210975; NSIS SHA-256 `c014a400ae622815a94be6a4f2686e7dac900cdff10ec1fdeaa3d5c4ab56a1b3` |
| Predecessor installed Windows NSIS | PASS FOR `3836024` ONLY — CI run 31329794579 passed 14/14 including the installed NSIS job; not current-checkpoint evidence |
| `73dcca4` installed Windows NSIS | PASS FOR `73dcca4` ONLY — CI run 31345691672 passed 14/14; artifact 9047406111; tested installer SHA-256 `e59053e5a18e115d7dddf7ca1b35922bf7b17d20c5bb5452bdaca1454bff6fe2` |
| `8194c23` installed Windows NSIS | PASS FOR JOB `93334827088` ONLY — two installed-root direct-layout launches passed with zero broker/backend delta even though CI run 31348501253 was red 10/14 on the portable path test; artifact 9048319122; known SHA-256 `545833b2d71d0cd8d77036e62da7a310a7e4cbc0dd272c6a6f3bbc10fbac71f6` is the GitHub artifact ZIP digest, not an installer hash |
| `492dad3` installed Windows NSIS | PASS — CI run 31349781519 passed 14/14; job 93338310651; artifact 9048710352; exact tested installer 70,500,529 bytes with SHA-256 `6ca6f5dc3fcdfc3dfc51c210ace1734bcede7f77298d1e3ea7019d9d8b5a425c`; two installed-root launches; zero broker/backend process delta |
| Clean predecessor relocated macOS app | PASS FOR `0424716` macOS JOB ONLY — the macOS job passed two relocated-layout launches in run 31326610316, but the overall workflow failed on Linux; not installation or checkpoint evidence |
| Earlier-predecessor relocated macOS app | PASS FOR `8be9523` RELOCATED LAYOUT ONLY — job 93279571751 passed in cross-platform run 31327288595; the workflow is red overall and this is not installation/notarization evidence |
| Immediate-predecessor relocated macOS app | PASS FOR `6ad3422` RELOCATED LAYOUT ONLY — macOS job in run 31328047802; artifact 9042161197; tested-app archive SHA-256 `8d22957bba783737df954dee5c2a76a012ebeb1bb6f4c1f04886e93916245939`; workflow failed on AppImage |
| Predecessor relocated macOS app | PASS FOR `3836024` MACOS JOB ONLY — the job passed in red cross-platform run 31329794568; not installation or current-checkpoint evidence |
| `73dcca4` relocated macOS app | PASS FOR `73dcca4` MACOS JOB ONLY — two relocated-layout launches passed in red run 31345691667; artifact 9047326014; tested archive SHA-256 `5051d58ca1668d15b114e30d948087bf511ec51d61d010f6e40c649a19f11d9e`; not installation/notarization evidence |
| `8194c23` relocated macOS app | PASS FOR `8194c23` ONLY — job 93334826678 in green run 31348501256; artifact 9048238724; tested archive SHA-256 `48881bf929258fe980ff43b2dc4fa948b0a122e55cbb1508bdf9e817a533a624`; not installation/notarization evidence |
| `492dad3` relocated macOS app | PASS FOR RELOCATED LAYOUT — green run 31349781518, job 93338310626; artifact 9048609980; internal tested archive SHA-256 `15a64e25af00f30e288f62c837725cccb9e9588fc0f90d668a57d6d1164f0de8`; two launches and zero broker/backend process delta; not installation/notarization evidence |
| Earlier-predecessor extracted Linux DEB/AppImage | DIAGNOSTIC FAILURE — `8be9523` job 93279571732 failed before Desktop launch because process inspection rejected an unrelated protected same-UID process; no Linux package pass/fail result |
| Immediate-predecessor extracted Linux DEB/AppImage | PARTIAL/FAIL — `6ad3422` extracted DEB completed both production-WebKit runs; AppImage component digest verification failed before AppImage Desktop launch because packaging mutated the bytes after the pre-bundle hash; no AppImage or full Linux pass |
| Predecessor extracted Linux DEB/AppImage | DIAGNOSTIC FAILURE — `3836024` Linux finalization rejected the defined `.digest_md5` rewrite before package smoke; no Linux package result |
| `73dcca4` extracted Linux DEB/AppImage | PARTIAL/DIAGNOSTIC FAILURE — DEB completed both runs; AppImage finalization/extraction passed, then the harness bypassed runtime/AppRun and raw-launched Desktop with no marker; no AppImage or full Linux pass |
| `8194c23` extracted Linux DEB | PASS FOR `8194c23` ONLY — direct-layout smoke passed in job 93334826622; tested DEB SHA-256 `5f6dde7aed7335ccb6944560fc4aecc993c09a6c6f5cbd18964b0ae2074ca127`; not package-manager installation evidence |
| `8194c23` finalized outer AppImage plus warm `AppRun` | PASS FOR `8194c23` ONLY — green run 31348501256 crossed exact outer `--appimage-extract-and-run`, then re-attested the retained root and launched warm `AppRun`; `execution_mode=outer_appimage_extract_and_run_then_verified_apprun`; artifact 9048343920; tested AppImage SHA-256 `0b139d9f03d88d1a2984445de8d2e08d29fe42ce6120072524dd9ed5ed8cc17d`; not normal FUSE/double-click or installation evidence |
| `492dad3` extracted Linux DEB | PASS FOR EXTRACTED LAYOUT — green run 31349781518, job 93338310580; artifact 9048696066; internal DEB SHA-256 `7411b1c976d66a7e4e4a48f757ad751eb69ac0a8a4105d318559ab64fc30bfb7`; two direct-layout launches and zero broker/backend process delta; not package-manager installation evidence |
| `492dad3` finalized outer AppImage plus warm `AppRun` | PASS — green run 31349781518, job 93338310580; exact finalized AppImage SHA-256 `915d4ebb139ee69a1d9514d6fdb306ab7e2bbd02e12a858bb4deaedcf5a1f5f7`; outer `--appimage-extract-and-run` followed by re-attested warm `AppRun`; zero broker/backend process delta; not normal FUSE/double-click or installation evidence |
| Live provider and live TNER | OUTSIDE INSTALLED DESKTOP — the current installed product deliberately supports neither; no Slice 4 package smoke uses real credentials, quota, or provider/TNER endpoints, and broader-interface live acceptance remains separately open |
| Manual visual, updater, relocation install, upgrade, interrupted-upgrade, stale-cleanup, uninstall | PENDING — automated package smoke does not close these Slice 6 gates |
| Credential/configuration ownership | SOURCE DECISION IMPLEMENTED — installed Desktop supports local `thainer` only, carries no credential-requiring provider/TNER configuration into children, and defers any future credential capability to a separate owner-approved ADR |
| Independent complete-diff security review | PENDING FOR CORRECTION — historical reviews through `492dad3` remain valid for those exact checkpoints; the owner-decision configuration delta requires its own independent exact-diff review |
| Full repository/Office/version/release/RustSec/audit gates | LAST FULLY GATED CHECKPOINT PASS — exact `492dad3` run 31349781519 passed 14/14; the correction's complete exact-head matrix remains pending |
| Windows native source/runtime | CURRENT PASS — exact `492dad3` source/runtime jobs and two-run installed-NSIS smoke passed |
| real WSL2 Linux source/runtime | PRIOR LOCAL PASS — Desktop all-feature 23 passed; native library 14 passed; Slice 4 integration 9 active passed with 3 invoked subprocess fixtures ignored; this is not Linux package evidence |
| macOS native source/runtime | CURRENT RELOCATED-LAYOUT PASS — exact `492dad3` source/runtime job and two-run relocated-app smoke passed; not installation evidence |
| Last fully gated implementation-checkpoint branch CI | PASS FOR `492dad3` — run 31349781519 passed 14/14; no exact-head CI claim is made for the correction yet |
| Last fully gated implementation-checkpoint cross-platform package workflow | PASS FOR `492dad3` — run 31349781518 passed 2/2 across relocated macOS, direct extracted DEB, and faithful outer-AppImage/warm-`AppRun` execution; no correction package claim yet |
| Squash integration and post-main CI | PENDING |

## Commands captured and current clean-build precondition

```powershell
$env:PYTHONUTF8='1'
.\.venv\Scripts\python.exe -m pytest -q `
  tests/test_desktop_native_broker_migration.py `
  tests/test_desktop_native_package.py tests/test_native_broker_backend.py `
  tests/test_desktop_capabilities.py
.\.venv\Scripts\python.exe -m pytest -q tests/test_desktop_native_package.py
.\.venv\Scripts\python.exe -m pytest -q
npm run test:js -- --run
cargo test --locked --manifest-path desktop/src-tauri/Cargo.toml
cargo test --locked --manifest-path desktop/src-tauri/Cargo.toml `
  --features package-smoke
cargo clippy --locked --manifest-path desktop/src-tauri/Cargo.toml `
  --all-targets --all-features -- -D warnings
cargo test --locked --manifest-path native-broker/Cargo.toml `
  --test slice4 -- --nocapture
cargo test --locked --manifest-path native-broker/Cargo.toml
wsl -- env AIGUARD_TEST_PYTHON=/tmp/aiguard-slice3-venv/bin/python `
  CARGO_TARGET_DIR=/tmp/aiguard-slice4-desktop-target cargo test --locked `
  --manifest-path /mnt/c/Users/teera/dev/thai-pii-redaction/desktop/src-tauri/Cargo.toml `
  --all-features
wsl -- env AIGUARD_TEST_PYTHON=/tmp/aiguard-slice3-venv/bin/python `
  CARGO_TARGET_DIR=/tmp/aiguard-slice4-native-target cargo test --locked `
  --manifest-path /mnt/c/Users/teera/dev/thai-pii-redaction/native-broker/Cargo.toml `
  --lib
wsl -- env AIGUARD_TEST_PYTHON=/tmp/aiguard-slice3-venv/bin/python `
  CARGO_TARGET_DIR=/tmp/aiguard-slice4-native-target cargo test --locked `
  --manifest-path /mnt/c/Users/teera/dev/thai-pii-redaction/native-broker/Cargo.toml `
  --test slice4 -- --nocapture
.\.venv\Scripts\python.exe scripts/measure_perf.py --iterations 20
.\.venv\Scripts\python.exe scripts/build_sidecar.py
.\.venv\Scripts\python.exe scripts/build_native_broker.py
.\.venv\Scripts\python.exe scripts/prepare_desktop_native_package.py `
  --build-placeholders
Push-Location desktop
npm run tauri -- build --bundles nsis --features package-smoke --ci --no-sign `
  --config '{"bundle":{"createUpdaterArtifacts":false}}'
Pop-Location
Get-FileHash -Algorithm SHA256 `
  'desktop/src-tauri/target/release/bundle/nsis/AI Guard_2.5.0_x64-setup.exe'
.\.venv\Scripts\python.exe scripts/smoke_desktop_native_package.py `
  artifacts/slice4-nsis-installed --repetitions 5
```

`--build-placeholders` is required on a clean tree so Tauri can discover every
bundle-specific resource. It writes deliberately invalid `{}` placeholders;
for the NSIS command above, the ordinary `beforeBundleCommand` must replace the
selected placeholder with the direct-bundle manifest. AppImage deliberately
keeps its invalid pre-manifest until the post-linuxdeploy finalizer hashes the
actual AppDir components, repacks, and verifies the result. A placeholder is
never a runnable manifest or acceptance evidence.

## Independent review

The completed separate-context implementation review inspected
Tauri command exposure, arbitrary-operation injection, webview/native/XSS
escalation, broker role binding, backend/provider endpoint and credential
secrecy, session ownership/stale handles, uncertainty/no replay, HTTP and
legacy-sidecar fallback, multi-instance races, broker/backend/app lifecycle,
shutdown cleanup, fixed errors, clipboard/file/UI publication, package
failure cleanup, exact residual-process checks, and exact-artifact evidence.
All confirmed lifecycle, publication, package, and stale-render findings were
fixed and their affected tests rerun. At that reviewed checkpoint it found no
P0 and no remaining P1/P2 beyond the owner-level credential/configuration
source decision. Final separate-context review of executable checkpoint
`6ad3422` found no additional P0/P1 in the complete Slice 4 diff or the Linux
candidate-filter repair. Independent review of the `3836024` AppImage finalizer
delta found no P0/P1/P2. Exact `73dcca4` review found executable-`PT_LOAD`
overlap in the first bounded mutation verifier, the implementation closed it
with a synthetic regression, and final re-review found no P0/P1/P2. Review of
the `8194c23` private marker-root and faithful AppImage execution boundary found
no additional P0/P1/P2. Final read-only review of `492dad3` verified that raw
non-Windows `OsStr` comparison and canonicalized test-root construction repair
Linux/macOS/Windows CI portability without weakening the production no-alias
contract; it found no P0/P1/P2. The provider/TNER ownership decision remains
the sole confirmed P1 **at that historical checkpoint**. The owner has since
selected and the branch checkpoint implemented the credential-free local
profile described above. Exact CI run 31349781519 and exact package run
31349781518 remain evidence only for `492dad3`; correction checkpoint `dc4aff6`
passed CI 31393684276, package run 31393684282, and a new independent review
before integration.

## Deferred and external gates

- Future installed credentials: credential-requiring providers and remote TNER
  are unsupported by installed Desktop. Adding them requires a separate
  owner-approved ADR covering ownership, provisioning, permissions, storage,
  rotation, configuration identity/epoch, broker restart/reconfiguration,
  upgrade, uninstall, attestation, and cross-platform behavior. This deferred
  capability does not block the current local-only Slice 4 boundary.
- Slice 5: Chrome Native Messaging, native-host adapter/registration,
  Extension migration, Extension packaging, and browser acceptance. **Not
  started; it must branch from the exact integrated Slice 4 main.**
- Slice 6: updater/installer certification, exact installed Windows/macOS/Linux
  artifacts, supported-path relocation, manual visual behavior, updater
  check/install, upgrade/drain, interrupted-upgrade recovery, stale cleanup,
  uninstall, and full packaging recertification. Slice 4 now maps the native
  component manifest into ordinary bundle layouts, but relocated macOS,
  extracted-DEB, and outer-AppImage/warm-`AppRun` CI smoke are not installed
  macOS/Linux lifecycle evidence. The AppImage mode is not normal
  FUSE/double-click acceptance. The tag workflow still fails closed before
  publication because Slice 5 native-messaging registration and the Slice 6
  lifecycle are not certified. **Not started; it must follow integrated Slice
  4 and Slice 5.**
- Office broker integration and Office real-host acceptance remain outside
  protocol v1.
- Live TNER, live provider, manual cross-platform installation,
  signing/notarization, release, deployment, and official hosted platform
  evidence are not claimed while the gates above remain open. The current
  AppImage/full-Linux automated package gate is green but is not a substitute
  for those evidence classes.
- The sibling `aiguard-aift` repository is outside scope and was not modified.
