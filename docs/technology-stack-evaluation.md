# Technology Stack Evaluation

Evaluation target: AI Guard 2.5.0
Branch: `research/technology-evaluation`
Baseline: `origin/main` at `01aa793`
Scope: evidence-based technology evaluation only. Runtime APIs, defaults,
`VERSION`, the shared core, and the product architecture were not changed.

Evidence labels used below:

- **Production evidence**: existing runtime, package, CI, or performance gates.
- **SMOKE_ONLY**: a bounded experiment that proves mechanics, not quality or
  production readiness.
- **FAIL**: the stated experiment did not meet its gate.
- **BLOCKED**: the required external artifact, host, or approval was absent.

## 1. Executive conclusion

Keep the current architecture:

    storefronts -> FastAPI adapter -> pii_redactor shared core
                                      -> detectors, anonymizer, leak guard,
                                         provider boundary, restore/validate

Keep Python for the shared PII, Thai NLP, PDF, report, and privacy core.
Keep FastAPI for local and hosted HTTP, Tauri/Rust for the desktop shell,
JavaScript/TypeScript for storefronts, and Docker for hosted packaging.

Decisions from this evaluation:

- Keep the existing requirements and hash-locked installation paths.
- Keep `scripts/compare_finetuned_onnx.py` as an optional research harness.
- Do not add an ONNX production backend from this evidence. FP32 is
  `SMOKE_ONLY`; the temporary-model INT8 run is `FAIL`.
- Treat uv as a reversible migration candidate, not an adopted default.
- Keep Rust/PyO3, Go, free-threaded Python, and full core rewrites as future
  options only when a measured product requirement justifies them.

No ADR was added. This document records reversible evaluation results, not an
architecture decision that is expensive to undo.

## 2. Current production architecture

The repository has one shared core under `pii_redactor/`. `app/server.py`
adapts the core for local, hosted, Office, and browser-facing paths. Storefronts
do not own separate detection, vault, provider, or restore implementations.

    browser extension / CLI / demo / Office Add-in
                     |
    Tauri desktop -> Python sidecar HTTP
                     |
             app/server.py
                     |
    detect_all -> anonymize -> outbound leak guard
                     -> provider -> restore/validate

| Boundary | Current technology | Evidence-based reason |
| --- | --- | --- |
| Shared PII and privacy core | Python 3.11+ | Existing Thai NLP, PDF, report, and provider ecosystem |
| Thai detection | PyThaiNLP, CRFsuite, regex/checksum layers | Current source-span and structured-ID behavior |
| Optional fine-tuned NER | PyTorch and Transformers | Opt-in external artifact; not bundled |
| Optional scanned-PDF OCR | PaddlePaddle and PaddleOCR | Separate optional dependency tier |
| HTTP adapter | FastAPI and Uvicorn | Shared local, hosted, Office, and browser contract |
| Desktop shell | Tauri 2 and Rust | Native lifecycle, watchdog, and packaging boundary |
| Storefronts | JavaScript/TypeScript and Vite | Browser and Microsoft 365 surfaces |
| Hosted packaging | Docker | Existing stateless deployment path |

The local pseudonym mapping remains in memory inside the core. Browser and
Office clients may hold `session_id`, never the mapping or provider
credentials. Hosted AI processing is stateless by default and is not described
as keeping raw PII on the user's device.

## 3. Existing production baseline

### Environment and gates

Measurements used Windows 11 build 26200, repository Python 3.13.14, Node
24.15.0, Rust/cargo 1.97.0, and uv 0.11.18. Docker CLI was present, but the
local Docker Desktop Linux daemon was unavailable. Go and .NET were not
installed.

| Gate | Result |
| --- | --- |
| Python pytest | 1,482 passed, 5 skipped, 1 warning |
| Ruff lint | Passed |
| Ruff format | 210 files already formatted |
| Version and release readiness | Passed; all version targets remain 2.5.0 |
| Root JavaScript | 60 tests passed; syntax checks passed |
| Tauri/Rust | 19 tests passed |
| Office Add-in | 65 tests passed; typecheck, build, manifests, and package passed |
| Sidecar smoke | Health, sanitize, and port cleanup passed |
| Docker CI baseline | 320,978,341 bytes; ready after 2 s; five-endpoint smoke passed |

### In-process performance

The existing local performance gate is production-core evidence. Its memory
value is the maximum of RSS samples taken after each measured operation, not a
continuously sampled instantaneous peak.

