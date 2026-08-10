# Version, tag, and release process

This process applies to the desktop installers, extension version, API version,
and public GitHub Release. The hosted API contract has its own
`contract_version`; a product release does not automatically break that
contract.

## Sources of truth

- `VERSION` - product version.
- `scripts/_version_targets.py` - every file that must carry the same product
  version.
- `CHANGELOG.md` - human-readable shipped scope.
- immutable Git tag `v<VERSION>` - exact source commit used to build artifacts.
- GitHub Release for that tag - downloadable artifacts, checksums, Tauri updater
  signature files, and attestations. Updater signatures are separate from OS
  code signing; the installers remain unsigned by the accepted distribution
  decision.

Release assets are the distribution surface. The repository carries no package-
manager manifest, so nothing downstream needs a version bump after publication.
The automated tag workflow publishes Desktop artifacts only. The browser
extension remains source/unpacked distribution unless the owner explicitly adds
its zip as a release asset; it is not published to the Chrome Web Store. The
Office add-in is likewise outside the automated GitHub Release asset set.

## Current publication block

This document describes the intended process and preserves the procedure used
for historical releases. It is not currently an instruction to push a new tag.
Every new tag intentionally fails `.github/workflows/release.yml` in the
`release metadata preflight` job before any build or publishing job can run.
That stop remains until Slice 5 packages and registers the Extension Chrome
Native Messaging host against the shared broker and every Slice 6 gate in the
roadmap is complete, including cross-platform package/install, relocation,
updater, upgrade, interrupted-upgrade, stale-cleanup, and uninstall lifecycle
recertification.

`python scripts/check_release_readiness.py` is a metadata-consistency check
only: it verifies synchronized version targets plus the changelog, and with
`--expect-tag` also checks tag identity and an empty `Unreleased` section. A
green result does not certify architecture, security, packages, installed
hosts, signing, notarization, or release readiness, and it does not bypass the
workflow stop above.

Branch CI can build unpublished package candidates and exercise bounded smoke
paths. Those jobs do not create or publish a GitHub Release. Current branch
package commands explicitly use `--no-sign`; macOS app relocation and Linux
package extraction are package-layout evidence, not signing/notarization or a
native installer lifecycle result. Treat every result according to the exact
evidence class recorded for it. A distributable AppImage must pass the
checksum-pinned post-`linuxdeploy` finalizer before smoke, hashing, signing, or
upload. For the pinned no-sign/no-update build, that gate permits only the
single non-executable, non-overlapping 16-byte `.digest_md5` rewrite defined by
appimagetool, requires every other x86-64 ELF64 runtime-prefix byte to match,
then confirms the runtime offset and re-extracts the image to verify the native
components and manifest. The raw Tauri AppImage intentionally carries an
invalid manifest and is not a release candidate. Automated AppImage smoke must
independently attest the extracted bytes, start the exact finalized outer file
with `--appimage-extract-and-run`, re-attest the retained root, and exercise its
verified `AppRun` warm. Record that separately from normal FUSE/double-click,
which this branch gate does not certify.

## Semantic version policy

- **Patch** (`x.y.Z`) - compatible bug/security fixes and operational fixes.
- **Minor** (`x.Y.0`) - additive user-facing capability, new endpoint/operation,
  or a materially new supported integration that preserves existing contracts.
- **Major** (`X.0.0`) - a deliberate breaking change to a supported public
  contract, persisted user data, or installer/update compatibility.

Docs-only commits do not require a tag. Development commits after a release stay
under `Unreleased` until the next release-preparation branch chooses the version.

Published product versions are monotonic and are never reset to `0.1.0` in the
same distribution identity. A separately deployed AI for Thai service may adopt
its own line only after an independent service-version source is implemented;
the current sibling port inherits the product version. See
[the versioning proposal](versioning-proposal.md).

## Release preparation branch

1. Freeze the intended scope, ensure every item meets the roadmap definition of
   done, and confirm that the intentional Slice 5/Slice 6 release-workflow block
   has been removed through reviewed implementation rather than bypassed.
2. Pull the latest `main` and create a short-lived release-preparation branch.
3. Run `python scripts/bump_version.py X.Y.Z` rather than editing version strings.
4. Move the relevant `Unreleased` entries into
   `## [X.Y.Z] - YYYY-MM-DD`; leave a fresh empty `Unreleased` section.
5. Run `python scripts/check_release_readiness.py` as the metadata-only check;
   complete the separate architecture, package, installed-host, security, and
   external gates required by the candidate.
6. Run the full local checks appropriate to the change, push the branch, and
   wait for every GitHub Actions job to pass.
7. Review the diff for installer names, updater configuration, API contract,
   documentation, and the release notes - not only tests.
8. Squash the reviewed branch into `main` as one commit, push `main`, and wait
   for every `main` CI job to pass before tagging.

## Tag and build

The commands below apply only after the current publication block has been
removed and the release-preparation branch is squashed into a green `main`:

```bash
git switch main
git pull --ff-only origin main
git tag -a vX.Y.Z -m "AI Guard vX.Y.Z"
git push origin vX.Y.Z
```

Rules:

- The tag must be placed on the exact reviewed `main` commit.
- Never move, delete/recreate, or reuse a published version tag.
- A failed release is fixed with a new commit and new version, not a retag.
- Do not create the GitHub Release by hand before the tag workflow runs.

The release workflow verifies the tag/version/changelog relationship (including
an empty `Unreleased` section), builds each platform artifact, creates a draft
release, checks a minimum cross-platform asset set, publishes `SHA256SUMS`, and
attaches GitHub build provenance. The automated minimum-set check does not prove
that every updater signature file expected by the current Tauri configuration
is present; that remains a manual publish gate.

## Publish gate

The draft remains unpublished until the maintainer verifies:

- all expected Windows/macOS/Linux assets and every expected updater/signature
  file are present;
- every AppImage was finalized from the post-`linuxdeploy` AppDir and the exact
  finalized file, not the raw Tauri output, was hashed and exercised through
  the recorded outer-AppImage/verified-`AppRun` path;
- the workflow is green on the tag;
- checksums match downloaded artifacts;
- `gh attestation verify` succeeds for representative artifacts;
- release notes match the changelog and make no unsupported claim; and
- an install/launch smoke has passed on the maintainer's primary platform.

Only then publish the draft and mark it Latest. Delete stale duplicate **drafts**
after verifying a published release for that tag already exists; never delete a
published release as routine cleanup.

## After publication

1. Verify README's Latest link and updater `latest.json` resolve correctly.
2. Update wherever the installer is linked for download; the repository
   publishes release assets and does not push to any package manager.
3. Return new work to `CHANGELOG.md` under `Unreleased`.

## Hotfix

Branch from the latest supported tag only when `main` contains unrelated work
that cannot safely ship. Apply the smallest compatible fix, bump the patch
version, add the changelog entry, run the same release gates, and integrate the
hotfix into `main` with the repository's normal squash workflow. Security fixes
do not bypass artifact verification.

## GitHub repository controls

Recommended controls for `main`:

- require green CI on the short-lived branch before the owner-controlled squash
  into `main`, then require green `main` CI before tagging;
- include version drift, release metadata, Python, JS, Rust, Docker, and packaged
  smoke checks as required checks;
- block force pushes and branch deletion;
- delete short-lived branches after their squash commit is on `main`;
- enable Dependabot security updates and public-repository secret scanning where
  GitHub makes them available; and
- keep default workflow-token permissions read-only, granting write only inside
  the release jobs that need it.

Apply branch rules only after checking the exact status-check names, so the
owner is not locked out by a misspelled or obsolete required check.
