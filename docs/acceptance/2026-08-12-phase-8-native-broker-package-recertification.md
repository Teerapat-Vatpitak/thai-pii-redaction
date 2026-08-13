# Phase 8 Slice 6 — native-broker package and lifecycle recertification

Date: 2026-08-12; closure refreshed 2026-08-13
Status: **replacement source in local validation; closed only when one exact reviewed tree is integrated through the protocol below**
Source branch: `codex/phase-8-native-broker-package-recertification` (deleted only after verified integration)
Recovered baseline: `a6318d8a118ebe364d4506c1bd9b3e8f2079ff88`
Pre-final local executable checkpoint: `d1ee42557c2b620d37a07504aea9e33047599746`
Baseline main CI: run `31558663610`, 14/14 jobs passed
Baseline cross-platform smoke: run `31558663632`, 2/2 jobs passed
Product version: `2.5.0`
Latest tag: `v2.5.0`

This record keeps source, extracted, relocated, installed, normal-launch, and
official-platform evidence separate. All runtime examples and tests use only
synthetic PII. The Chrome Web Store item remains Draft and unpublished.

The immutable final branch and integrated-main SHAs, three read-only review
results, and GitHub workflow run IDs are reported in the Slice 6 closure
handoff. They are deliberately not inserted into this commit: changing this
record after those gates would create a different, unreviewed head. This record
may reach `main` only after all three exact-head reviews, branch CI and cross-
platform smoke are green and the reviewed branch tree equals the squash commit
tree. Branch deletion requires green post-main CI/smoke plus local/origin/remote
main equality.

## Phase A package and lifecycle inventory

The inventory below describes the exact post-Slice-5 baseline before Slice 6
runtime changes. A row marked source or prior installed evidence is not a new
Slice 6 pass.

### Windows NSIS

| Item | Owner and exact path | Permissions and lifetime | Update and cleanup authority | Baseline evidence class |
|---|---|---|---|---|
| Installer root | Per-user Desktop companion; NSIS default is `%LOCALAPPDATA%\AI Guard`, while prior Slice 5 CI also used an explicit isolated `$INSTDIR` | Inherited per-user directory ACL; package lifetime | NSIS owns replacement and removal | Pre-final `d1ee425` passed the normal default-path lifecycle locally; exact-head branch CI supplies the clean-runner final-artifact gate |
| Desktop | Companion; `$INSTDIR\desktop.exe` | Installed executable; process lifetime | NSIS replaces/removes; Desktop owns only its UI/hotkey broker scopes | Installed isolated-root cold/warm smoke |
| Broker | Companion; `$INSTDIR\aiguard-native-broker.exe` | On-demand per-logon process | Package replacement; broker owns idle/backend shutdown | Installed isolated-root runtime smoke |
| Chrome adapter | Companion; `$INSTDIR\aiguard-chrome-native-host.exe` | Chrome-started stdio process | Package replacement/removal | Installed real-Chromium native-host evidence |
| Native-host manager | Companion; `$INSTDIR\aiguard-native-host-manager.exe` | Non-interactive maintenance executable | NSIS hooks invoke install/uninstall registration operations | Source plus installed hook evidence; pre-replacement drain absent at baseline |
| Component manifest | Companion; `$INSTDIR\native-components-v1.json` | Package file; exact paths, build IDs, and SHA-256 digests | Generated from final bundle inputs and replaced by NSIS | Exact installed manifest evidence |
| Python backend | Companion; `$INSTDIR\aiguard.exe` | Broker-only child in a kill-on-close Job Object | Broker terminates; NSIS replaces/removes after process exit | Installed broker/backend smoke |
| Browser host manifest | Companion; `$INSTDIR\th.ac.psu.aiguard.native_host.json` | Product-owned file with one exact origin and adapter path | Manager writes/removes exact bytes | Installed registration evidence |
| Chrome/Chromium registration | Companion; HKCU 32- and 64-bit views at `Software\Google\Chrome\NativeMessagingHosts\th.ac.psu.aiguard.native_host` and the Chromium equivalent | Current-user registry values; package lifetime | Manager overwrites on install/repair and removes only the exact expected value | Installed four-value registration/uninstall evidence |
| Broker endpoint | Broker; install-independent `\\.\pipe\AI-Guard-Native-Broker-<logon-hash>` plus `Local\AI-Guard-Native-Broker-<logon-hash>` mutex | Current-logon-SID-only kernel objects; broker lifetime | Broker/OS handle teardown; no filesystem cleanup | Windows native boundary tests |
| Updater | Desktop Tauri updater; fixed GitHub release metadata endpoint | Rust-side HTTPS/signature path; no JavaScript credential | Tauri verifies the downloaded artifact; the launched NSIS owns drain/replacement | Source/dependency contract plus exact direct NSIS lifecycle; no public updater asset was installed |

Baseline NSIS hooks run manager `install nsis` after installation and manager
`uninstall nsis` before removal. They do not request maintenance drain before
component replacement at this baseline.

### macOS app bundle