| Operation | Historical median | Current final run |
| --- | ---: | ---: |
| detect | 5.73 ms | 5.18 ms |
| sanitize | 10.08 ms | 9.57 ms |
| restore | 0.28 ms | 0.31 ms |
| PDF redaction | 67.67 ms | 67.72 ms |
| RSS sample maximum | 151.4 MiB | 151.3 MiB |

The final run stayed within the 20% time and 15% memory budgets. Earlier
outliers show measurement variance; no baseline move is justified.

### Startup and packaging

- Fresh `import app.server` median: 676.88 ms. This is import/startup time,
  not fine-tuned model loading.
- Local Uvicorn: health response after 1,203.58 ms, first sanitize 501.01 ms,
  warm sanitize median 4.32 ms, warm maximum 6.79 ms.
- PyInstaller sidecar: 137,558,149 bytes / 131.19 MiB; smoke passed.
- Published v2.5.0 assets ranged from 68,981,723 bytes for the ARM archive to
  172,308,984 bytes for the Linux AppImage.
- No local Docker image build or cold-start measurement was possible; CI is the
  authoritative Docker evidence.

Model-dependent production evidence is reported in section 6. It remains
`BLOCKED` for absolute accuracy because no approved external model and gold set
were available.

## 4. Profiling observations

On the current synthetic Thai fixture, cProfile over 30 detection calls
attributes the largest measured share to Thai tokenization and NER:

| Path | Cumulative profile time | Interpretation |
| --- | ---: | --- |
| `detect_all` | 0.756 s | Top-level detector |
| `detect_tb` | 0.743 s | Thai contextual detector |
| `sent_tokenize` | 0.488 s | Thai sentence/token path |
| `crfcut.segment` | 0.477 s | CRFsuite segmentation |
| `word_tokenize/newmm` | 0.462 s | Thai dictionary tokenization |
| Thai NER candidate path | 0.216/0.210 s | `thainer` and candidate generation |

The profile also attributes meaningful work to PDF extraction and image/text
conversion on the small fixture: `redact_pdf` 0.376 s, Pillow quantization
0.239 s, and PDF text extraction 0.239 s. These values locate work; they do
not establish production throughput.

The evidence does not identify FastAPI dispatch, localhost HTTP, the Tauri
command boundary, or a small pure-Python overlap routine as the dominant cost.
Future optimization should start with larger representative Thai/PDF corpora,
dictionary initialization, tokenization reuse, or PDF conversion.

## 5. Technology decision matrix

| Option | Decision | Evidence |
| --- | --- | --- |
| Keep Python/FastAPI/Tauri/Docker | Adopt | Running system, shared core, green gates, and lowest migration risk |
| Optional ONNX Runtime backend | Future POC | Reversible boundary; only smoke evidence exists and INT8 failed |
| Supplemental uv workflow | Evaluate later | Fast environment creation, but loose resolution differs from the committed lock |
| Rust/PyO3 hot path | Future POC | Profile does not yet justify a native rewrite |
| Go hosted gateway | Future option | No measured gateway bottleneck or platform requirement |
| Full Rust, Go, Node, .NET, or C++ core | Reject now | Would reproduce Thai NLP, model labels, PDF coordinates, Thai shaping, and privacy contracts |
| FastAPI/sidecar replacement | Reject now | No evidence that the transport/process boundary is the cost center |
| Frontend framework rewrite | Reject now | No UI, bundle, or test bottleneck |
| Free-threaded Python | Reject now | Native dependency compatibility and concurrency benefit are unproven |

The decision is about evidence quality and reversibility. It does not claim
that future hardware, models, deployment constraints, or native implementations
cannot change the ranking.

## 6. ONNX smoke evaluation

### Harness contract

The current fine-tuned adapter returns character-offset spans, uses a fast
tokenizer, 240-token windows, a 60-token overlap, maximum-confidence voting,
BIO decoding, and optional per-label thresholds. The harness reuses the
production window/overlap constants and compares the logical output:

    list[tuple[int, int, str, float]]

It writes generated ONNX files and numeric JSON only under ignored `tmp/`,
uses synthetic probes, and never uses `blind-v1`. Its result statuses are:

- no model: `SKIPPED` (exit 0), or exit 2 with `--require-model`;
- invalid existing artifact or evaluation error: `FAIL`;
- successful bounded smoke: `SMOKE_ONLY`;
- complete non-smoke evaluation: `PASS`.

### Model and training-pipeline review

No valid external AI Guard artifact was found through
`AIGUARD_FINETUNED_MODEL_DIR`, bounded repository model folders, or the
inspected Hugging Face cache. The available ThaiNER base checkpoint was
rejected because its 36-label mapping is not the product's fine-tuned mapping.

