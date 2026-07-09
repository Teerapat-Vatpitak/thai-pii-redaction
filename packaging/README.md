# Packaging manifests

Package-manager manifests for distributing AI Guard as free OSS. These point at the
GitHub Releases installer for the Windows Tauri desktop app.

Current target: **v2.2.0**, Windows x64 NSIS installer
(`AI.Guard_2.2.0_x64-setup.exe`, SHA256 `0fa1d2afa42dde2222066164bd72820b84dcd0bc010a5cfb96e57ccad1b03a9c`).

These files are prepared here for review. Nothing is submitted automatically — submitting to
winget-pkgs or a Scoop bucket publishes the app outward, so do those steps yourself.

## winget (`winget/`)

Three manifest files (schema 1.6.0): version, installer, and en-US locale, for
`Teerapat-Vatpitak.AIGuard`.

To submit to the community repository:

1. Install the toolchain: `winget install wingetcreate` (or use the manifests directly).
2. Validate locally: `winget validate --manifest packaging/winget`
3. Test the install from the local manifests (enable local manifests first with
   `winget settings --enable LocalManifestFiles`):
   `winget install --manifest packaging/winget`
4. Fork [microsoft/winget-pkgs](https://github.com/microsoft/winget-pkgs), copy the three files to
   `manifests/t/Teerapat-Vatpitak/AIGuard/2.2.0/`, and open a PR. Or let wingetcreate do it:
   `wingetcreate submit packaging/winget --token <gh-token>`

Notes / caveats:
- **Publisher identifier** `Teerapat-Vatpitak.AIGuard` matches the GitHub account. It is public and
  sticky once accepted, so change it here before submitting if you want a different moniker.
- **Unsigned installer:** winget's automated validation runs the installer in a sandbox. An unsigned
  NSIS installer can pass, but users still see a SmartScreen prompt until the app builds reputation.
  Code-signing is a separate roadmap item.
- **Upgrade matching:** an `AppsAndFeaturesEntries` block (DisplayName "AI Guard", Publisher "Teerapat Vatpitak", DisplayVersion) is included so `winget upgrade` detects future versions. These values are best-effort until confirmed against a real install — after installing a build, read the actual ARP `DisplayName`/`Publisher`/`DisplayVersion` from the registry and correct them if they differ.
- **Updater artifacts:** from v2.x the release also carries a signed `latest.json` (the app's in-product auto-update feed). It only resolves once the draft release is published and marked "Latest".

## Scoop (`scoop/aiguard.json`)

The app ships as an NSIS installer, not a portable zip, so this manifest has Scoop extract the
installer with 7-Zip (`#/dl.7z`) and shim the app binary directly — no system-wide install, no admin.
Verified layout inside the installer: `desktop.exe` (Tauri GUI) and `aiguard.exe` (engine sidecar)
sit in the same root, so the sidecar resolves next to the GUI after extraction. `pre_install` deletes
the NSIS leftovers (`$PLUGINSDIR`, `uninstall.exe`).

- `bin` shims the GUI as the `aiguard` command; `shortcuts` adds a Start Menu entry "AI Guard".
- The `hash` is the SHA256 of the `.exe` bytes (Scoop hashes before the `#/dl.7z` extraction), so it
  equals the winget `InstallerSha256`.
- `checkver`/`autoupdate` track GitHub releases and rewrite the URL for future `$version`s.

To publish: either add `aiguard.json` to a Scoop bucket repo (e.g. a `scoop-aiguard` repo), or keep it
here and let users install directly:

```
scoop install https://raw.githubusercontent.com/Teerapat-Vatpitak/thai-pii-redaction/main/packaging/scoop/aiguard.json
```

Test locally before publishing: `scoop install packaging/scoop/aiguard.json` then launch `aiguard`,
confirm the backend starts (health at `127.0.0.1:8000`), and `scoop uninstall aiguard`.

## Updating for a new release

On each new tagged release, per artifact:

1. Download the installer and compute its SHA256:
   `gh release download vX.Y.Z -R Teerapat-Vatpitak/thai-pii-redaction --pattern "*x64-setup.exe"`
   then `certutil -hashfile <file> SHA256`.
2. Bump `PackageVersion`/`version`, the `InstallerUrl`/`url`, and the hash in all four files.
3. Re-validate (`winget validate`, and JSON-lint the Scoop file) before submitting.
