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

1. Freeze the intended scope and ensure every item meets the roadmap definition
   of done.
2. Pull the latest `main` and create a short-lived release-preparation branch.
3. Run `python scripts/bump_version.py X.Y.Z` rather than editing version strings.
4. Move the relevant `Unreleased` entries into
   `## [X.Y.Z] - YYYY-MM-DD`; leave a fresh empty `Unreleased` section.
5. Run `python scripts/check_release_readiness.py`.
6. Run the full local checks appropriate to the change, push the branch, and
   wait for every GitHub Actions job to pass.
7. Review the diff for installer names, updater configuration, API contract,
   documentation, and the release notes - not only tests.
8. Squash the reviewed branch into `main` as one commit, push `main`, and wait
   for every `main` CI job to pass before tagging.

## Tag and build

After the release-preparation branch is squashed into `main` and `main` is green:

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