The repository training lane was checked directly against `training/`:

- `training/train.py` uses base model
  `pythainlp/thainer-corpus-v2-base-model` and a fresh 11-label BIO space:
  `O` plus `B-`/`I-` for PERSON, LOCATION, ORGANIZATION, DATE, and STUDENT_ID.
- The default seed is `20260728`; max length is 256; the default run uses
  Trainer checkpoint selection on dev span-F1 and never benchmark gold.
- `training/generate_data.py` uses synthetic lexicons, a held-out value shard
  and template space for dev, O-only hard negatives, counterfactual pairs, and
  optional ThaiNER rehearsal. It rechecks contamination against gold values.
- The tracked manifest records 6,828 train documents / 16,310 entities and
  680 dev documents / 1,720 entities with the same seed and content hashes.
- `training/calibrate_thresholds.py` reads synthetic dev only and chooses the
  highest grid threshold within 0.005 recall loss. It writes
  `thresholds.json` beside the model artifact.
- The pipeline saves standard Hugging Face config, weight, tokenizer, and
  training metadata files. Weights and thresholds remain external to the repo.
- Base-model, rehearsal-dataset, and all training-dependency revisions are
  not fully pinned. The lane is executable, but not fully lock-reproducible.

### Smoke evidence and interpretation

A previous bounded one-step training run created a temporary artifact in about
10.22 s. Its classifier head was freshly initialized. No additional training
or quantization was run in this cleanup pass.

| Evidence | Status | Result |
| --- | --- | --- |
| Training artifact | `SMOKE_ONLY` | Mechanics only; not a quality candidate |
| PyTorch vs ONNX FP32 | `SMOKE_ONLY` | All 12 synthetic probes agreed on spans, labels, and threshold decisions |
| PyTorch/ONNX absolute accuracy | `BLOCKED` | No approved raw-label gold JSONL; no precision, recall, or F1 claim |
| Dynamic ONNX INT8 | `FAIL` | Current smoke model and current quantization method failed differential gates |
| Sidecar/installer benefit | `BLOCKED` | No sidecar or installer delta was measured |

FP32 export took 4,560.23 ms. The maximum FP32 confidence delta was
`1.27e-6`; that is differential mechanics, not absolute accuracy.

The current dynamic INT8 smoke run failed differential span, label, and
threshold gates. Re-evaluation requires a production-quality model. This
result rejects the current smoke evidence and method for production; it does
not prove that every production-quality model or quantization strategy will
fail.

### Performance and memory limits

The temporary artifact was approximately 420 MB. PyTorch and ONNX were loaded
and measured in separate subprocesses:

| Worker | Load | First probe set | Warm median | Current RSS samples |
| --- | ---: | ---: | ---: | ---: |
| PyTorch | 9,135.665 ms | 1,396.691 ms | 84.995 ms/case | 478.2-848.7 MiB |
| ONNX FP32 | 8,813.201 ms | 1,060.572 ms | 59.771 ms/case | 897.9-920.6 MiB |

These are **current RSS samples**, not a continuously sampled maximum or total
runtime memory. The one-step artifact is not representative of a final
optimized production artifact, and these samples do not justify an ONNX
memory advantage or disadvantage.

## 7. uv evaluation

uv 0.11.18 was evaluated in ignored temporary environments without changing
requirements, CI, Docker, or the sidecar workflow:

| Experiment | Result |
| --- | --- |
| Environment creation | 270.3 ms |
| Core/web installation | 3,620.33 ms |
| ML installation | 14,737.5 ms |
| OCR installation | 4,971.29 ms |
| All-optional `uv pip check` | Passed for 108 packages |
| Hash compilation | 1,197 lines / 43 resolved packages |

The environment resolved newer packages than the committed hash lock. uv is
useful for lock generation and a future migration pilot, but it is not an
adopted default. Adoption requires equivalence across requirements, CI,
Docker, ML/OCR tiers, and the sidecar build.

## 8. Rejected rewrites

These options are rejected for the current product, not permanently:

- Full Rust or C++ core: migration would reproduce Thai NLP, model-backed
  inference, PDF coordinates, Thai shaping, privacy behavior, and packaging.
- Node/TypeScript or .NET core: storefront syntax or Windows integration does
  not replace the current Thai NLP/PDF ecosystem.
- FastAPI/sidecar replacement: a new transport would create another path
  without evidence of a boundary bottleneck.
- Go gateway: reasonable only after a concrete hosted gateway or rate-limit
  requirement appears.
