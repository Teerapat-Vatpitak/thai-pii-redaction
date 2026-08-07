# Phase 8 explicit-TNER fail-closed source hardening

- Evidence date (Asia/Bangkok): `2026-08-07`
- Clean base commit: `fa74a4c1b192580f7c5c9f671cbc4de5aaab4eec`
- Reviewed code candidate: `3d5a5aff79d77c6e3a1c0ecbe3580eb3c60a331e`
- Branch CI head: `a7e388257190527c3fc6ff29100e2f17af9abf94`
- Candidate branch: `codex/phase-8-tner-fail-closed`
- Product version: `2.5.0` (unchanged)
- Status: **integrated into main; branch CI green**

This record covers the first separately reviewable Phase 8 unit: whole-operation
failure for an explicitly selected remote TNER engine. It is current-source
automated evidence, not a live TNER, packaged/installed, real-host, deployment,
release, or official-platform certification.

All runtime checks used synthetic values. This record contains no request text,
entity value, mapping, credential, provider body, restored answer, or
machine-specific artifact path.

## Behavior established

`AIGUARD_NER_ENGINE=tner` remains opt-in and sends raw pre-mask chunks to AI for
Thai. It is now the fail-closed exception to the local NER resilience policy:

- missing configuration aborts before any chunk request;
- local client/dependency failures abort as non-retryable `ner_unavailable`;
  this evidence does not establish whether transmission began;
- transport and upstream failures abort on the first failed chunk;
- malformed JSON, invalid parallel fields, incomplete source coverage, illegal
  BIO transitions, unknown labels, and truncated or misaligned token streams
  abort as incomplete;
- candidates from earlier chunks are discarded, and later chunks are not sent;
  and
- the provider, PDF renderer, session publication, and successful worker result
  are never reached after the TNER failure.

Local/default `thainer`, WangchanBERTa, and union execution retain their
structural skip-and-continue behavior. The selected engine is resolved once per
detection call.

TNER token alignment now uses authoritative source positions when building
entity spans. Internal whitespace remains inside a continued entity even when
the remote tokenizer omits the separator or returns it as a blank-tag token.
The adapter accepts only the bounded current/legacy label vocabulary and one
legal ordered BIO stream. Provider-controlled labels are never written to the
degenerate-span warning.

The core error carries only fixed code, category, derived retryability, and
failed/incomplete-chunk count:

| Code | Category | Retryable | Count |
|---|---|---:|---:|
| `ner_unavailable` | `configuration` or `dependency` | false | failed chunks; pre-chunk configuration/dependency is 0 |
| `ner_unavailable` | `network` or `upstream` | true | failed chunks |
| `ner_incomplete` | `upstream` | false | incomplete chunks; minimum 1 |

HTTP v2 projects `ner_unavailable` as 503 and `ner_incomplete` as 502 in the
existing fixed envelope. Local, hosted, direct detect/analyze, sanitize,
roundtrip, and PDF paths use the same central translation. Worker envelope v1
does not gain fields: it returns only the fixed type and fixed message.

Every containment boundary snapshots the bounded metadata, clears the original
exception graph and payload, and raises or returns a fresh value-free failure.
Regressions retain the original error to verify that input, credential,
provider-body, vault, mapping, traceback, cause, context, and ordinary custom
attributes are unreachable. Second-scan failures occur after anonymization has
populated the throwaway or staged vault; the throwaway vault is cleared and an
existing published session remains byte-for-byte structurally unchanged.

## Local verification

| Gate | Result |
|---|---|
| Tests-first collection gate | PASS as evidence — initial focused collection failed until the new failure module existed |
| Final focused TNER/core/adapter matrix | PASS — 411 passed, 1 existing warning |
| Local span/window regression matrix | PASS — 179 passed |
| Final full Python suite | PASS — 2,299 passed, 5 skipped, 1 warning in 251.84 seconds |
| Documentation coverage | PASS — 6 passed |
| `python -m ruff check .` | PASS |
| `python -m ruff format --check .` | PASS — 218 files |
| Version synchronization | PASS — `2.5.0` |
| Release-readiness check | PASS |
| `git diff --check` | PASS |
| Independent privacy/correctness review | PASS — all confirmed findings fixed; exact-current re-review found no blocker |
| Exact-head branch CI | PASS — [11/11 jobs](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31126705388/attempts/2) |