| Item | Owner and exact path | Permissions and lifetime | Update and cleanup authority | Baseline evidence class |
|---|---|---|---|---|
| App bundle | Desktop companion; `AI Guard.app` at the user-selected location | Bundle lifetime; existing signing/notarization status unchanged | User or external package owner replaces/removes the bundle | Relocated exact app, not installation/notarization |
| Native component set | Companion; `AI Guard.app/Contents/MacOS/{desktop,aiguard-native-broker,aiguard-chrome-native-host,aiguard-native-host-manager,aiguard,native-components-v1.json}` | Executables plus read-only manifest under the bundle owner | Bundle replacement/removal | Relocated exact-bundle component smoke |
| Browser registration | Companion; `~/Library/Application Support/{Google/Chrome,Google/ChromeForTesting,Chromium}/NativeMessagingHosts/th.ac.psu.aiguard.native_host.json` | Per-user files; absolute adapter path | Manager install/repair/uninstall | Relocated registration and cleanup evidence |
| Broker endpoint | Broker; `/tmp/aiguard-native-broker-<uid>-v1/{broker.lock,broker.sock}` | Directory `0700`, lock/socket `0600`, current UID; socket is broker-lived while directory/lock persist | Broker removes its owned socket; no baseline uninstall removal of directory/lock | macOS native runtime CI |
| Backend supervision | Broker process group plus parent-death enforcement | Broker/backend lifetime | Broker shutdown or OS parent death | macOS native runtime CI |
| Relocation | User plus manager repair; registration changes to the relocated absolute adapter | Supported only after complete component verification | Manager repair updates exact per-user manifests | Relocated app evidence |
| Update/uninstall | In-app update is disabled; a user or external package owner replaces/removes the bundle after explicit unregister | Package/user lifetime | User/external package owner plus manager registration repair | Relocation, registration repair, runtime, and cleanup only; no real bundle update, signing, or notarization |

### Linux DEB

| Item | Owner and exact path | Permissions and lifetime | Update and cleanup authority | Baseline evidence class |
|---|---|---|---|---|
| Package set | Debian package; `/usr/bin/{desktop,aiguard-native-broker,aiguard-chrome-native-host,aiguard-native-host-manager,aiguard,native-components-v1.json}` | Root-owned package files, executables normally `0755`, manifest `0644` | `dpkg` replacement/removal | Extracted DEB smoke only at baseline, not package-manager install |
| Browser registration | Debian package; `/etc/{opt/chrome,opt/chrome_for_testing,chromium}/native-messaging-hosts/th.ac.psu.aiguard.native_host.json` | Root-owned system discovery files | `postinst` manager `repair deb`; `prerm` manager `uninstall deb` | Extracted-layout fixture; real package-manager path open |
| Broker endpoint | Broker; `/tmp/aiguard-native-broker-<uid>-v1/{broker.lock,broker.sock}` | Directory `0700`, lock/socket `0600`, current UID | Broker socket cleanup; no baseline package removal of directory/lock | Linux/WSL native boundary tests |
| Backend supervision | Broker process group plus Linux parent-death signal | Broker/backend lifetime | Broker shutdown or OS parent death | Linux/WSL native boundary tests |
| Repair/update | Debian package manager plus `postinst` registration repair | Package transaction lifetime | `dpkg` and package scripts | Real install/upgrade/interruption open |
| Removal | `prerm` unregister followed by package removal | Package lifetime | `dpkg` | Real removal/process/runtime cleanup open |

### Linux AppImage

| Item | Owner and exact path | Permissions and lifetime | Update and cleanup authority | Baseline evidence class |
|---|---|---|---|---|
| Outer image | User; user-selected `*.AppImage` | Executable file; user-managed lifetime | User replaces the outer image; in-app update is disabled | Finalized outer `--appimage-extract-and-run`; normal FUSE remains a separate evidence class |
| Transient component set | AppImage runtime; transient `APPDIR/usr/bin/{desktop,aiguard-native-broker,aiguard-chrome-native-host,aiguard-native-host-manager,aiguard,native-components-v1.json}` | Mounted/extracted image lifetime | AppImage runtime only | Exact extracted layout plus outer execution |
| Stable component set | Companion manager; `${XDG_DATA_HOME:-~/.local/share}/aiguard/native-host-v1/2.5.0/` with the same six files | User-owned directories `0700`, executables `0755`, manifest `0644`, repair lock `0600` | Manager manifest-last staging, repair, unregister, and owned removal | Stable cold/warm and repair transaction tests |
| Browser registration | Companion; `${XDG_CONFIG_HOME:-~/.config}/{google-chrome,google-chrome-for-testing,chromium}/NativeMessagingHosts/th.ac.psu.aiguard.native_host.json` | Per-user `0644` files with stable absolute adapter path | Manager install/repair/uninstall | Outer/stable registration cleanup smoke |
| Stable re-exec | Stable Desktop from the verified component root | Desktop re-execs after transient repair; stable process lifetime | Desktop bootstrap plus manager | Outer then verified warm `AppRun` evidence |
| Broker endpoint | Broker; `/tmp/aiguard-native-broker-<uid>-v1/{broker.lock,broker.sock}` | Directory `0700`, lock/socket `0600`, current UID | Broker socket cleanup; no baseline uninstall removal of directory/lock | Linux native runtime tests |
| Repair transaction | Manager plus `.component-repair-v1.lock` | One serialized current-user transaction; components copied atomically and manifest published last | Manager | Deterministic exact-repair/concurrent-first-start tests |
| Uninstall | Explicit `--unregister-native-host` path | User action; no system daemon | Manager removes exact registration and current owned stable root | Prior exact current-root cleanup test; broader stale/update cleanup open |

The AppImage evidence classes remain distinct: extracted layout, finalized
outer `--appimage-extract-and-run`, verified warm stable `AppRun`, and normal
FUSE launch are not interchangeable.

## Baseline gap classification

- Package registration and AppImage same-set repair are implemented.
- The maintenance role already has only health and global drain/stop protocol
  authority, but package replacement hooks do not yet use it end to end.
- A partially replaced set can fail individual executable admission, but the
  baseline does not require complete-set digest/permission verification before
  every installed native runtime starts.
- Unix broker socket cleanup is safe, but the owned runtime directory and lock
  remain after uninstall.
- The Windows updater configuration retains Tauri signature verification and
  hands verified bytes to NSIS, but no public broker-enabled updater asset has
  been installed. In-app update is disabled before updater access on macOS,
  DEB, and AppImage.
- Default-path current NSIS, real DEB install/removal, normal AppImage FUSE,
  macOS real update, signing/notarization, and Web Store installation remain
  unclaimed until exact evidence says otherwise.

## Fixed boundaries

Office remains outside broker v1. Installed Desktop and Extension remain
credential-free: local `thainer`, with `fake` only for internal conformance.
There is no provider/TNER credential store, no HTTP fallback, no production
loopback permission, no release/version/tag work, and no Web Store submission
or publication in this slice.

