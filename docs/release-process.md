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
- GitHub Release for that tag - downloadable artifacts, checksums, signatures,
  and attestations.

Packaging manifests are downstream consumers of a published release. They are
intentionally not version sources.

## Semantic version policy

- **Patch** (`x.y.Z`) - compatible bug/security fixes and operational fixes.
- **Minor** (`x.Y.0`) - additive user-facing capability, new endpoint/operation,
  or a materially new supported integration that preserves existing contracts.
- **Major** (`X.0.0`) - a deliberate breaking change to a supported public
  contract, persisted user data, or installer/update compatibility.

Docs-only commits do not require a tag. Development commits after a release stay
under `Unreleased` until the next release-preparation PR chooses the version.

Published product versions are monotonic and are never reset to `0.1.0` in the
same distribution identity. A separately deployed AI for Thai service may use
its own `0.x` line; see [the versioning proposal](versioning-proposal.md).

## Release preparation PR

1. Freeze the intended scope and ensure every item meets the roadmap definition
   of done.
2. Pull the latest `main`; do not release from a feature branch.
3. Run `python scripts/bump_version.py X.Y.Z` rather than editing version strings.
4. Move the relevant `Unreleased` entries into
   `## [X.Y.Z] - YYYY-MM-DD`; leave a fresh empty `Unreleased` section.
5. Run `python scripts/check_release_readiness.py`.
6. Run the full local checks appropriate to the change, then open the release
   PR and wait for all required GitHub Actions checks.
7. Review the diff for installer names, updater configuration, API contract,
   documentation, and the release notes - not only tests.

## Tag and build

After the release PR is merged and `main` is green:

```bash
git switch main
git pull --ff-only origin main
git tag -a vX.Y.Z -m "AI Guard vX.Y.Z"
git push origin vX.Y.Z
```

Rules:

- The tag must be placed on the exact reviewed merge commit.
- Never move, delete/recreate, or reuse a published version tag.
- A failed release is fixed with a new commit and new version, not a retag.
- Do not create the GitHub Release by hand before the tag workflow runs.

The release workflow verifies the tag/version/changelog relationship (including
an empty `Unreleased` section), builds each platform artifact, creates a draft
release, checks the asset set, publishes `SHA256SUMS`, and attaches GitHub build
provenance.

## Publish gate

The draft remains unpublished until the maintainer verifies:

- all expected Windows/macOS/Linux assets and updater files are present;
- the workflow is green on the tag;
- checksums match downloaded artifacts;
- `gh attestation verify` succeeds for representative artifacts;
- release notes match the changelog and make no unsupported claim; and
- an install/launch smoke has passed on the presentation platform.

Only then publish the draft and mark it Latest. Delete stale duplicate **drafts**
after verifying a published release for that tag already exists; never delete a
published release as routine cleanup.

## After publication

1. Run `python scripts/update_packaging.py vX.Y.Z`.
2. Review and validate the winget/Scoop diff in a separate PR.
3. Verify README's Latest link and updater `latest.json` resolve correctly.
4. Record any manual store/package submission separately; the repository script
   does not publish externally.
5. Return new work to `CHANGELOG.md` under `Unreleased`.

## Hotfix

Branch from the latest supported tag only when `main` contains unrelated work
that cannot safely ship. Apply the smallest compatible fix, bump the patch
version, add the changelog entry, run the same release gates, and merge the
hotfix back to `main`. Security fixes do not bypass artifact verification.

## GitHub repository controls

Recommended controls for `main`:

- require a pull request and green CI before merge;
- include version drift, release metadata, Python, JS, Rust, Docker, and packaged
  smoke checks as required checks;
- block force pushes and branch deletion;
- enable automatic deletion of merged branches;
- enable Dependabot security updates and public-repository secret scanning where
  GitHub makes them available; and
- keep default workflow-token permissions read-only, granting write only inside
  the release jobs that need it.

Apply branch rules only after checking the exact status-check names, so the
owner is not locked out by a misspelled or obsolete required check.
