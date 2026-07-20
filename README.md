<p align="center">
  <img src="assets/logo.png" alt="AI Guard logo" width="140" />
</p>

<h1 align="center">AI Guard</h1>

<p align="center">
  Mask Thai personal data before sending it to an external AI, then restore the real values locally.
</p>

<p align="center">
  <a href="https://github.com/Teerapat-Vatpitak/thai-pii-redaction/releases/latest"><img src="https://img.shields.io/github/v/release/Teerapat-Vatpitak/thai-pii-redaction?label=release" alt="Latest release" /></a>
  <a href="https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/workflows/ci.yml"><img src="https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/workflows/ci.yml/badge.svg" alt="CI" /></a>
  <img src="https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey" alt="Platforms" />
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-blue" alt="License: Apache 2.0" /></a>
</p>

<p align="center">
  <img src="assets/demo-before-after.png" alt="AI Guard before and after: real Thai PII on the left, masked tokens on the right" width="760" />
</p>

Everything runs on your machine. Detection is regex + checksum (Thai national ID
mod-11, phone, email, bank account) plus Thai NER from PyThaiNLP — no cloud
service sees your data, and the token-to-original map never leaves the device.

## Features

| | |
|---|---|
| **Mask & restore in the browser** | On ChatGPT, Claude, Gemini, Grok, Perplexity and GLM/Z.ai, replace PII with tokens (`[ชื่อ_1]`) or realistic fake data before sending, then restore the real values in the reply. A docked side panel does the same by paste on any other page. |
| **True PDF redaction** | Black out PII at the bounding-box level and get the redacted file plus a before/after preview. |
| **PDPA report** | Re-identification risk score and Section 26 sensitive-data flags (health, religion, and so on). |

## Install

Download the installer for your platform from the
[latest release](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/releases/latest):

| Platform | File |
|---|---|
| Windows | `AI.Guard_<version>_x64-setup.exe` |
| macOS (Apple Silicon) | `AI.Guard_<version>_aarch64.dmg` |
| Linux | `.AppImage` or `.deb` |

The installer bundles the backend, so no Python setup is required. It is
**unsigned by design** — trust comes from verifiable builds rather than a paid
certificate, so Windows SmartScreen warns on first run (**More info → Run
anyway**). See [SECURITY.md](SECURITY.md).

To add the in-page browser bar, load `extension/` unpacked at
`chrome://extensions` with Developer mode on, while the desktop app is running.
Details in [extension/README.md](extension/README.md).

Running from source instead: [docs/install-from-source.md](docs/install-from-source.md).

## Verify your download

Every release asset is listed in `SHA256SUMS` and carries GitHub build
provenance:

```bash
# integrity
sha256sum -c SHA256SUMS --ignore-missing      # macOS: shasum -a 256 -c
# origin — proves GitHub Actions built this file from this repo at this tag
gh attestation verify <file> -R Teerapat-Vatpitak/thai-pii-redaction
```

Build inputs are pinned (hash-locked Python lockfiles, SHA-pinned CI actions, a
SHA256-pinned Thai NER model, explicit pip/Rust/Node versions). This proves
origin and integrity; it is not a claim of bit-for-bit reproducibility.

## Two masking modes

| Mode | Output | Use when |
|---|---|---|
| `token` (default) | `[ชื่อ_1]`, `[เบอร์โทร_1]` | You want the AI to clearly see what was hidden. Restores exactly. |
| `surrogate` | Realistic fake Thai values with valid formats | You want text that reads naturally to the AI. |

## Status and scope

A working prototype, built for PSU Future Tech Challenge 2026 and maintained as
open source since. It is a **safety net, not a guarantee**: detection favours
recall over precision, but no automated tool catches every piece of personal
data. Review anything sensitive before you send it. No accuracy figures are
published until the benchmark work lands — see [ROADMAP.md](ROADMAP.md).

Not affiliated with, or endorsed by, any AI provider named above.

## Documentation

- [CONTRIBUTING.md](CONTRIBUTING.md) — development setup, tests, conventions
- [SECURITY.md](SECURITY.md) — reporting a vulnerability (private reporting is enabled)
- [CHANGELOG.md](CHANGELOG.md) — release history
- [ROADMAP.md](ROADMAP.md) — what is planned and what is deliberately out of scope
- [docs/decisions/](docs/decisions/) — design decisions and audit findings

## License

Apache-2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE) for third-party
attributions.