## Slice 6 implementation boundary

The candidate does not change broker protocol v1 or any storefront/provider
contract. It hardens the installed component and lifecycle boundary:

- `native-components-v1.json` must describe one broker, one backend, and
  exactly three clients: `desktop`, `chrome-native-host`, and
  `native-host-manager`, with the fixed data roles `desktop`, `extension`, and
  `maintenance`;
- each fixed relative file name, SHA-256 digest, owner, executable/manifest
  mode, link count, and symbolic/reparse state is verified. The Rust broker and
  client executables also carry verified embedded build markers; the frozen
  Python backend is bound by its fixed component ID, name, digest, manifest
  build ID, and file identity rather than an embedded Rust marker. The identity
  of the already-opened executable is rechecked before use;
- mixed, missing, duplicate, unexpected-manifest, modified, linked, wrongly
  owned, permissive, stale, or partially published sets fail before PII work
  with a fixed value-free failure and no fallback executable;
- a fixed `.aiguard-component-maintenance-v1` barrier is itself verified for
  owner, mode, links, and exact bytes. It blocks new Desktop/Extension
  admission before replacement. Broker startup holds the endpoint reservation
  while it verifies the barrier and complete set, and live broker/adapter paths
  recheck the barrier at admission and response boundaries;
- only the complete-set-admitted maintenance executable may request drain. It
  cannot open a data scope, sanitize, restore, inspect a handle, or receive
  storefront authority;
- drain stops admissions, cancels or boundedly terminates in-flight work
  without replay, disposes known sessions, tears down the backend on
  uncertainty, closes the broker endpoint, and invalidates all handles;
- replacement never writes a mapping/session file. A new broker gets new
  private backend credentials and empty scope/session state;
- Windows NSIS and external Linux `dpkg` replacement, plus AppImage stable
  component staging, use drain-before-replacement. macOS relocation repair
  does not replace components: it verifies the relocated complete set and
  repairs exact per-user registration. A failed updater install leaves the
  verified maintenance barrier active and discovery isolated rather than
  claiming registration repair;
- AppImage stable repair uses one owned private component transaction lease,
  atomic component staging, manifest-last publication, deterministic same- and
  cross-version recovery, strict old-product registration isolation, and
  removal of only verified inactive owned roots. Ordinary repair/unregister
  cannot consume another live component transaction;
- in-app macOS, DEB, and AppImage update is explicitly unsupported before
  updater access. DEB cannot update in app because an unprivileged Desktop
  cannot own the root package transaction and a synchronous `dpkg` install
  would wait on its own GUI process; the pinned macOS/AppImage updater does not
  provide the package-independent atomic lifecycle required here. The
  supported paths are Windows NSIS, external `dpkg`, user-managed AppImage
  replacement followed by stable repair, and user-managed macOS bundle
  replacement/relocation followed by registration repair; and
- Unix stale endpoint cleanup rejects wrong-owner, permissive, linked, replaced,
  or live runtime state. DEB removal enumerates per-user runtime roots only
  under the exact product prefix and removes them only after inactive ownership
  proof.

## Deterministic compatibility and failure evidence

The pre-final checkpoint and affected final source were tested at different
heads and remain separate:

| Platform | Default | All features |
|---|---:|---:|
| Final Windows closure source | 167 active passed; 14 invoked subprocess fixtures ignored | 167 active passed; 14 invoked subprocess fixtures ignored |
| Pre-final `d1ee425` real WSL2 Ubuntu | 186 active passed; 14 invoked subprocess fixtures ignored | 186 active passed; 14 invoked subprocess fixtures ignored |

Together the matrix covers strict component matching, OS-specific
owner/mode/link checks, explicit protocol-set intersection, least-authority
maintenance, storefront drain rejection, byte-exact barrier validation,
startup/live-admission races, stale endpoint cleanup, live Desktop plus
Extension drain/restart, and in-flight detect/sanitize/restore cancellation
without replay or old-handle revival. The AppImage manager unit path
additionally covers cold staging, exact repair, concurrent first start,
same-/cross-version migration, foreign registration refusal, inherited update
lease exclusion, interruption before and after manifest publication,
post-registration retry, crash-left temporary/partial sets, stale roots,
live-inode refusal, and direct owned uninstall cleanup.

At the earlier PowerShell candidate, package/workflow tests passed 116 with one
expected Windows skip for a Unix-only mode assertion. That result predates and
does not cover the later two-phase DEB smoke-harness changes; the current
affected selection is recorded below. Those earlier tests validated the NSIS/
DEB hooks and `dpkg` workflow at that source state, default-path Windows
lifecycle,
relocation repair, separate AppImage outer/extract/warm/FUSE classifications,
deterministic predecessor upgrade, registration cleanup, and no evidence-class
promotion. Workflow YAML and all four DEB shell scripts parse successfully.

Pinned dependency and source-order assertions establish that Windows downloads
and verifies the signed artifact before handing it to NSIS; NSIS then owns the
serialized drain/replacement transaction. This is source/dependency-contract
evidence plus direct exact-NSIS lifecycle evidence, not a public updater
install: no authorized release asset/channel was exercised. macOS, DEB, and
AppImage reject update check/install before updater access. No tag, release
endpoint, or signature policy changed.

## Windows default-path root cause and exact repair

The first clean reproduction ran the pre-final `d1ee425` installer with the ordinary
silent `/S` argument while a prior Slice 6 custom-root product registration was
still remembered. Tauri's generated NSIS `RestorePreviousInstallLocation`
reads `HKCU\Software\Teerapat Vatpitak\AI Guard` and assigns that value to
`$INSTDIR`; `/S` does not force the default path. The installer returned zero,
correctly refreshed the complete custom-root candidate, and left the absent
default directory absent. The harness then reported the default installed set
as incomplete.

