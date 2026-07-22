# Architecture and trust boundaries

AI Guard follows **one core, multiple storefronts**. Detection,
pseudonymization, leak scanning, restoration, and validation live under
`pii_redactor/`. The extension, desktop app, CLI, HTTP API, demo, and platform
worker adapt user or platform input to that core; they must not create separate
detection logic.

## System shape

```text
Browser extension ----\
Desktop app -----------+--> FastAPI adapter ----\
CLI -------------------/                        |
                                                +--> pii_redactor core
Demo playground -------> demo/API adapter ------|    detect -> mask -> guard
Platform queue --------> worker adapter --------/    -> provider -> restore
```

The FastAPI session path and the queue worker serve different lifecycles:

- Local HTTP sessions retain a mapping in process memory behind an opaque
  `session_id`, enabling multi-turn restoration on one device.
- Stateless worker operations create a mapping only for the duration of the
  operation. `roundtrip` consumes it before returning. `sanitize` does not
  return it unless an exact explicit opt-in is supplied; the hosted product
  should not enable that opt-in by default.

## Trust boundary A - local product

The desktop sidecar binds to localhost and serves the extension/desktop shell.
Detection and the token-to-original mapping stay on the device. When the user
chooses an external AI provider, the outbound leak guard checks the masked text
before it leaves. The external provider should see only masked values.

The local claim is therefore: **the mapping and raw PII do not leave the user's
device through the intended product flow**.

## Trust boundary B - hosted platform

Calling a hosted AI Guard service necessarily sends the request to the hosting
platform. The raw input therefore reaches the platform boundary and the AI
Guard container. The hosted guarantees are narrower:

- no mapping persistence to disk;
- no user text or raw PII in application logs or public error messages;
- no mapping in the normal queue result;
- a protected Pathumma roundtrip sends Pathumma only the masked prompt; and
- container restart may intentionally discard transient restoration state.

The hosted product must never reuse the local slogan "PII never leaves the
device". It may say that **Pathumma receives masked text and AI Guard does not
persist the transient mapping** when the corresponding path is used.

## Core processing layers

1. Ingest and normalize text or PDF content while preserving coordinates where
   redaction requires them.
2. Detect structured PII with regex/checksum rules and free-form PII with Thai
   NER/context logic.
3. Resolve overlaps centrally before any replacement.
4. Replace values with tokens or realistic surrogates.
5. Run outbound leak checks before an optional AI provider call.
6. Restore from the in-memory mapping when the selected lifecycle supports it.
7. Validate restoration/output integrity and produce PII-free audit metadata.
8. Return text, a report, or a flattened redacted PDF.

Section 26 semantic signals are reported rather than automatically removed.
The prompt-injection guard is an independent warn-only signal layer, not part of
PII detection and not a complete injection defense.

## Source layout

| Path | Responsibility |
|---|---|
| `pii_redactor/` | Product core: ingest, detection, masking, vault, provider clients, restoration, validation, reports, and PDF redaction. |
| `app/server.py` | Local/HTTP adapter and API contract. |
| `app/worker/` | Stateless job operations plus a replaceable platform transport. |
| `extension/` | MV3 browser extension and supported-site adapters. |
| `desktop/` | Tauri shell, static UI, updater, and sidecar lifecycle. |
| `demo/` | Opt-in demonstration UI; not a separate production frontend. |
| `benchmark/` | Diagnostic corpora, scorers, and engine comparisons. |
| `tests/` | Contract, security, feature, benchmark, and packaging regression tests. |
| `scripts/` | Build, version, release, packaging, and smoke tooling. |
| `docs/` | Current operating docs plus historical ADRs. |

This boundary is already test-covered. Moving modules for appearance alone
would add release risk without improving the product, so source reorganization
is deferred unless a concrete dependency or ownership problem appears.

## Configuration boundaries

- `VERSION` is the product-version source of truth.
- `contract_version` is the independently versioned public API contract.
- `AIGUARD_NER_ENGINE` selects a process-wide NER implementation.
- `AIGUARD_API_KEY` protects hosted declared API endpoints when configured.
- `AIFORTHAI_API_KEY` is a provider credential for Pathumma/TNER, not the AI
  Guard caller credential.
- Optional ML/OCR dependencies are not silently installed or silently selected.

Platform-specific queue envelopes, hostnames, and credentials belong in an
adapter/configuration layer. They must not leak into detection or masking code.
