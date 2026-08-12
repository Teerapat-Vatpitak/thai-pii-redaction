# Phase 8 Slice 5 — Chrome Native Messaging acceptance

Date: 2026-08-11; production-identity closure evidence added 2026-08-12
Status: **production-qualified; integration and post-main outcomes are reported
in the closure report**
Branch: `codex/phase-8-native-broker-extension`
Recovered baseline: `386c18c62aea3324f66c38a6b908ac52cb609872`
Runtime/package candidate: `32e9aa0048a19a4f3e5ba3130cb59a5663b5da71`
Prior Slice 5 acceptance head: `b799363e0330ab93e21bfdef6612acdc475619c4`
Production-identity runtime candidate: `cebf6eb29796797508dc5e4e90c4f85c35b43837`
Final branch and integrated-main heads: reported after the final gates

## Closure decision

The complete migration was first implemented and exercised with a deterministic
synthetic identity. On 2026-08-12 the owner created an unpublished Chrome Web
Store Developer Dashboard item and supplied its Item ID and public manifest
key. The repository now owns that public identity in
`config/chrome-extension-identity.json`; no private signing key was supplied or
committed.

The normal production packager, with no synthetic override, produced an exact-
ID runtime ZIP. Real Chromium loaded the production-keyed candidate as an
unpacked Extension and reported the expected Item ID. The exact CI-produced
NSIS companion installed and registered the same one-origin native-host
manifest, completed the Slice 5 browser/lifecycle matrix, and uninstalled with
zero product registration or process delta. The external production-identity
prerequisite is therefore satisfied.

The Chrome Web Store item remains Draft and unpublished. No Publish, Submit for
review, Send for review, rollout, or public-distribution action was performed.
Because the unpublished item was not installable through a supported Web Store
mechanism without a review/submission action, this record claims exact-ID real-
browser unpacked acceptance, not Chrome Web Store installation acceptance.

## Identity evidence

| Field | Value |
|---|---|
| Production Extension ID | `kdjmkknedgmfphpkjhjdhmjadaelgggm` |
| Production allowed origin | `chrome-extension://kdjmkknedgmfphpkjhjdhmjadaelgggm/` |
| Production classification | `production_owner_approved` |
| Production provenance | owner-approved unpublished Chrome Web Store item created 2026-08-12; Item ID and public key copied from the Developer Dashboard |
| Public DER SHA-256 | `a39caad436c5f7fa97937c90304b666c02f37c16a30607e985c9ec653b9dc256` |
| Derived-ID verification | exact match |
| Historical test Extension ID | `efocdbdljgaaiflfleofbjpenncenhee` |
| Historical test allowed origin | `chrome-extension://efocdbdljgaaiflfleofbjpenncenhee/` |
| Historical test classification | `synthetic_test_only`; isolated to tests/fixtures |
| Wildcard admitted | no |

`scripts/native_host_identity.py` derives the Extension ID from the canonical
public key and requires exact ID/origin agreement. The supplied decoded DER
independently derived `kdjmkknedgmfphpkjhjdhmjadaelgggm` and the exact origin
above. Production builders reject the synthetic classification unless an
explicit acceptance-only flag is used. A build-specific companion manifest
cannot be produced without one exact allowed origin.

## Implemented production boundary

The MV3 service worker owns one long-lived
`chrome.runtime.connectNative("th.ac.psu.aiguard.native_host")` port. Content
scripts and panels use only internal Chrome runtime messaging. Production
manifest/code has no loopback host permission, backend discovery, direct HTTP
client, native broker endpoint, credential, provider selector, remote TNER,
or HTTP fallback.

The thin Rust adapter:

- accepts only Chrome Native Messaging framed stdin/stdout and reserves stdout
  exclusively for valid response frames;
- validates the exact browser-supplied origin, same-user/stable Chrome parent
  process context, installed adapter path/build/digest, and broker role
  `extension` before PII-bearing work;