The original defect was therefore a harness/precondition error interacting with stale
product-owned install-location state from the prior custom-root Slice 6 run. It
was not a missing component, incorrect filename/path, architecture difference,
or NSIS payload defect, and it was not caused by the three
preserved July payload files. The CI lifecycle now rejects an existing product
uninstall registration or a remembered non-default root before installation,
then requires both the published uninstall `InstallLocation` and remembered
root to equal `%LOCALAPPDATA%\AI Guard` after every installer invocation.
Focused regression tests pin those checks. The component/digest assertion was
not weakened.

First-principles reruns subsequently confirmed and repaired separate lifecycle
defects without weakening that inventory check: the embedded Windows drain
script used a .NET API absent from Windows PowerShell 5.1; extended-length CIM
paths were not normalized for exact comparison; legacy exact package processes
could remain mapped after launcher isolation; and the uninstaller reset its
working directory to `$INSTDIR` before trying to remove that root. The final
hook passes paths through environment data, uses Windows PowerShell-compatible
drive/UNC checks, normalizes only the `\\?\` prefix, stops only exact validated
package paths within the fixed wall-clock deadline, keeps interruption state
fail closed, and changes to `$PLUGINSDIR` before strict root removal. Focused
contract tests prevent each false assumption from returning.

Recovery also found two clean-runner races at preserved branch head
`283e9c0491b5611472bcda658020958d272fdf0f`. CI run `31654584324` and cross-
platform smoke run `31654584242` were red. Linux exposed the broker completing
barrier-driven shutdown between maintenance connection and response; Windows
installed NSIS exposed repeated unfiltered process enumeration consuming the
fixed drain deadline. The subsequent candidate drops the maintenance client
before inactivity proof, reconciles only `broker_unavailable` or
`operation_timeout` after bounded exact endpoint inactivity, keeps authorization
failures and other errors fail closed, and filters process enumeration to the five fixed
package executable names before the existing exact-path check. The one Windows
adapter exit-code
failure did not reproduce in 20 consecutive exact focused runs and required no
contract change; exact-head CI remained the mandatory disposition. Independent
reviews then found and closed three more defects: AppImage replacement now
reaches the admitted maintenance drain instead of always using inactive-endpoint
fallback; extended `\\?\UNC\` process paths normalize to their ordinary UNC
form before exact comparison; and Windows package transactions use one
exclusive per-user product file lock shared across supported install roots and
console/RDP sessions instead of a session-local mutex. The lock lives under the
user's Local AppData boundary, is non-inheritable, and is deleted on close.
Final review then closed fresh-process recovery: a new NSIS installer reloads
an exact retained receipt through the admitted replacement manager, a repeated
NSIS uninstaller validates its retained marker/receipt before resuming exact
registration and launcher cleanup, and repeated DEB `prerm` resumes a partially
unlinked set only after exact root-owned marker/receipt and absent-registration
proof. The Windows fixture now creates copied executables with destination-owned
files. A pre-request transient maintenance connection failure is retried only
while exact endpoint ownership proves the broker remains active; only an
unavailable or timed-out response after the one drain request may use bounded
inactive-endpoint reconciliation. The fixed drain script executes end to end
under Windows PowerShell 5.1 and does not rely on PowerShell 7-only generic-
method syntax.

Preserved head `136c97406dcc13f4ae98ff8d433d92fba2e02412` was then invalidated by
CI run `31663171457` and cross-platform smoke run `31663171424`. The confirmed
code-side failures were narrow: the Windows binary fixtures did not explicitly
set destination ownership after copying; the live-upgrade harness published its
release marker at the final path before all bytes were written; the PowerShell
receipt check did not require one exact 65-byte lower-hex-plus-LF representation;
and the Linux Slice 6 fixture used a 30-second signal wait and 40-second parent
wait around a 30-second drain operation, leaving no realistic process-start or
scheduling margin. The recovered source sets ownership on every copied Slice 5
and Slice 6 fixture component and manifest without relaxing production admission,
publishes a fully written and flushed pending release
marker through one no-clobber filesystem link, accepts only the exact receipt
representation, and makes the finite deadline hierarchy explicit: 45 seconds for
drain, 55 seconds for the enclosing child exit, and 75 seconds for live fixture
signals. The actual Windows PowerShell 5.1 regression accepts the valid receipt
and rejects uppercase, extra-LF, CRLF, NUL, and hard-linked variants. Both
Windows fixture-ownership regressions passed ten consecutive focused runs, the
strengthened atomic marker regression passed ten, and the focused Linux
lifecycle passed three consecutive real-WSL
runs in 29.19, 26.84, and 28.58 seconds. The separate Tauri NSIS download
failure in run `31663171457` was `io: Peer disconnected` while fetching the pinned tool;
it remains an external failure, not a code pass, and must be replaced by a green
exact-head package job.

Replacement head `70a34257c5008787ba4adcb62a45cbd2f514216d`, tree
`d5ae0136c117e7871b574054674f641ce2f8fede`, was also invalidated. CI run
`31668314033` produced one deterministic Windows native-runtime failure because
the separate Slice 6 full-package fixture still inherited copied-file ownership;
the other long jobs and cross-platform smoke run `31668314041` were cancelled
after review found that defect. The same review found PowerShell's ordinary
`-notmatch` to be case-insensitive, so uppercase hex was not yet rejected, and
found that the live DEB harness incorrectly expected the drained, unlinked old
Desktop to complete the new package's workflow. The recovered source uses
case-sensitive receipt matching, sets all Slice 6 fixture owners, and separates
DEB upgrade evidence into two bounded phases. The old Desktop first holds a
synthetic session and must publish fixed invalidation evidence without reviving
that session; after it exits and native processes return to baseline, the harness
re-reads the installed manifest and launches the new Desktop for the complete
smoke. The 60-second `dpkg` operation is nested inside a 90-second child release
wait and a 120-second old-process envelope. Neither cancelled run is closure
evidence.

Replacement head `2b914568baf6bda7c359dd271d6fb6b25035d702`, tree
`2937fd30f23129b74be94162dab37adbff7365c5`, was invalidated before its
workflows completed. Independent review found that its two-phase DEB harness
could label the old session invalidated without requiring the second held-
session operation to carry the structured invalidation flag. CI run
`31671305719` and cross-platform smoke run `31671305777` were cancelled and do
not count as evidence. Head `b4565e07345668aeecffc92d31ec768b92ace1ce`, tree
`6b9cd12e78828d4c07cf9fd55535c64a52fd14ba`, closed that assertion gap and
passed all three read-only reviews, but exact-head execution found three more
deterministic failures and invalidated those reviews. CI run `31672034114`
passed 12 of 14 jobs but failed Ubuntu native runtime and Windows installed
package smoke; cross-platform run `31672034062` passed macOS and failed Ubuntu
before package construction. The Ubuntu Slice 4 runtime observed the documented
nonterminal `broker_busy` during supported-client startup after a rejected
remote-TNER attach. The Ubuntu Slice 6 fixture spent its five-second control
deadline re-attesting the large copied component set, then incorrectly treated
the pre-request connection failure as an ambiguous drain response. The Windows
installed-package artifact retained only the exact 33-byte maintenance marker
after cleanup. It did not preserve the failing phase or ACL, so the initial
elevated-owner explanation remained an inference rather than evidence.

The current source handles `broker_busy` through the existing bounded readiness
helper; prepares the strict maintenance client once, starts each control
handshake after preparation within one enclosing deadline, retries only pre-
request transient connection failures while the endpoint proves active, and
reserves inactive reconciliation for the single drain request. The marker-only,
no-receipt bootstrap state is shape/content/link validated before any existing
owner-normalization path runs and is then fully revalidated. Receipt-bearing
state is never normalized and retains strict owner, exact-byte, hard-link, and
reparse rejection. These corrections are locally green but require a new
immutable exact-head review and workflow replacement; no result above is
promoted to closure evidence.

Candidate `4efbdfbd21a536588611f3f5548695014f34be82`, tree
`efa2204b0aa8eda77bac0f2cca02a9e81fd68648`, was invalidated by final
correctness review. Although connection attempts were bounded by the enclosing
drain deadline, a late successful connection gave the maintenance request a new
five-second window, and a pre-request `operation_timeout` was not retried while
the endpoint still proved active. CI run `31692622432` was cancelled after 13
of 14 jobs passed; only the Windows installed-package job was cancelled.
Cross-platform smoke run `31692622444` was cancelled with both jobs cancelled.
These successful partial jobs are historical evidence for the invalidated tree
only, and neither workflow counts as closure evidence. The current source
threads one absolute deadline through preparation, bounded connection/hello
attempts, the single maintenance request, and final inactivity proof. A pre-
request unavailable, busy, or operation timeout is retried only while exact
endpoint ownership still proves the broker active; authorization and protocol
failures remain immediate, and post-request reconciliation remains limited to
the fixed ambiguous shutdown errors.

Candidate `854b6aba84cd7728cb0801fe4ed24b5cd206f783`, tree
`0fdb509f612e48a55c36553d4e435ae74c32707c`, was also invalidated. CI run
`31694499510` passed 13 of 14 jobs and failed only Windows installed-package
job `94429059178`; post-cleanup artifact `9179069030` retained the exact
33-byte maintenance marker and no product registration. Cross-platform smoke
run `31694499478` passed macOS job `94429058870` and failed Ubuntu job
`94429058749`. The Ubuntu log reached the post-DEB-reinstall Desktop launch,
but no later phase marker or Linux artifact was preserved, so that run does not
prove which later command exited. Neither failed workflow is closure evidence.

Local recovery reproduced a real marker-only failure before payload extraction,
but the post-cleanup hosted artifact did not itself locate that phase. In the
local reproduction, the embedded Windows PowerShell 5.1 script parsed its root,
then `Add-Type` resolved the native NSIS `$PLUGINSDIR\System.dll` as a .NET
metadata reference because NSIS also used that directory as the child working
directory. The helper therefore never loaded. A focused executable regression
reproduces exit 1 with a native file under the colliding `System.dll` name and
exit 0 when the same script runs from the install root. The hook now extracts
the fixed script in `$PLUGINSDIR` but changes to `$INSTDIR` before `ExecWait`.
An ordinary local Tauri NSIS candidate, SHA-256
`60a3db6ce6a31b4cf839e42f3245318b12320692dcf9e88ba42802ec97fc4e3f`,
then recovered the preserved interrupted marker, matched all five declared
component digests, passed one packaged smoke, uninstalled cleanly, and left the
pre-existing default root and remembered preference unchanged. This is local
affected-path evidence; the replacement exact-head default-path hosted NSIS
lifecycle remains mandatory.

The Ubuntu source/workflow review found a separate deterministic contract
mismatch even though the failed log lacked its final command. The workflow
required two concurrent AppImage repairs to both succeed, while the production
shared-root lease deliberately rejects an overlapping holder without blocking.
The replacement workflow now holds that exact directory lease, requires the
real manager contender to return fixed status 75 within 60 seconds without
changing the complete stable-root inventory/content fingerprint or registration, releases the
holder within 10 seconds, then requires repair within 120 seconds and full
re-attestation.

Candidate `522358ffb6874edf4ee723a74fcea83557d780c7`, tree
`14765fe0b8ecd1460b13cd6f551e52c983f15d2c`, was invalidated by the
documentation/evidence audit before integration. Correctness/security and
package/deployment reviews passed, but the evidence wording incorrectly claimed
that phase evidence could locate every Linux failure. CI run `31704307547` and
cross-platform smoke run `31704307450` were cancelled on that obsolete head and
do not count as closure evidence. Once the Linux package-layout step reaches
phase-tracker initialization, its `always()` artifact step is configured to
upload the latest-started coarse phase and any value-free partial evidence. The
marker does not prove that the phase completed or identify its exact failing
command, and no phase artifact is guaranteed for an earlier failure or runner
loss that prevents upload.

Replacement candidate `ea8eb7725bf6d31a95e4db03f99bca6bf46ef2e2`, tree
`067a88e8ae9884de68621668d14efffb20b3d414`, passed all three independent
read-only reviews and was then invalidated by exact-head execution. CI run
`31705549161` passed 13 of 14 jobs and failed only Windows installed-package
job `94465065578`. Artifact `9183413143` records installer SHA-256
`be4ea6b030d79b772fd74d204f82dcc70dd8ddbb7d342bc01843ed0c44bd2413`, lifecycle
phases `clean-install` and `final-cleanup`, a failed primary operation, failed
uninstall cleanup, absent native/uninstall registration, the retained default-
path preference, and a residual exact maintenance marker plus the full five-
executable payload, component manifest, and uninstaller. It does not preserve
the failing subcommand or file ACLs, so it cannot directly prove an owner SID
or exact API failure. Cross-platform run `31705549230` passed macOS job
`94465065913` and failed Ubuntu job `94465065907`. Artifact `9183764469`
records `deb-interrupted-remove-recovery` as the latest-started coarse phase;
it also preserves completed initial DEB install/smoke, two-phase live upgrade,
remove, reinstall, and reinstall-smoke evidence. It contains no AppImage
evidence and does not identify the exact failing command or prove that the
coarse phase completed. Neither failed workflow counts as closure evidence.

The Windows source-path diagnosis is narrower than the artifact. NSIS extracts
the fixed payload before `NSIS_HOOK_POSTINSTALL`; the manager strictly loads
and verifies the complete manifest before dispatching any post-install action.
The exact installer's five embedded component hashes match its manifest, and
the same manager accepts `capability nsis` after local extraction gives those
files the process user owner. Windows creates files with the process token's
default `TokenOwner`, which can differ from `TokenUser` on an elevated runner,
while ordinary installed admission deliberately requires `TokenUser`. That
owner mismatch is therefore the mechanism-consistent source diagnosis, but
remains an inference for the obsolete artifact because it retained no ACLs.
The repair does not broaden ordinary admission to an administrator group. At
the start of post-install, the actual Windows PowerShell 5.1 helper first
requires the exact current-user marker and, when present, the exact current-
user 65-byte lower-hex receipt. It then opens only the fixed five components,
`native-components-v1.json`, and `uninstall.exe` without reparse traversal or
write/delete sharing; requires every file to be nonempty, regular, and one-
link; permits the bootstrap source owner only when it is exact `TokenUser` or
this process's exact `TokenOwner`; validates every handle before changing any
owner; sets each held handle to `TokenUser`; and rechecks owner, identity,
size, attributes, and link count. Receipt-bearing authority is never
normalized. The unchanged strict manager immediately reopens the component
manifest and verifies schema, fixed paths, build IDs, and component digests
before registration. The exact-head workflow records only the privacy-safe
boolean of whether process `TokenOwner` differs from `TokenUser`, then remains
the authoritative distinct-owner/default-path lifecycle gate.

The Ubuntu failure exposed a separate operation-order bug. The interrupted-
remove harness intentionally unlinks `/usr/bin/desktop` after the admitted
manager has published its removal receipt, then invokes `deb-prerm.sh` to
resume cleanup. The script calls manager `cleanup deb`, but the manager used to
require the complete five-component set before it dispatched cleanup, so it
could not reach the existing incomplete-removal path. Only `cleanup deb` now
uses the existing incomplete-removal manifest loader; it still requires the
strict manifest schema/version/fixed declarations and exact maintenance-
manager path, digest, build marker, mode, owner, link, and same-file identity.
Every other operation and package shape retains complete-set admission. The
workflow now publishes a separate latest-started marker before the manager,
each of the two `prerm` attempts, reinstall, and final removal, and places the
manager plus both retry invocations inside fixed 60-second bounds. These
markers remain coarse start evidence, not completion claims.

Focused current-source evidence is green. Actual Windows PowerShell 5.1
accepts the valid 65-byte lower-hex receipt and fixed payload, preserves every
payload byte, and rejects uppercase, extra-LF, CRLF, NUL, missing/empty,
hard-linked, and reparse variants. This local token has equal `TokenOwner` and
`TokenUser`, so it proves the helper and fail-closed paths but not the hosted
distinct-owner transition. The WSL manager suite passed 22 tests, including
the early-unlink cleanup regression, and the exact Slice 6 WSL target passed
10 active tests with four intentional fixture ignores in 35.11 seconds. A
fresh unsigned local NSIS candidate was 141,116,965 bytes with SHA-256
`17873e96be1d873734525a57df5a530ae6e78b2278cf0364f533140c3de7573b`.
It installed to an isolated Local AppData root, matched all five declared
digests, published four native-host registrations, completed one full
synthetic package smoke in 7,261.872 ms with zero broker/backend process delta,
uninstalled cleanly, and left the pre-existing default installation and
remembered default-root preference unchanged. This is affected-path local
evidence. The later target-gating edit restricts incomplete-manifest dispatch
to Linux `cleanup deb` and does not change the Windows NSIS path, so it does not
invalidate this artifact; exact-head hosted NSIS and Ubuntu package workflows
remain mandatory.

Candidate `097d41d4d7c141f0e001ded1cbb868c0c45ae7d7`, tree
`9d74a768814d18d064da11300de2da0e1428fe48`, then passed independent
correctness/security and package/deployment review but was invalidated by both
exact-head workflows. CI run `31713219318` passed 13 of 14 jobs and failed only
Windows package job `94491279795`. Artifact `9186697047` records installer
SHA-256 `895a419eae07dd59f17cf104b904e4dd7e4769f122ee0f8833d193c8cabe5ca5`,
`token_owner_differs_from_user: true`, exact installed component hashes, four
registrations, and two successful installed Desktop smoke runs. Its lifecycle
reached `clean-install` and `concurrent-transaction-rejected`; primary status
was failed, final cleanup had no failure, registrations were absent, and no
residual default install tree was recorded. This directly proves the owner
bootstrap worked on the distinct-owner hosted path, but the red run is not
closure evidence.

The Windows failure was a false workflow invariant. Tauri's generated NSIS
script executes `SetOutPath $INSTDIR` before the product preinstall hook, so a
blocked custom-root contender can create an empty directory before the shared
product lock rejects it. The workflow incorrectly rejected mere existence. A
local held-lock run of the exact artifact reproduced nonzero exit status plus
an exact empty directory. The production lock remains unchanged. The
replacement requires both default/custom contenders to fail; accepts only an
absent or exact empty, non-reparse synthetic probe directory; rejects every
child or other package state; re-attests installed digests, native-host and
uninstall registration, and the remembered default root; records fixed
value-free contention state; and removes only the reverified-empty synthetic
directory.

Cross-platform run `31713219299` passed macOS job `94491279822` and failed
Ubuntu job `94491280004`. Artifact `9186746050` records the complete DEB
lifecycle, including two-phase live upgrade and interrupted-removal recovery,
plus AppImage registration, fixed lease-contention status 75 with unchanged
state, repair, stable/reinstall smoke, cleanup, and finalized extract-and-run
smoke. Its latest-started phase is `appimage-outer-modes`; the job emitted fixed
failure stage `appimage_repair` only during normal FUSE launch. The empty FUSE
JSON is an output file opened before the program emitted evidence, not a pass.
The pinned AppImage tool makes root-owned SquashFS bytes. A WSL mount of that
exact pinned runtime confirmed normal FUSE exposes UID 0 files on a read-only
mount, whereas extraction creates effective-user-owned files. The manager's
transient staging predicate incorrectly required only the latter.

The AppImage replacement keeps stable publication strictly effective-user-
owned. A transient UID 0 source is accepted only when its directory is the
exact canonical `$APPDIR/usr/bin` topology on a read-only filesystem. The
complete source must still share one owner and device and contain only the
manifest-declared regular, non-symlink, one-link files at exact `0644`/`0755`
modes; existing digest, build-ID, path, and before/after manifest checks remain.
Foreign ownership, writable/spoofed topology, stable UID 0, links, wrong modes,
and modified bytes remain rejected. Focused workflow tests, YAML parsing,
rustfmt, the owner-policy regression, and the updated 22-test WSL manager suite
pass. No timeout increased and normal FUSE was not reclassified as unavailable.
Both `097d` workflows and their partial artifacts remain historical diagnostics
only; a replacement immutable head must pass the full closure protocol.

## Exact local Windows package evidence

The exact unsigned package-smoke NSIS candidate is:

- file: `AI Guard_2.5.0_x64-setup.exe`;
- executable checkpoint: `d1ee42557c2b620d37a07504aea9e33047599746`;
- size: 141,103,791 bytes;
- SHA-256:
  `92b6840b53cbda6ee567a560dea70fbc59e651199391b94260b0797a313d8faa`;
- normal install root: `%LOCALAPPDATA%\AI Guard`; and
- product/file version: `2.5.0`.

The installed component manifest was 1,431 bytes with SHA-256
`c0329881d26e3a195b1876b12ccd0ed8737a15acde9df1e280549c4356c6490a`.
Its exact five executable entries all matched their installed bytes:

| Component | Size (bytes) | Installed SHA-256 |
|---|---:|---|
| `desktop.exe` | 14,735,872 | `2284cac1711a48e3c3f100154c6b68ed3484c25c1dcfc66871b5f9eafe6c5c9f` |
| `aiguard-native-broker.exe` | 973,824 | `d24c48ea2b592797b890d5c4b2bd6a7100eb205ed4ff0078b588603a9cc35498` |
| `aiguard-chrome-native-host.exe` | 830,976 | `e9329fc643ecf13b73918a634c2a1212d2653fa0b37009593fd6bde0759ab58b` |
| `aiguard-native-host-manager.exe` | 659,456 | `69093100c969d10d44d19bba62d71b5825a83d00caf4a8931d7343fda4637ff4` |
| `aiguard.exe` | 137,682,340 | `f593befef5e6f4800900a27c9e12212ffb403e1765da317ff69a531ae2880758` |

The generated native-host manifest was 301 bytes with SHA-256
`43ad4b5d5b0032f0412639d926ea6c9be04b5d3e3df71ce342fc1eab555479b6`.
The uninstaller was 83,934 bytes with SHA-256
`bcb1aa750afa77dcc69f8a2978cb55282aafe4310d28d3b16a2202765033fd64`
and version `2.5.0`.

The exact artifact passed clean default-path install, strict component/digest
verification, registration in both Chrome and Chromium HKCU 32/64-bit views,
Desktop cold/warm package smoke, repair, real pre-Slice-6 predecessor upgrade,
same-candidate upgrade, Extension-only live
upgrade, Desktop-only live upgrade, simultaneous Desktop plus Extension live
upgrade, uninstall, registration/process cleanup, reinstall, and fresh empty
state. Deterministic package/manager regressions separately passed interrupted
post-drain recovery. Every old candidate process observed
before replacement was gone afterward. Old masked text stayed unusable, while a
new backend accepted a fresh user-initiated mask/restore. The cold/warm package
smoke recorded 7,176.899 ms and 1,743.416 ms process elapsed, respectively,
with zero broker/backend process delta; those are operational package timings,
not a performance-baseline change.

The predecessor was the exact baseline artifact from
`a6318d8a118ebe364d4506c1bd9b3e8f2079ff88`: 141,042,221 bytes, SHA-256
`eb5567e8c1eb726e7c1719de1eb7bb82871925a6fb295addfd4ab6c8b7d2815a`.
With its Extension scope live, the pre-final `d1ee425` installer returned zero, removed
every observed predecessor process before replacement, published the complete
candidate, and the fresh backend rejected the old masked text. Separate
deterministic interruption regressions cover receipt/barrier creation,
manifest-last publication, registration failure, and retry without admitting a
partial set; a prior same-source local interruption exercise also retained the
barrier and predecessor bytes until retry. The pre-final `d1ee425` artifact was
not forced into an artificial power-loss window. Exact-head workflows require
fresh package processes to recover strictly validated install/uninstall
receipts and repeated DEB `prerm` to finish a partially unlinked owned set.

After candidate lifecycle completion, the original pre-broker July installation
was restored byte-for-byte at its original default path from the reversible
backup. Its three SHA-256 values matched the pre-run inventory. Slice 6 native
registration remained absent and the final candidate process delta was zero.
The published Apps & Features uninstall key was absent. NSIS intentionally
retained its product-owned remembered install-location preference at the normal
default root; this is classified as retained configuration, not an active
uninstall/native-host registration. No unrelated user file, process, browser
profile, native host, or registry key was removed.

## Real Chrome acceptance

Google Chrome for Testing 145 loaded the exact production-keyed unpacked
candidate and reported Extension ID `kdjmkknedgmfphpkjhjdhmjadaelgggm`. The
installed native host admitted only
`chrome-extension://kdjmkknedgmfphpkjhjdhmjadaelgggm/`. A separately packaged
repository synthetic identity `lbginkmjlpjnjdjbhmidfjebjlnafepl` was rejected:
health and restore stayed unavailable and no extra adapter process started.

