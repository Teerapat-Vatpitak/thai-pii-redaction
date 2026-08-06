# Office v2 packaged-backend and HTTPS proxy preflight — 2026-08-06

Status: **automated local transport composition passed; Office real-host and
packaged unified-manifest acceptance remain open**.

## Candidate and environment

- Repository branch: `codex/office-v2-composition`
- Base commit: `1808be8ea1b3e219517842cadfcd47c50c3baebb`
- Source identity: the squash commit containing this record
- Product version: `2.5.0`
- OS: Windows 11 Home Single Language, build `26200`
- Python: `3.13.14`
- Node/npm: `22.23.2` / `10.9.8`
- Rust: `1.97.0`

Only synthetic input was used. This record contains counts and structural
results only; it does not contain request or restored text, a `session_id`,
token value, mapping, credential, certificate material/digest, provider body,
or private key.

## Commands

The exact evidence path builds both artifacts, requires the HTTPS leg, and
refuses to provision certificate trust:

```powershell
$env:PYTHONUTF8='1'
.\.venv\Scripts\python.exe scripts\office_v2_composition.py --require-https
```

The final focused rerun after the artifact builds used:

```powershell
.\.venv\Scripts\python.exe scripts\office_v2_composition.py `
  --skip-sidecar-build `
  --skip-office-build `
  --require-https
```

The default command may exit successfully with the HTTPS leg marked `PENDING`
when the standard Office development certificate is absent or untrusted.
Only a successful `--require-https` run supports the passed status above.

## Observed result

- The Office production bundle built successfully.
- The packaged Windows sidecar built, booted headlessly, and reported HTTP
  contract v2 with control-plane protection enabled and no data-plane API-key
  requirement.
- Direct packaged-backend health, token sanitize, and reidentify passed:
  2 entities detected, 2 replacements restored, 0 leftovers.
- The Vite task-pane entry loaded over `https://localhost:3000`.
- The same health, token sanitize, and reidentify flow passed through the
  Office HTTPS development proxy: 2 entities detected, 2 replacements
  restored, 0 leftovers.
- Strict response validators rejected extra or missing capability fields in
  automated tests. No capability returned a token or credential value.
- The three pre-existing Office development certificate files were byte- and
  timestamp-identical before and after the proxy run. No certificate was
  generated, installed, trusted, replaced, or removed.
- The packaged sidecar and Vite process trees stopped, and ports 8000 and 3000
  were free after the run.
- The packaged profile forced the local offline `thainer` engine, removed
  inherited provider/data-plane credentials, disabled browser opening, and made
  no provider call.

## Evidence boundary

This is automated local transport preflight evidence. It built the Office
bundle and fetched the task-pane entry, but Python drove the strict-v2 API flow;
Office JavaScript and host adapters did not execute. No Office host or installed
Desktop application was opened. No manifest was sideloaded or activated. No
certificate trust, package installation, live provider, release, deployment,
store, or official-platform action occurred.

The Microsoft 365 Add-in therefore remains **Acceptance pending**. The
Word-only release manifest is unchanged, and all eight open real-host/package
checks in the acceptance index remain open.