- bounds frames at 1 MiB, uses strict UTF-8 and duplicate-free exact-field JSON,
  enforces protocol/operation/response limits, and exposes only fixed errors
  and structural event codes;
- translates to shared broker protocol v1 without detector, provider, restore,
  mapping, retry, PDF/document, localhost, or credential logic; and
- has no interactive/standalone privileged mode. Chrome supplies the required
  origin argument and browser parent context.

Enabled operations are health/readiness, token/surrogate sanitize, restore,
scope open/close, and connection lifecycle. Provider completion/selection,
remote TNER, PDF/file work, audit, drain/stop, and arbitrary broker operations
remain unavailable.

## Scope and MV3 lifecycle

- Each admitted top-frame tab gets a broker `extension_tab` scope tied to its
  exact HTTPS origin/document evidence.
- Each connected side-panel instance gets a separate `extension_panel` scope.
- Broker handles remain only inside the service worker. Raw Python session IDs
  and mappings never reach JavaScript.
- Cross-tab, tab/panel, panel/tab, cross-origin-navigation, stale-document, and
  stale-response handle use fails closed.
- Tab or panel close invalidates local authority first and disposes only that
  scope. Unconfirmed cleanup falls back to connection close and the broker's
  authenticated backend-teardown contract.
- Native-port loss or worker/browser restart invalidates all connection-owned
  contexts, clears stale `chrome.storage.session` state, blocks Restore and
  writeback, and publishes only a fixed unavailable/session-expired state.
- Automatic retry is limited to PII-free connect/hello/health. No sanitize,
  restore, or possibly completed request is replayed. Fresh connection
  authority requires a new user-initiated Mask before Restore.
- Desktop exit preserves admitted Extension scopes; Extension exit preserves
  admitted Desktop UI/hotkey scopes. Broker idle exit remains broker-owned.

The provider-page limitation is unchanged: raw text typed into an AI site's
DOM may already be visible to provider-controlled page code before Mask. The
side panel is the stronger raw-entry boundary; this candidate makes no false
device-confinement claim for in-page entry.

## Companion packaging and registration

The Desktop package now owns five native components: Desktop, broker, Chrome
adapter, native-host manager, and frozen Python backend, plus their exact
digest/build manifest.

Native host: `th.ac.psu.aiguard.native_host`
Manifest file: `th.ac.psu.aiguard.native_host.json`

| Platform/package | Registration/discovery path |
|---|---|
| Windows NSIS | exact manifest beside the installed adapter; per-user HKCU 32- and 64-bit views under `Software\\Google\\Chrome\\NativeMessagingHosts\\th.ac.psu.aiguard.native_host` and the equivalent `Software\\Chromium` key |
| macOS app | `~/Library/Application Support/Google/Chrome/NativeMessagingHosts/`, `Google/ChromeForTesting/NativeMessagingHosts/`, and `Chromium/NativeMessagingHosts/`; manifest points to the absolute adapter inside `Contents/MacOS` |
| Linux DEB | `/etc/opt/chrome/native-messaging-hosts/`, `/etc/opt/chrome_for_testing/native-messaging-hosts/`, and `/etc/chromium/native-messaging-hosts/`; exact `/usr/bin` adapter path |
| Linux AppImage | per-user `~/.config/{google-chrome,google-chrome-for-testing,chromium}/NativeMessagingHosts/`; manifest points to components atomically staged at `${XDG_DATA_HOME:-~/.local/share}/aiguard/native-host-v1/2.5.0/` rather than a transient mount |

Windows NSIS post-install/pre-uninstall hooks and Linux DEB post-install/
pre-remove hooks call the verified manager. macOS app startup repairs its
per-user registration, while transient AppImage startup repairs and stages its
per-user stable package before re-exec. DEB registration is deliberately
package-manager-owned because its discovery files are root-owned; an ordinary
GUI launch does not attempt or claim to repair them. Explicit install/repair/
uninstall modes validate the package shape. Uninstall removes only exact product-owned values/files;
modified or unrelated entries are left untouched and make the operation fail
closed. No elevation-dependent service, systemd unit, or machine daemon is
introduced. Signing/notarization is not claimed.