The production candidate passed health without the Desktop GUI, token and
synthetic-surrogate sanitize/restore, panel isolation, tab isolation, navigation
invalidation, disposal, disconnect, browser restart with empty session storage,
Desktop coexistence, live-upgrade invalidation, uninstall discovery removal,
reinstall from empty state, and fresh operation afterward. Its browser request
inventory contained only `chrome-extension://` resources; production has no
localhost permission, loopback fetch/fallback, or client TCP listener. No raw
PII, mapping, credential, provider body, or restored answer was persisted in an
acceptance artifact. Generated browser profiles were removed after the run.

This is exact-ID unpacked real-browser evidence, not Chrome Web Store
installation. The Web Store item remains Draft/unpublished and was neither
submitted nor published. The ephemeral archive unpacked for the pre-final
`d1ee425` Chrome/installed-companion run was 295,406 bytes with SHA-256
`aa880855f8a752a205b6a360a24b982cad04faf1df6f41495ff4e223784e8027`.
The separately retained repository archive `dist/aiguard-extension-2.5.0.zip`
is also 295,406 bytes but has SHA-256
`6e75709030c79b3fc0e9c567842efbae2e2ca10dab9fd158fea487c9960200ef`.
ZIP timestamp metadata makes separate packaging runs byte-distinct; the first
digest identifies the archive actually unpacked for this browser run, while the
second identifies the retained file and is not promoted to browser evidence.

