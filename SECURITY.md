# Security Policy

## Supported versions

Only the **latest release** (see [`VERSION`](VERSION) / the
[Releases page](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/releases/latest))
is supported with security fixes. This is a solo-maintained project without
a long-term-support branch — please upgrade to the latest release before
reporting an issue, and re-check it still reproduces there.

## Reporting a vulnerability

Please **do not open a public GitHub issue** for a security vulnerability.

Instead, use GitHub's private vulnerability reporting:
[Security → Report a vulnerability](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/security/advisories/new)
on this repo. This opens a private advisory visible only to the maintainer
until a fix is ready, so real users aren't exposed while it's being worked
on.

Include, where relevant: the affected version (`VERSION` / release tag),
a reproduction, and the impact you believe it has (e.g. PII leak to an
external AI provider, vault/session data exposure, localhost API abuse).

There is no bug bounty. Reports are handled on a best-effort, solo-maintainer
timeline — expect an initial response within a few days, not hours.

## Threat model (short version)

AI Guard is a **local-first** tool. Understanding what "local-first" means
here helps calibrate what counts as a security bug:

- **Backend is localhost-only.** `app/server.py` binds to `127.0.0.1` /
  `localhost` and its CORS policy (`allow_origin_regex`) only allows browser
  extension origins (`chrome-extension://`, `moz-extension://`) and the
  bundled Tauri desktop shell (`tauri://localhost`) — not `*`. A
  `TrustedHostMiddleware` further restricts the `Host` header to
  localhost/127.0.0.1. There is no remote/hosted deployment of this backend;
  running it reachable from the network is out of scope and unsupported.
- **The vault never leaves the device.** The pseudonym ↔ original PII mapping
  (`SessionVault`) lives in server process memory only — never written to
  disk, never sent over the network. The browser extension holds only an
  opaque `session_id`; the desktop app talks to its own bundled sidecar
  process. A vulnerability that exfiltrates vault contents off-device (not
  just within the local process) is high severity.
- **No cloud, no telemetry.** PII detection and pseudonym generation run
  entirely locally (regex/checksum + local NER models); nothing is sent to
  an external service *except* the already-pseudonymized text, deliberately,
  when the user chooses to send a prompt to an external AI provider (the
  product's whole point). A bug that causes *real, unpseudonymized* PII to
  reach that external call (a "leak") is the single highest-severity class of
  bug in this project — see the pre-send / pre-export leak guards described
  in `CLAUDE.md`.
- **Distribution is unsigned.** The Windows/macOS/Linux builds are not
  code-signed (a deliberate scope decision — see `ROADMAP.md`). Trust is
  meant to come from a reproducible, verifiable build (pinned dependencies,
  published checksums) rather than a purchased certificate. If you find a
  way to make the build *not* reproducible from this source in a way that
  matters for supply-chain trust, that's worth reporting too.

Out of scope: the SmartScreen/Gatekeeper "unknown publisher" warning itself
(expected, documented in the README) and denial-of-service against a backend
that, by design, only your own machine can reach.