For AppImage, a Desktop process from the transient runtime first runs the
verified repair/staging path, loads the stable manifest, and re-executes the
manifest-verified stable Desktop. Desktop, adapter, broker, manager, and
backend therefore use one exact stable component root and one package manifest
regardless of which admitted client starts the broker first. Exact-path
admission is not broadened.

The complete AppImage registration/component transaction is serialized by a
private per-version lock: repair holds it through staging and registration;
uninstall holds it through unregister and owned removal. Before
skipping any copy, the manager requires exact bounded source/stable manifest
bytes and re-verifies every source and stable component's digest, direct-child
path, current-user ownership, single link, and exact mode, plus each native
executable's embedded build marker. A fully matching set returns without
renaming any inode, so a live broker remains admissible through
`/proc/<pid>/exe`. Any mismatch takes the existing per-file atomic restaging
path under the same transaction lock, publishes the manifest last, and fully
re-verifies the installed set. Uninstall removes the verified product
components and owned lock only.

Linux packaging preserves the exact frozen Python backend outside the build
tree before linuxdeploy runs. The finalizer requires its PyInstaller archive
cookie, atomically restores it after linuxdeploy, and records the restored
digest in the final component manifest before checksum-pinned repacking. A
missing, stripped, changed, or non-executable preserved backend fails before
candidate replacement.

## Historical local and synthetic-browser evidence

All test data was synthetic. No real PII or AI for Thai credential was used.

| Gate | Result |
|---|---|
| Full Python, credential-free exact-head rerun | 2,631 passed, 9 skipped, 1 dependency deprecation warning |
| Root/Extension JavaScript | 160 passed across 20 files |
| Office JavaScript regression | 129 passed; manifest/typecheck/build green; Office files unchanged |
| Native broker, Windows default | 143 active passed, 10 intentional subprocess-fixture ignores |
| Native broker, Windows all features | 143 active passed, 10 intentional subprocess-fixture ignores |
| Native broker, WSL default/all features | 150 active passed, 10 intentional subprocess-fixture ignores in each run |
| Desktop Rust, Windows default/all features | 20 / 29 passed |
| Desktop Rust, WSL all features | 29 passed |
| Rust formatting and strict all-target/all-feature Clippy | passed on Windows |
| Focused package/identity/registration/smoke/documentation tests | 151 passed, 1 platform-mode skip |
| Deterministic package-smoke marker tests | 9 passed |
| AppImage stable lifecycle regressions | 6 passed: repeated full-set inode preservation, hard-link/mode repair, concurrent first repair, serialized repair/unregister, and owned uninstall cleanup |
| Version/release contracts | 45 passed, 1 dependency deprecation warning; `VERSION` and release-readiness checks green |
| Exact installed Windows NSIS package smoke | CI artifact `9113872467` installed into an isolated per-user root; 2/2 direct-package-layout runs, cold 25,906.728 ms, warm 1,333.507 ms, zero final broker/backend process delta |
| Exact real-Chromium/installed-companion checkpoint | Chromium 145 loaded the 22-file synthetic candidate built from `32e9aa0`; the exact CI NSIS artifact registered 4/4 expected HKCU values, all accepted/wrong-origin and scope/lifecycle assertions passed, uninstall left registration/process delta zero |
| Extension-live Desktop coexistence | the exact installed Desktop joined the Extension-owned broker, completed health/analyze/sanitize/continuation, exited at its fixed local clipboard-copy stage, and the existing Extension mapping restored afterward; exact CI completed that copy/full package path |
| Exact Linux/macOS package smoke | CI DEB cold/warm 3,914.382/1,253.275 ms; AppImage extract-and-run/warm stable run 5,540.346/989.809 ms; relocated macOS app 10,663.424/3,291.828 ms; all registration cleanup and final broker/backend deltas were zero |