The warning is the existing Starlette/httpx TestClient deprecation warning.
The five skips are optional OpenCV OCR cases because `cv2` is not installed.

GitHub's 2026-08-06 Actions incident canceled jobs before they ran in the
initial exact-head attempts; it did not produce a test failure. Attempt 2
reran only the canceled jobs and completed with all 11 jobs recorded green on
the branch CI head above. This record does not claim post-merge CI.

The principal commands were:

```powershell
$env:PYTHONUTF8='1'
.\.venv\Scripts\python.exe -m pytest tests\test_tner_client.py tests\test_ner_engine.py tests\test_step2_detection.py tests\test_tb_degenerate_chunk_guard.py tests\test_stateless_leak_regression.py tests\test_session_service.py tests\test_http_v2_contract.py tests\test_worker_handler.py tests\test_hosted_readiness.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_tb_windowing.py tests\test_name_boundary_hygiene.py tests\test_ocr_tolerant_name_shapes.py tests\test_step2_detection.py tests\test_tb_degenerate_chunk_guard.py -q
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe scripts\measure_perf.py
.\.venv\Scripts\python.exe scripts\check_version.py
.\.venv\Scripts\python.exe scripts\check_release_readiness.py
git diff --check
```

## Performance

The formal command remained red only on the repository's older sanitize
anchor:

| Operation | Candidate | Committed baseline | Formal result |
|---|---:|---:|---|
| Detect | 6.01 ms | 5.73 ms | within 20% |
| Sanitize | 15.76 ms | 10.08 ms | +56%, over the stale anchor |
| Restore | 0.25 ms | 0.28 ms | within 20% |
| PDF redact | 73.17 ms | 67.67 ms | within 20% |
| Resident memory | 152.9 MiB | 151.4 MiB | within 15% |

Three alternating runs compared the candidate with exact clean base
`fa74a4c` in the same environment:

| Operation | Clean base median | Candidate median | Candidate delta | Budget |
|---|---:|---:|---:|---:|
| Detect | 5.96 ms | 6.07 ms | +1.8% | within 20% |
| Sanitize | 15.96 ms | 16.13 ms | +1.1% | within 20% |
| Restore | 0.24 ms | 0.25 ms | +4.2% | within 20% |
| PDF redact | 74.36 ms | 73.61 ms | -1.0% | within 20% |
| Resident memory | 153.3 MiB | 153.5 MiB | +0.1% | within 15% |

The branch itself is inside the repository time and memory budgets. The
committed baseline was not moved. The previously recorded sanitize-anchor
privacy/security explanation remains unchanged.

## Independent review

The first read-only review confirmed five defect classes in the candidate:

1. omitted whitespace could shorten a continued entity span and leave its last
   source character outside the redaction;
2. non-string tokens/tags, leading or mismatched I-tags, empty labels, and
   unknown labels could be accepted as a clean response;
3. an unexpected local HTTP-client defect was mislabeled as retryable network
   unavailability;
4. a provider-controlled unknown label could reach a warning log; and
5. cleanup tests failed before anonymization, so populated throwaway/staged
   vault disposal was not pinned.

Source-position span ends, strict schema/BIO/label validation, bounded
dependency classification, fixed remote-label logging, and post-anonymization
cleanup regressions close those findings. The exact-current read-only re-review
found no remaining actionable issue or blocker.

## Evidence boundaries and next Phase 8 decisions

No live credential or TNER request was used. Historical 2026-07 live
response-shape and mapping evidence predates this changed adapter and does not
certify it. Fresh live acceptance must still prove the current response shape,
known label vocabulary, full source coverage, and end-to-end
`NAME`/`LOCATION`/`ORGANIZATION`/`DATE` mapping.

This record does not verify an installed Desktop application, real browser,
Office host, package, optional OCR/ML runtime, deployment, platform logs,
resource/soak behavior, release, or the separately versioned sibling core.

The native localhost broker and broker-backed browser/Office/Desktop disposal
remain blocked on an owner-approved ADR selecting transport, process identity,
attestation, installation, and lifecycle ownership. Shared protected-provider
orchestration and authoritative PDF source-to-box intervals remain separate
Phase 8 units. No outward-facing action or real credential was used.