- Free-threaded Python: requires a supported native-dependency matrix and a
  measured concurrency benefit.
- Frontend framework rewrite: no UI or bundle problem was measured.

## 9. Recommended architecture

Keep one core and make future optimization optional at explicit boundaries:

    flowchart LR
      S[Browser CLI Office Demo] --> A[FastAPI adapter]
      T[Tauri Rust shell] --> P[Python sidecar HTTP]
      A --> C[pii_redactor shared core]
      P --> C
      C --> D[Thai and structured detectors]
      C --> N[Anonymizer and in-memory vault]
      C --> L[Outbound leak guard]
      C --> R[Provider and restore/validate]
      C --> F[PDF extraction and coordinate-preserving redaction]
      N -. local session only .-> V[session_id boundary]
      C -. optional external model .-> O[PyTorch now; ONNX POC later]
      A -. stateless hosted mode .-> H[Docker and reverse proxy]

An eventual ONNX path must implement the same span interface, remain behind
explicit configuration, preserve source offsets, and never move pseudonym
mappings, credentials, raw provider bodies, or restored answers into clients or
logs.

## 10. Remaining evidence required

1. Obtain a production-quality external 11-label model and an approved
   synthetic raw-label gold set.
2. Pin the base model, rehearsal dataset revision, and training dependency
   versions before calling full retraining reproducible.
3. Run FP32 differential plus precision/recall/F1 and offset checks. Only then
   investigate INT8, using the FP32-before-INT8 gate.
4. Measure model load, warm inference, current RSS samples, artifact size,
   sidecar impact, installer impact, and representative Thai/PDF throughput.
5. Revisit uv only after all installation and CI tiers are equivalent.
6. Revisit Go or native hot paths only when a measured product boundary or
   platform requirement justifies them.

## 11. Commands and environment

Repository and core gates:

    git status --short --branch
    git fetch origin
    $env:PYTHONUTF8='1'
    ./.venv/Scripts/python.exe -m pytest -q
    ./.venv/Scripts/python.exe -m ruff check .
    ./.venv/Scripts/python.exe -m ruff format --check .
    ./.venv/Scripts/python.exe scripts/check_version.py
    ./.venv/Scripts/python.exe scripts/check_release_readiness.py

Production measurements:

    ./.venv/Scripts/python.exe scripts/measure_perf.py --iterations 5 --json tmp/technology-baseline.json
    ./.venv/Scripts/python.exe -c "import app.server"
    ./.venv/Scripts/python.exe -m cProfile -s cumulative ...
    uvicorn app.server:app --host 127.0.0.1 --port 18252 --log-level warning

Optional training smoke used for the evidence above (do not treat it as
accuracy evaluation):

    ./.venv/Scripts/python.exe training/train.py --data training/data --out tmp/technology-model-smoke --max-steps 1 --epochs 1 --batch 1 --grad-accum 1

Harness without a model:

    ./.venv/Scripts/python.exe scripts/compare_finetuned_onnx.py --list-cases
    ./.venv/Scripts/python.exe scripts/compare_finetuned_onnx.py

Harness with an approved external model:

    $env:AIGUARD_FINETUNED_MODEL_DIR='path/to/external-model'
    ./.venv/Scripts/python.exe scripts/compare_finetuned_onnx.py --model-dir path/to/external-model --require-model --output-dir tmp/technology-onnx
    ./.venv/Scripts/python.exe scripts/compare_finetuned_onnx.py --model-dir path/to/external-model --require-model --output-dir tmp/technology-onnx --quantize

The second command is valid only after the first command's FP32 differential
gate passes. An approved synthetic gold JSONL may be added with
`--gold-jsonl`; agreement with PyTorch is never substituted for gold accuracy.

## 12. Limitations

- PR #106 was merged into `main`, and this branch was refreshed with a normal
  merge from `origin/main`; no rebase was performed.
- No valid external production-quality model or approved raw-label gold set
  was available. Absolute model accuracy is therefore `BLOCKED`.
- The training pipeline is executable but upstream revisions and dependency
  pins are incomplete.
- The ONNX smoke used a freshly initialized one-step classifier head. Its
  current RSS samples and approximately 420 MB artifact are not production
  resource evidence.
- No sidecar/installer ONNX delta, concurrent load soak, local Docker cold
  start, live provider acceptance, or real browser/Office host acceptance was
  run in this evaluation.
- No model weights, ONNX files, binaries, large datasets, secrets, personal
  documents, or new blind datasets were added to the branch.