Several JavaScript full-suite attempts failed in different background
lifecycle cases while each isolated unchanged rerun passed in 68--116 ms.
Investigation found that real 250 ms reconnect timers from already-completed
worker-module tests survived cleanup and later used the next test's Chrome
mock. The harness now uses fake timers for this file, advances only immediate
tasks, and clears timers after every test. The affected file then passed 15/15
and the then-standard full rerun passed 153/153. Seven later review and
diagnostic regressions bring the final unchanged suite to 160/160. No timeout
was increased and no test was skipped or quarantined.

The first WSL native run and its isolated unchanged rerun failed the audit
request at the existing two-second boundary. Repeating with the repository's
locked Python 3.13 environment proved the interpreter was not the cause.
Inspection found 12,789 existing audit files under the source working
directory; enumerating them through `/mnt/c` exceeded the request boundary.
The real-backend test now owns a unique temporary working/audit directory and
cleans it after backend teardown. The isolated test passed in 4.88 seconds,
then both unchanged full default and all-feature WSL suites passed. Product
timeouts and runtime audit behavior were not changed.

One initial broad Python command inherited a locally configured Tokenmind
environment and attempted one synthetic provider request, which returned HTTP
404. It did not use AI for Thai, print a credential value/body, or produce a
successful provider response. The environment was removed and the complete
credential-free suite was rerun green. This is a known execution mistake, not
installed-Extension capability; it is recorded rather than hidden.

The exact browser-tested synthetic Extension ZIP has 22 runtime entries,
SHA-256
`8e956228559081f453f04c2e63e8a16956adf36404db489682f93d0fdadbe950`,
no test directory, and no forbidden loopback/fetch/credential/backend/session
string. It was built directly from runtime candidate `32e9aa0` with the
explicit acceptance-only synthetic-identity flag, then extracted as the
unpacked Chromium candidate.

Real Chromium acceptance used Chromium 145 (Chrome for Testing), the exact
synthetic public identity, the unpacked 22-file candidate above, and the exact
CI-produced NSIS candidate installed and registered in an isolated per-user
root. The installer was artifact `9113872467` from exact-candidate CI; its
SHA-256 is
`3b509d10bfdad41318394f6469f91fc49e83ee663249fa15b69ab92cebffbaae`.
Registration verification found only the expected product host in the Chrome
and Chromium 32-/64-bit HKCU views. Acceptance verified health without the
Desktop GUI, token and surrogate Mask/Restore, same-scope token reuse,
closed-shadow content Restore with restored values absent from the page DOM,
completed Mask followed by a same-origin hard navigation with the old mapping
rejected and a fresh scope required,
separate side-panel scopes with cross-panel rejection and close-only disposal,
two isolated tabs with cross-tab rejection and close-only disposal, forced
adapter disconnect with Restore/write blocking, empty session storage, and
PII-free reconnect, fresh user Mask recovery, Desktop exit coexistence,
browser restart with empty restore state, and a separately loaded wrong-origin
fixture (`chbjnmlcfdiakcdaljjfhbllmhgadakl`) rejected by the exact accepted
host manifest. The accepted and wrong-origin browser request inventories
contained only nine and eight `chrome-extension://` static-resource requests,
respectively: no HTTP, localhost, loopback, or other network request came from
Extension code. The
adapter opened no TCP listener. The broker's private authenticated transport
remained outside JavaScript. Structural logs/evidence contained no synthetic
PII sentinel or credential value, and the final evidence-file sentinel scan
found zero matches. Browser close allowed
broker-owned idle shutdown with zero installed-candidate process delta. The
NSIS uninstaller returned success, removed its isolated install root and all
four product registration values, left zero product registration/process
delta, and did not remove unrelated state.