The pre-final `d1ee425` Desktop artifact also passed automated native cold/warm and
live-upgrade behavior. A repeated pixel-level manual UI pass was unavailable
because Windows reached the lock screen; UI automation stopped immediately and
did not operate through the lock. This limitation does not replace or weaken
the installed package/runtime assertions.

## Complete local gates

- Python: the earlier complete suite passed 2,641 with 8 expected environment/
  platform skips. The current changes touch only package/workflow contracts and
  their tests; the complete affected Desktop/package/backend Python selection
  collected 124 and produced 121 passes with three expected Windows skips: one
  Unix executable-mode check and two Unix-only `SCM_RIGHTS` checks. No Slice 6 change adds a skip,
  quarantine, or relaxed assertion.
- Root Extension/Desktop JavaScript: 163 passed; syntax checks passed.
- Office regression: 129 passed; manifest, upstream checksum-pinned schema,
  package, typecheck, and production build passed. Office source was unchanged.
- Native broker: current Windows 167 passed/14 expected ignored in both default
  and all-feature configurations; pre-final WSL checkpoint 186 passed/14
  expected ignored in both. The current WSL manager suite passed 22, and the
  current exact Slice 6 Linux target passed 10 active tests with four expected
  fixture ignores in 35.11 seconds inside the unchanged 75-second harness
  bound. Exact-final Linux/macOS/Windows complete behavior remains a branch
  workflow gate rather than an implied local matrix.
