# AI Guard browser extension

AI Guard masks Thai PII before text is sent to an AI chat site and restores
the original values locally from a reply. The installed-production transport
in current source is Chrome Native Messaging:

```text
content script or side panel
  -> MV3 service worker (the only native-port owner)
  -> th.ac.psu.aiguard.native_host
  -> shared per-user broker
  -> private authenticated HTTP-v2 backend
  -> shared Python core
```

The production manifest requests `nativeMessaging` and has no loopback
`host_permissions`. Production JavaScript contains no HTTP client, backend
port probing, native broker endpoint, credential, provider command, or
localhost fallback. The Desktop companion package owns the adapter, broker,
backend, native-host manifest, and registration. Chrome can start or join that
broker without the Desktop GUI running.

The repository-owned production identity is the owner-approved unpublished
Chrome Web Store item `kdjmkknedgmfphpkjhjdhmjadaelgggm`, exact origin
`chrome-extension://kdjmkknedgmfphpkjhjdhmjadaelgggm/`. Its public key is in
`config/chrome-extension-identity.json`; no private signing key is stored or
required. The deterministic identity under `tests/fixtures/native_host/` is
public-only and may be selected only by explicit test/package-acceptance flags;
it is not a production identity. The Web Store item remains Draft/unpublished,
and exact-ID unpacked Chromium acceptance is not Web Store installation.

## Data and authority boundary

The installed Extension profile uses local `thainer` only. `fake` is retained
inside backend conformance support; the Extension exposes no provider or
detector selector. Remote TNER, provider credentials, and credential-requiring
providers are unavailable on this path. The adapter contains no detector,
mapping, restore, provider, retry, or HTTP logic.

The canonical token-to-original vault stays in the private backend's memory.
Python session IDs and mappings never reach Extension JavaScript. The service
worker keeps only broker-issued handles in memory and owns a separate broker
scope for each admitted tab and each side-panel instance. A handle cannot cross
tabs or panel contexts.

- Top-frame content messages require consistent HTTPS sender, tab, document,
  and origin evidence.
- Every replacement document, including a same-origin hard navigation,
  disposes the old tab scope. Tab or panel close disposes only that context.
- Native-port loss or service-worker restart invalidates every local handle,
  clears legacy/stale session storage, removes restore/write authority, and
  shows a fixed unavailable/session-expired state.
- Only PII-free connect/hello/health startup may retry. Health recovery uses
  bounded exponential delay capped at 30 seconds while the page stays active.
  Mask, Restore, and any possibly completed operation are never replayed.
- A fresh connection never revives an old mapping; a new user-initiated Mask
  is required before Restore is available again.
- Install, repair, update, and removal activate a verified companion-owned
  maintenance barrier before component replacement. New native admission is
  rejected, the least-authority maintenance role drains broker/backend state,
  and every tab/panel handle becomes unusable. The barrier and package bytes
  contain no mapping; upgrade never migrates or replays a session.

Strict result validators run before composer, closed-shadow overlay,
side-panel, or clipboard writes. Unknown, malformed, oversized, stale,
incompatible, or uncertain responses produce no write.

In-page Mask still starts after raw text has entered the AI site's
provider-controlled DOM. Page code may observe or transmit the draft before
AI Guard replaces it. Native Messaging does not remove that earlier boundary.
Use the side panel and paste only the reviewed masked result when stronger
raw-entry isolation is required.

## Development and test loading

An unpacked build needs a matching registered companion and an identity whose
public key derives the loaded Extension ID. Do not start the fixed-port
developer backend for the Extension; it has no path to that service.

Production packaging requires an identity JSON classified
`production_owner_approved`:

```powershell
.\.venv\Scripts\python.exe scripts\package_extension.py `
  --identity config\chrome-extension-identity.json
```

The identity file may contain only the Chrome Web Store Item ID, exact
`chrome-extension://<id>/` origin, public manifest key, classification, and
provenance. Never place a private signing key in the repository or command
output. Synthetic packaging is reserved for deterministic automated and local
acceptance and requires its explicit opt-in flag; see `--help`.

After registering a matching candidate:

1. Open `chrome://extensions` and enable Developer mode.
2. Load the built candidate directory, not an arbitrary source directory.
3. Confirm the derived ID exactly matches the registered manifest origin.
4. Open the toolbar side panel or a supported site.

Supported content-script sites remain ChatGPT, Claude, Gemini, Grok,
Perplexity, and GLM/Z.ai. Site selectors live in `sites.js`; selector drift can
still choose another visible matching element and requires fresh live-site
acceptance.

## Failure behavior

- **Companion unavailable**: install/repair the matching Desktop companion.
  Restore and page writes remain blocked.
- **Session expired**: perform a new user-initiated Mask. Old masked text cannot
  restore through the new connection.
- **In-page controls missing**: use the side panel while the site selector is
  reviewed.
- **Upgrade or repair in progress**: wait for the companion to finish, then
  start a fresh Mask. Do not expect pre-upgrade Restore to recover.

The exact Slice 5 production-identity, installed-companion, and remaining
unpublished-Web-Store evidence classifications are recorded in
`docs/acceptance/2026-08-11-phase-8-slice-5-native-messaging.md`.
Slice 6 upgrade, restart, wrong-origin, uninstall/reinstall, Desktop
coexistence, and empty-state evidence is recorded separately in
`docs/acceptance/2026-08-12-phase-8-native-broker-package-recertification.md`.
The real-browser path uses an exact production-keyed unpacked candidate in
Google Chrome for Testing; it is not Chrome Web Store installation. The item
remains Draft/unpublished.
