# Phase 4B: Packaging + Release CI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the release pipeline to sign + publish updater artifacts, and finalize the winget manifest so `winget upgrade` matches future versions.

**Architecture:** The `release.yml` workflow already builds installers via `tauri-action`. Adding the two Tauri signing secrets to that step makes it emit a signed `latest.json` (the endpoint Plan 4A points at). The winget manifest gets an `AppsAndFeaturesEntries` block now that the installer carries a real publisher.

**Tech Stack:** GitHub Actions, `tauri-apps/tauri-action@v0`, winget manifest schema 1.6.0.

## Global Constraints

- Depends on Plan 4A having set `bundle.createUpdaterArtifacts: true`. With that on, `tauri build` REQUIRES `TAURI_SIGNING_PRIVATE_KEY` at build time or the release build fails. Therefore the next tagged release will fail unless the user has set the signing secrets — this is expected and documented, not a bug.
- Releases stay `releaseDraft: true`; the user publishes manually. `latest.json` at `releases/latest/download/latest.json` only resolves after publish.
- Shipping unsigned (no OS code-signing); document the SmartScreen bypass. No cert step.
- winget `PackageIdentifier` stays `Teerapat-Vatpitak.AIGuard`. `InstallerType` is `nullsoft` (NSIS), already correct.
- No emoji. Commit messages: no `Co-Authored-By` trailer.

## File Structure

- `.github/workflows/release.yml` — add the two signing-secret env vars to the `tauri-action` step.
- `packaging/winget/Teerapat-Vatpitak.AIGuard.installer.yaml` — add `AppsAndFeaturesEntries`.
- `packaging/README.md` — document the signing/latest.json flow + the `AppsAndFeaturesEntries` caveat.

---

### Task 1: Sign updater artifacts in the release workflow

**Files:**
- Modify: `.github/workflows/release.yml`

**Interfaces:**
- Consumes: repo secrets `TAURI_SIGNING_PRIVATE_KEY`, `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` (set by the user).
- Produces: a release that includes `latest.json` + `.sig` files (the update feed Plan 4A reads).

- [ ] **Step 1: Add the signing env to the tauri-action step**

In `.github/workflows/release.yml`, in the `Build the Tauri app and publish the Release` step, extend the `env:` block (currently just `GITHUB_TOKEN`) to:

```yaml
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          TAURI_SIGNING_PRIVATE_KEY: ${{ secrets.TAURI_SIGNING_PRIVATE_KEY }}
          TAURI_SIGNING_PRIVATE_KEY_PASSWORD: ${{ secrets.TAURI_SIGNING_PRIVATE_KEY_PASSWORD }}
```

Leave the `with:` block (projectPath, tagName, releaseName, releaseBody, releaseDraft, prerelease) unchanged. `tauri-action` emits `latest.json` automatically when `createUpdaterArtifacts` is on.

- [ ] **Step 2: Verify the workflow YAML parses**

Run: `$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe -m pip install --quiet pyyaml; .\.venv\Scripts\python.exe -c "import yaml; yaml.safe_load(open('.github/workflows/release.yml', encoding='utf-8')); print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/release.yml
git commit -m "ci(release): sign + publish updater artifacts (latest.json) via tauri-action"
```

---

### Task 2: winget upgrade-matching + packaging docs

**Files:**
- Modify: `packaging/winget/Teerapat-Vatpitak.AIGuard.installer.yaml`
- Modify: `packaging/README.md`

**Interfaces:**
- Consumes: nothing.
- Produces: a winget installer manifest with an ARP-matching block, valid under `winget validate`.

- [ ] **Step 1: Add AppsAndFeaturesEntries**

In `packaging/winget/Teerapat-Vatpitak.AIGuard.installer.yaml`, add this block at the root level, immediately before the `Installers:` line:

```yaml
AppsAndFeaturesEntries:
  - DisplayName: AI Guard
    Publisher: Teerapat Vatpitak
    DisplayVersion: 2.0.0
```

These mirror the installer's Add/Remove-Programs entry (DisplayName = productName "AI Guard"; Publisher = `bundle.publisher`). They are best-effort until confirmed against a real install; a wrong value degrades `winget upgrade` matching but never breaks install.

- [ ] **Step 2: Re-validate the winget manifest**

Run: `winget validate --manifest packaging/winget`
Expected: `Manifest validation succeeded.`

- [ ] **Step 3: Document the signing + upgrade caveat in the packaging README**

In `packaging/README.md`, under the winget "Notes / caveats" list, replace the existing "Upgrade matching:" bullet (which said no `AppsAndFeaturesEntries` was included) with:

```markdown
- **Upgrade matching:** an `AppsAndFeaturesEntries` block (DisplayName "AI Guard", Publisher "Teerapat Vatpitak", DisplayVersion) is included so `winget upgrade` detects future versions. These values are best-effort until confirmed against a real install — after installing a build, read the actual ARP `DisplayName`/`Publisher`/`DisplayVersion` from the registry and correct them if they differ.
- **Updater artifacts:** from v2.x the release also carries a signed `latest.json` (the app's in-product auto-update feed). It only resolves once the draft release is published and marked "Latest".
```

- [ ] **Step 4: Commit**

```bash
git add packaging/winget/Teerapat-Vatpitak.AIGuard.installer.yaml packaging/README.md
git commit -m "packaging(winget): add AppsAndFeaturesEntries + document updater/upgrade flow"
```

---

## Self-Review

- **Spec coverage:** release-CI signing env (Task 1), `latest.json` emission (Task 1, via createUpdaterArtifacts from Plan 4A), winget `AppsAndFeaturesEntries` (Task 2), README finalize incl. SmartScreen/unsigned already present + updater note (Task 2). The publish dependency is captured in Global Constraints. All Component-B points covered.
- **Placeholders:** none. Every edit shows the exact YAML.
- **Type consistency:** secret names `TAURI_SIGNING_PRIVATE_KEY` / `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` match the user's key-setup commands and Plan 4A's nuance note. `PackageIdentifier` and `InstallerType: nullsoft` unchanged from the validated manifest.
