# Provisional worker emulator acceptance

- Date: 2026-07-24
- Evidence level: local platform emulator
- Official AI for Thai acceptance: no
- Internal contract version: `1`
- Result: pass

Run:

```powershell
$env:PYTHONUTF8='1'
.\.venv\Scripts\python.exe scripts\run_worker_acceptance.py
```

The command writes a PII-free, gitignored record to
`artifacts/acceptance/worker-emulator.json`.

## Passed cases

- `detect`, `sanitize`, `analyze`, and fake-provider `roundtrip`, all four of
  which run on a core-only install since `analyze_text` moved into
  `pii_redactor/report.py` on 2026-07-29; the record still names which ran
  under `checks.operations`;
- explicit internal contract version and safe rejection of unsupported
  versions;
- malformed and oversized envelopes;
- duplicate delivery, conflicting duplicate IDs, and result-submit failure;
- same-process redelivery without a second provider side effect;
- provider timeout and substituted-handler crash containment;
- eight concurrent handler jobs;
- synthetic honeytoken scan over worker-visible logs and public error results.

The envelope defaults to a provisional 1 MiB maximum and can be reduced with
`AIGUARD_MAX_JOB_BYTES`. Job IDs are represented in logs only by a truncated
SHA-256 reference; request text and mappings are not logged.

## Honest boundary

The cache is deliberately bounded and process-local. It protects a redelivery
while the same worker process remains alive, including a failed result
submission. It cannot promise crash-safe exactly-once provider calls across a
container restart. Durable acknowledgement, retry ownership, and an
idempotency store cannot be selected until AI for Thai publishes the official
delivery contract.

The following remain externally blocked:

- platform account and registry access;
- official wire envelope and result protocol;
- acknowledgement/retry semantics;
- official timeout, payload, resource, network, and log policies;
- cross-process crash/idempotency acceptance;
- platform-visible honeytoken and soak evidence.
