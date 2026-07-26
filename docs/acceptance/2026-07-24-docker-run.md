# Hosted Docker local acceptance

- Date: 2026-07-24
- Evidence level: local constrained Docker Desktop
- Official AI for Thai acceptance: no
- Image tag: `aiguard:post25-local`
- Local image ID:
  `sha256:e1d654d9bcfb1d68f6c3e4162c44761c841dd4bc6767caf340b7479261051958`
- Image size: `115,898,138` bytes
- Runtime limits: 1 CPU, 1 GiB RAM
- Runtime user: `appuser`
- Result: pass

The first build exposed a 1.41 GB build context because development `tmp/`,
Office dependencies, packaged output, and acceptance artifacts were not
excluded. `.dockerignore` now excludes those non-service paths and a regression
test pins the exclusions. The cached rebuild transferred only the changed
service context and completed in 6.6 seconds.

## HTTP and resource results

The container passed all seven non-live HTTP acceptance checks. The
booth-workload observations were:

| Operation | Local latency |
|---|---:|
| Health | 11.9 ms |
| Token sanitize | 26.2 ms |
| Surrogate sanitize | 19.2 ms |
| Re-identify | 3.6 ms |
| Text-layer PDF redact | 256.5 ms |

Token sanitize plus re-identification was 29.8 ms, below the local 2,000 ms
demo warning budget. After the workload, one Docker stats sample reported
177.2 MiB of 1 GiB, 0.20% CPU, and six container PIDs. This is not a peak or
platform p95 measurement.

The container log scan found none of the synthetic phone, name, or the word
`mapping`. The container was stopped and removed after the run; port 8000 was
not left published.

## Boundary

This proves the current hosted image builds, boots non-root, and runs the local
contract under the requested initial CPU/RAM profile. Registry push, platform
startup, official delivery/retry behavior, peak resource telemetry, and soak
remain blocked on the AI for Thai account and specification.