The local Desktop package-smoke checkpoint was repeated unchanged twice with
the accepted browser open and once after closing it. Each reached fixed stage
`copy`, then failed closed without leaving a process or registration delta.
The current fixed-error contract intentionally does not expose whether its
internal reidentify-authority or OS clipboard-publication substep failed, so
the local cause was not guessed. The exact same installer completed copy,
restore, PDF, audit, cleanup, and both repetitions in CI. The local fixed-stage
result is therefore recorded as a local UI/clipboard acceptance limitation,
not counted as a full package-smoke pass, and not used to qualify the branch;
the lifecycle checkpoint separately proved that Desktop exit preserved the
Extension mapping.

The 2026-08-11 checkpoint is real-browser runtime evidence, but it is **not**
Web Store installation, production-origin, default-path NSIS installation,
normal AppImage installation, or official distribution evidence. The
isolated-root run did
exercise the normal NSIS install/register/use/uninstall hooks. Local WSL
registration is a layout fixture, not a normal DEB/AppImage install. Exact CI
DEB installation and macOS relocated-app evidence are recorded separately;
relocation/extraction is not normal installed-browser discovery evidence.

## Production-identity closure evidence

Production-identity runtime candidate
`cebf6eb29796797508dc5e4e90c4f85c35b43837` passed the identity-sensitive and
affected gates below. All data was synthetic. No AI for Thai, provider, or
remote-TNER credential was read or used.

| Gate | Result |
|---|---|
| Production identity loader/derivation and package/registration focus | 42 passed; decoded DER digest, derived Item ID, exact origin, classification, and wrong-origin rejection all matched |
| Production Extension package | normal packager with `config/chrome-extension-identity.json`, no synthetic override; 22 runtime entries; SHA-256 `785f94709ab55db6b340f7bff3805edd6057b3118416cd9d68cd9a5ed644d2bd` |
| Production manifest | key derives `kdjmkknedgmfphpkjhjdhmjadaelgggm`; permissions are exactly `storage`, `clipboardWrite`, `sidePanel`, and `nativeMessaging`; no `host_permissions`, loopback, HTTP fallback, backend URL/ID, or credential |
| Native-host manifest | `th.ac.psu.aiguard.native_host`; `allowed_origins` is exactly `chrome-extension://kdjmkknedgmfphpkjhjdhmjadaelgggm/`; no wildcard or synthetic origin |
| Full credential-free Python | 2,636 passed, 9 skipped, 1 dependency deprecation warning |
| Root/Extension JavaScript | 160 passed across 20 files |
| Native broker, Windows default/all features | 144 active passed and 10 intentional subprocess-fixture ignores in each serial rerun |
| Native broker, real WSL default/all features | 151 active passed and 10 intentional subprocess-fixture ignores in each run |
| Desktop Rust, Windows default/all features | 20 / 29 passed |
| Desktop Rust, real WSL all features | 30 passed |
| Formatting/lint/version | Ruff check and format for 239 files; rustfmt; strict all-target/all-feature Clippy; version-drift and release-readiness checks all passed; `VERSION` remained `2.5.0` |
| Production branch CI | [run 31554602630](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31554602630), 14/14 jobs green at exact `cebf6eb` |
| Production cross-platform package smoke | [run 31554602814](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31554602814), 2/2 jobs green at exact `cebf6eb` |
| Windows NSIS artifact | artifact `9125744152`; exact installer SHA-256 `de082a2c399b508b0ddad5cc9c260423cf0cf3d279db2cdc5961836f616b480e`; installed smoke cold/warm 47,727.066/1,092.389 ms; zero broker/backend delta |
| Linux artifacts | artifact `9125743249`; installed DEB cold/warm 3,710.406/1,209.551 ms and finalized AppImage outer/warm 4,666.181/1,472.033 ms; registration cleanup and final native-process deltas zero |
| macOS artifact | artifact `9125689856`; relocated app cold/warm 8,690.667/3,270.020 ms; registration cleanup and final native-process deltas zero |