- Desktop Rust: the current dependency build passed 21 default and 31 all-
  feature tests.
- Ruff lint and format, rustfmt, strict all-target/all-feature Clippy for both
  Rust manifests, version consistency, release readiness, DEB shell syntax, and
  `git diff --check`: passed.

`pii_redactor/` and `app/` are byte-unchanged from recovered baseline
`a6318d8a118ebe364d4506c1bd9b3e8f2079ff88`, so Slice 6 does not invalidate the
core performance gate. The committed baseline was not moved. Prior controlled
same-state performance evidence remains applicable; installed smoke timing is
reported separately and is not substituted for the core benchmark.

## Closure protocol

Closure requires three independent read-only reviews on the immutable branch
head; exact branch CI including clean-runner default-path Windows lifecycle;
exact branch cross-platform smoke covering relocated macOS repair/cleanup, real
DEB `dpkg` lifecycle, finalized AppImage outer extract-and-run, warm stable
`AppRun`, and normal FUSE only when the runner supports it; squash integration
with reviewed-tree equality; exact post-main CI/cross-platform smoke; main ref
equality; and deletion of only the integrated Slice 6 branch. The closure
handoff supplies the immutable SHAs, workflow run IDs, and review dispositions.

Signing/notarization, Web Store installation/publication, public updater
installation, release creation, and deployment remain outside Slice 6. Office
stays outside broker v1. The installed boundary remains local `thainer`; remote
TNER and credential-requiring providers remain unsupported. The provider-
controlled in-page DOM limitation remains unchanged.
