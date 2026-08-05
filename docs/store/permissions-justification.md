# AI Guard — Chrome Web Store Permissions Justification

Single-purpose statement: AI Guard detects and masks Thai personally identifiable
information (PII) in text before the user sends it to an external AI chat
service, and restores the original values locally once the AI's reply comes
back. Every permission below exists only to support that one purpose.

All direct backend calls the extension makes go to a backend the user runs on
their own machine (`http://localhost:8000` / `http://127.0.0.1:8000`). The
default detector is local; if the user explicitly configures remote TNER, that
backend sends raw pre-mask chunks to AI for Thai. See
`docs/store/privacy-policy.md` for the full data-handling description.

## `storage`

Used to persist two small pieces of state. The mode is non-sensitive;
`session_id` is an opaque but security-sensitive bearer-like restoration
reference:

- The user's last-chosen mask mode (`token` or `surrogate`), in
  `chrome.storage.local`, so the in-page bar and the side panel agree on the
  same choice across page loads (`extension/background.js:101`,
  `extension/sidepanel.js:47,51`).
- A per-tab `session_id` in `chrome.storage.session`, so a "Restore PII"
  click can look up the right backend session even after the MV3 service
  worker has been evicted and restarted by Chrome. `chrome.storage.session`
  is cleared automatically when the browser closes and is never written to
  disk (`extension/background.js:11-14,37,47`). The `session_id` is not the
  mapping, but it must be protected as session authority. The canonical
  PII↔placeholder vault
  remains in backend memory and is not deliberately persisted. Current HTTP
  contract v1 can return fields containing or permitting reconstruction of
  mapping pairs in extension process memory, although the extension does not
  deliberately persist them. Removing those fields is a contract-v2
  hardening gate.

## `clipboardWrite`

Used only for the "Copy" button in the side panel, which copies the masked
text to the user's clipboard after they click "Mask" (`extension/sidepanel.js:138-143`,
`navigator.clipboard.writeText`). The extension never reads the clipboard
and requests no `clipboardRead` permission.

## `sidePanel`

Used to open AI Guard's docked side-panel workspace (paste text to mask,
paste an AI reply to restore) via `chrome.sidePanel`
(`extension/background.js:22-27`, `extension/manifest.json` `side_panel`
key). This is the extension's primary manual-entry UI, alongside the
in-page floating bar.

## `host_permissions`: `http://localhost:8000/*`, `http://127.0.0.1:8000/*`

The extension's masking/restoration request path and default detector run in a
local backend process that the user starts on their own machine (see project
`README.md` / `run.ps1`). An explicitly selected TNER engine is the exception:
the backend sends raw pre-mask chunks to AI for Thai. These two host
permissions are what let
the extension's background service worker call that local backend across
origins from pages like `chatgpt.com` or `claude.ai`
(`extension/background.js:16,56-86`) — Chrome's default cross-origin
restrictions would otherwise block a content-script-initiated fetch to
`localhost` from those sites. No other hosts are ever contacted; there is no
code path in the extension itself that reaches any domain besides these two.
The current source extension trusts whichever process owns the fixed localhost
port; CORS and host permissions do not authenticate that process. It can also
write masked output after a text-based residual warning, so the current source
candidate is not accepted as a fail-closed production package. Users should run
only a backend they started and trust and review the result before submitting
it. Packaged production operation is intended to move to a native broker,
remove direct localhost host permissions, and block every residual signal;
that migration is not yet accepted.

## `content_scripts` matches (6 AI chat providers)

The extension injects a small floating "Mask PII / Restore PII" control bar
and a per-message "Restore" button into the pages of the AI chat services it
supports, so the user can mask before sending and restore after receiving a
reply without leaving the chat page:

- `chatgpt.com`, `chat.openai.com` — ChatGPT
- `claude.ai` — Claude
- `gemini.google.com` — Gemini
- `grok.com`, `*.grok.com` — Grok
- `perplexity.ai`, `*.perplexity.ai` — Perplexity
- `chat.z.ai`, `*.z.ai`, `chatglm.cn`, `*.chatglm.cn`, `*.bigmodel.cn` — GLM / Z.ai

Each match is a specific, publicly documented AI chat product domain, not a
broad or unrelated host. The content script (`extension/content.js`,
`extension/sites.js`) uses site selectors and broad visible
contenteditable/textarea or assistant/response fallbacks to locate likely
composer and reply elements when the user invokes Mask or Restore. On selector
drift, a fallback can read a different matching visible element; tightening
that heuristic is an acceptance concern. It writes masked text into the chosen
composer or restored text into an overlay. It does not talk to the network
directly; all network calls go through the background service worker described
above.

The in-page workflow starts after raw text has been entered into the AI site's
provider-controlled DOM. Page code can observe or transmit that draft before
Mask replaces it. Users who require the stronger isolation boundary should
enter raw text in the extension side panel and paste only the reviewed masked
result into the site.
`web_accessible_resources` in the same match list only exposes the
extension's own toolbar icon files (`icons/icon16.png` … `icon128.png`) so
the injected bar can render its logo; no other extension file is exposed to
these pages.

## Summary of what is *not* requested

No `tabs`, `webRequest`, `history`, `cookies`, `downloads`, `geolocation`,
`identity`, or broad (`<all_urls>`) host permission is requested. The
extension has no remote-code execution, no analytics SDK, and no telemetry.