Real Chromium 145 (Chrome for Testing 145.0.7632.6) loaded the exact extracted
production ZIP and reported
`kdjmkknedgmfphpkjhjdhmjadaelgggm`. The browser source classification was
unpacked. Its runtime request inventory contained only
`chrome-extension://kdjmkknedgmfphpkjhjdhmjadaelgggm/` static resources and no
localhost, loopback, or HTTP request from Extension code.

The exact CI NSIS installer was then installed normally into an isolated per-
user target. Its hooks registered the exact installed manifest in Google
Chrome and Chromium, in both 32- and 64-bit HKCU views. With no Desktop GUI
running, real Chromium discovered the host and passed health, token and
surrogate Mask/Restore, same-scope token reuse, two-tab isolation, side-panel
isolation, content closed-shadow containment, same-origin hard-navigation
invalidation, tab/panel close disposal, forced native-port disconnect with
stale Restore/write blocked, PII-free reconnect, fresh user-Mask recovery, and
browser restart with empty restore authority. Desktop exit preserved the live
Extension mapping; Extension exit preserved the live Desktop and broker. A
separate real-Chromium fixture with origin
`chrome-extension://lbginkmjlpjnjdjbhmidfjebjlnafepl/` was rejected by the
installed host.

The NSIS uninstaller returned zero, removed exactly all four product-owned HKCU
registration values and the isolated install root, preserved unrelated native-
host registry state, and left zero installed adapter/broker/backend/Desktop
process delta. Structural evidence contained no credential or real PII. The
synthetic identity remains only in tests/fixtures and did not occur in a
production ZIP, manifest, registration, or installed artifact.

This closes the production identity and installed-companion gates. It does not
claim Chrome Web Store installation: the owner-approved item remains an
unpublished Draft, and no submission/review/publication action was authorized
or performed. Default-path NSIS installation, normal AppImage FUSE/double-click,
manual updater/upgrade/interruption/stale-cleanup recertification, signing,
notarization, and release publication remain outside Slice 5. Slice 6 has not
started.

## Negative and positive coverage

Deterministic tests cover missing/wrong registration or host name, missing/
wrong/wildcard origin, malformed browser origin/process context, standalone or
wrong-path adapter invocation, component digest/build mismatch, wrong role or
protocol, malformed hello/framing/UTF-8/JSON/fields, duplicate request IDs,
oversized responses, stdout contamination, broker/backend crash and
unavailability, uncertain publication/restore, tab/panel close in flight,
disconnect/restart/navigation/stale response, concurrent/cross-context handle
use, Desktop/Extension coexistence, absence of fallback/loopback permission/
credentials/backend IDs, and sentinel absence from logs/errors/packages.

The positive path crosses service worker → Chrome stdio framing → registered
adapter → broker v1 → shared broker → private authenticated Python backend →
strict operation path → adapter/broker → strict JS validation → content/panel.
It covers health, both sanitize modes, continuation reuse, exact restore, tab
and panel isolation/disposal, connection-loss recovery, and client coexistence.

## Independent review and branch qualification

The first independent security and lifecycle reviews inspected commit
`286dbb01030a3f608f71897a5a73ebb36da97002`. They reported no P0, but found
three P1 defects: a same-origin replacement document retained the prior scope,
Extension packaging followed an out-of-tree symlink, and transient AppImage
Desktop could disagree with the registered stable component root. They also
found one P2 stale locale claim about remote TNER. The candidate now disposes
on every document change, rejects links/reparse points and replacement races
before packaging, re-executes transient AppImage Desktop from the verified
stable package, and states the exact local-`thainer` installed boundary in both
locales.

