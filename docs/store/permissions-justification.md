# AI Guard — Chrome Web Store permissions justification

Single purpose: detect and mask Thai PII before the user sends text to an
external AI chat service, then restore the original values locally from the
reply. Current source is not yet an accepted Web Store artifact because its
owner-approved item remains Draft/unpublished and the exact-ID real-browser run
loaded the package unpacked rather than through the Web Store.

## `storage`

- `chrome.storage.local` keeps the non-sensitive last-selected mask mode
  (`token` or `surrogate`).
- `chrome.storage.session` is cleared on native disconnect and service-worker
  initialization to remove legacy or stale session references. Broker scope
  and session handles are memory-only and never survive a worker generation.

The Extension does not store the canonical mapping, Python session ID,
request text, or detected PII in Chrome storage.

## `clipboardWrite`

Used only after the user clicks Copy in the side panel to copy the validated
masked text. The Extension never reads the clipboard and does not request
`clipboardRead`.

## `sidePanel`

Opens the docked side-panel workspace. Each panel instance has its own
service-worker-owned broker scope, disposed when that panel's runtime port
closes.

## `nativeMessaging`

Allows the MV3 service worker—the only native transport owner—to connect to
the exact registered host `th.ac.psu.aiguard.native_host`. Chrome starts the
thin stdio adapter, which validates the exact Extension origin and browser
process context before joining the shared broker as role `extension`.

The adapter and installed profile contain no provider command, remote TNER,
credential, localhost fallback, document/PDF transfer, mapping logic, or
detector implementation. The service worker retries only PII-free
connect/hello/health startup and never replays a PII-bearing request.

## No production `host_permissions`

The production manifest has no `host_permissions`. It contains no
`localhost`, `127.0.0.1`, direct HTTP client, port probe, or fallback. The
existing HTTPS content-script match list is unchanged and grants only content
script placement on supported AI chat sites; it is not a backend transport
permission.

## Content-script matches

The unchanged exact site list covers ChatGPT, Claude, Gemini, Grok,
Perplexity, Z.ai, ChatGLM, and BigModel. The content script renders
user-invoked Mask/Restore controls and locates likely composer/reply elements.
It never opens a native port or talks to a network endpoint.

Raw text used by in-page Mask has already entered provider-controlled DOM.
Site code may observe or transmit the draft before replacement. Users needing
the stronger raw-entry boundary should use the side panel and paste only the
reviewed masked result.

## Permissions not requested

No `tabs`, `webRequest`, `history`, `cookies`, `downloads`, `geolocation`,
`identity`, `clipboardRead`, broad host permission, or `<all_urls>` permission
is requested. There is no analytics SDK, telemetry, or remote code execution.