The same independent reviewers then inspected
`a417374de47069af5749bb4786f46283f704976f`. They found no P0 and reported one
security P1: a hard-linked Extension package input could still escape source
confinement. They also reported bounded P2 lifecycle gaps: a stale sanitize
could open an orphan scope, content health recovery stopped after its first
backoff window, and Extension-first broker ownership lacked a direct
coexistence regression. Later exact-head rounds found no P0 and confirmed one
additional P1: legitimate fixed broker errors outside the Extension's partial
allowlist could remove the active resolver before validation and leave the
operation unsettled. P2 findings covered stale native/HTTP documentation and
atomic AppImage smoke-marker publication/ownership races.

Checkpoint `06c8b34a266550ce2f00b59551ca9ef55ce33aa5` closes those findings. Extension
packaging rejects links, reparse points, and multiply linked inputs before and
during reads. Deferred scope work rechecks tab/panel authority and tears down
uncertain connections. PII-free health recovery uses bounded exponential
delay capped at 30 seconds. Fixed broker errors are complete for protocol v1,
validated before resolver deletion, and settle the current request before any
required teardown. AppImage diagnostics publish complete value-free markers
atomically through invocation-owned temporary files, and package smoke writes
evidence only to a private mode-0700 root outside immutable installed package
trees. The final marker regression deterministically opens two distinct
writer-owned pending files before either publication, proves the losing writer
cannot remove the winner's file, and leaves no pending artifact. Extension-
first single-broker/Desktop-join coexistence has a direct regression. Focused
and complete affected gates pass without increasing a timeout.

A prior branch CI failure was traced to broad packaged-sidecar discovery
treating the new adapter/manager as extra backends;
`571433659127198449017748370b51f44c2e555c` made discovery manifest-aware and
the unchanged full CI rerun passed. Checkpoint
`dce3d5cc4bbf93c131dd4a4cbf9051c59922df0c` then passed all 14 jobs in
[branch CI run 31504224781](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31504224781),
including installed Windows NSIS smoke and native runtime jobs on Windows,
Linux, and macOS. Its cross-platform run exposed a real AppImage defect after
the DEB and relocated macOS paths had passed: linuxdeploy left only the small
PyInstaller bootloader in the AppDir, so the backend exited before the fixed
`app_ready` marker. Inspection confirmed the preserved pre-linuxdeploy backend
still contained the frozen archive while the packaged copy did not. Candidate
`cdeae765f65293f37da96bdd235585a1c0fd140e` added the fail-closed preservation,
restoration, and manifest-attestation contract described above. Its first CI
run rejected one needless borrow under Linux strict Clippy; exact candidate
`0d300793b76011519e303e5286e0a4dcf4f3a1fe` contains only that one-line Clippy
correction on top. Local all-target/all-feature Clippy and all 29 Desktop tests
then passed unchanged. Candidate
`06c8b34a266550ce2f00b59551ca9ef55ce33aa5` adds only a feature-gated,
payload-free health probe when packaged Desktop app-readiness is false. A
persistent health failure is now distinguished as fixed stage `health`; a
healthy native path retains fixed stage `app_ready`. Private errors are
discarded, no production path changes, and the existing runner deadline and
teardown remain authoritative. The complete JavaScript suite passed 160/160.

Its [branch CI run 31516165392](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31516165392)
passed all 14 jobs. The matching
[cross-platform run 31516165371](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31516165371)
passed relocated macOS and installed DEB smoke, but both the original AppImage
job and its clean unchanged rerun failed at fixed stage `health` during the
second AppImage repetition.

Independent diagnosis confirmed a P1 package/lifecycle defect: every transient
AppImage startup repaired the stable set by renaming identical files over the
running broker/backend. Repetition one intentionally left the broker alive for
its broker-owned idle window; repetition two unlinked that live executable
inode. Linux admission then correctly rejected the deleted `/proc/<pid>/exe`
path before protocol use. The failure was deterministic, fixed-value, and
fail-closed; it exposed no payload, mapping, credential, replay, or fallback.

Checkpoint `141e1ed494758c45552076aa16416e73484bf635`
implements the locked, all-or-nothing verified no-copy path described above.
Local Windows default/all-feature suites each passed 143 active tests with 10
intentional fixture ignores; WSL default/all-feature suites each passed 149
active tests with 10 ignores. Its
[CI run 31520617003](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31520617003)
passed all 14 jobs and its
[cross-platform run 31520617034](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31520617034)
passed relocated macOS plus installed DEB and two-repetition AppImage smoke.
Linux-target and host strict Clippy passed. The
five new manager regressions prove stable device/inode identity for every
component and manifest across repeated exact repair, reject linked/wrong-mode
sets from the fast path, serialize concurrent initial repair, and remove only
the owned stable root on uninstall. No admission check or timeout changed.

Exact-object independent reviews then found one shared lifecycle issue, rated
P1 by the lifecycle reviewer and P2 by the security reviewer: staging/removal
held the lock, but registration did not. Concurrent automatic Repair and
explicit Uninstall could therefore both report success while leaving Chrome
registration pointing at a removed adapter.

Runtime/package candidate `32e9aa0048a19a4f3e5ba3130cb59a5663b5da71`
holds the same validated lock across stage+register and
unregister+verified-removal. A channel-controlled regression pauses Repair
inside registration, proves Uninstall cannot enter unregister, then verifies
registration absent and the owned stable root removed. Absent-root uninstall
cleans its temporary owned lock/root; modified or foreign state fails without
deletion; unrelated extra files prevent root deletion rather than being
removed. Exact local Windows all-feature passed 143 active tests with 10
intentional fixture ignores; WSL default/all-feature each passed 150 active
tests with 10 ignores. Both independent exact-head re-reviews report no
remaining P0, P1, or P2. They also reconfirmed origin/process/package
admission, framing/stdout, credential/mapping confinement, no fallback/replay,
tab/panel/MV3 ownership, coexistence, and platform registration behavior.
Dirty acceptance documents and generated output were excluded from their
runtime assurance; the exact runtime CI/package evidence follows.

Exact runtime/package candidate `32e9aa0` passed all 14 jobs in
[branch CI run 31522152257](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31522152257),
including the installed Windows NSIS smoke above and native runtime jobs on
Windows, Ubuntu, and macOS. Windows artifact `9113872467` is the exact installer
used by the final real-Chromium checkpoint. Its matching
[cross-platform run 31522152184](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31522152184)
passed both jobs. Linux artifact `9113800543` contains the installed DEB and
two-repetition AppImage evidence; macOS artifact `9113691215` contains the
relocated-app evidence. All three package artifacts record synthetic identity,
exact registration present/absent transitions, and zero final native-process
delta. A final documentation-only branch head is reported in the closure
report after its own unchanged CI and cross-platform reruns.

Production-identity candidate `cebf6eb` subsequently passed all 14 jobs in
[branch CI run 31554602630](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31554602630)
and both jobs in
[cross-platform run 31554602814](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31554602814).
Artifacts `9125744152`, `9125743249`, and `9125689856` are the exact Windows,
Linux, and macOS candidates described in the production-identity section.

Evidence head `1c637abb5d88d5c0ba6f951a355dee4c62a1e6e5` passed all 14 jobs
in [branch CI run 31556840276](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31556840276)
and both jobs in
[cross-platform run 31556840280](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31556840280).
Independent read-only identity/admission/security and lifecycle/package/
integration reviews on that exact object found no P0 or P1 and no runtime P2.
Both found the same documentation-only P2: four later current-state passages
still described the now-satisfied production identity as absent/open. The
follow-up corrected those passages without changing runtime or package bytes;
an exact follow-up re-review is required before integration.

Slice 6 has not started. No VERSION, tag, release, Office behavior, hosted,
worker-v1, CLI, `aiguard-aift`, thesis, or research-manuscript change is part of
this candidate.
