# Technology Stack Evaluation

Evaluation target: AI Guard version 2.5.0
Branch: research/technology-evaluation
Baseline commit: origin/main at 97ba756
Scope: evidence-based technology evaluation only. No runtime API, default
engine, product version, or public architecture contract was changed.

## 1. Executive conclusion

Keep the current architecture:

    storefronts -> FastAPI adapter -> pii_redactor shared core
                                      -> detectors, anonymizer, leak guard,
                                         provider boundary, restore/validate

Keep Python as the shared PII, Thai NLP, PDF, report, and privacy core. Keep
FastAPI as the local and hosted HTTP adapter, Tauri/Rust as the desktop shell,
TypeScript/JavaScript as the storefront layer, and Docker as the hosted
deployment unit.

Adopt now:

- Keep the existing architecture and optimize measured boundaries.
- Keep the existing requirements and hash-locked installation paths.
- Keep the optional ONNX evaluation harness in
  scripts/compare_finetuned_onnx.py.
- Use uv as a reversible development and lock-generation experiment, not as a
  replacement for the current requirements workflow yet.

Run a proof of concept:

- ONNX Runtime FP32, then dynamic INT8 only after FP32 differential validation,
  when an external fine-tuned model and an approved synthetic gold set are
  available.
- A uv migration pilot only after the generated lock can be proven equivalent
  across CI, Docker, ML/OCR optional tiers, and the PyInstaller sidecar build.

Keep as future options:

- Rust/PyO3 for a specific hot path only if a representative profile proves a
  Python-owned path is responsible for a material share of the budget.
- A Go gateway only if a hosted platform requirement introduces a gateway
  bottleneck or operational boundary that FastAPI cannot meet.
- Free-threaded Python only after every native dependency is proven compatible
  and a concurrency benchmark demonstrates a real benefit.

Reject for the current product:

- A full Rust, Go, Node/TypeScript, C#/.NET, or C++ rewrite of the shared core.
- Replacing FastAPI or the Python sidecar solely to reduce process count.
- A frontend framework rewrite without a measured UI or bundle problem.

The current polyglot stack is justified at its boundaries: Rust/Tauri owns the
desktop shell, JavaScript/TypeScript owns browser and Office surfaces, and
Python owns one shared detection and privacy implementation. The evidence does
not justify moving that core into another language.

## 2. Current architecture

The repository has one shared core under pii_redactor/. app/server.py provides
the FastAPI adapter and the provisional local worker adapter. Storefronts call
the shared path; they do not own independent detector, vault, or provider
implementations.

    browser extension / CLI / demo / Office Add-in
                     |
    Tauri desktop -> Python sidecar HTTP
                     |
             app/server.py
                     |
    SessionService or stateless request path
                     |
    detect_all -> anonymize -> outbound leak guard
                     -> provider -> restore/validate

The main runtime technologies are:

| Boundary | Current technology | Reason it remains in scope |
| --- | --- | --- |
| Shared PII and privacy core | Python 3.11+ | Existing Thai NLP, CRFsuite, PDF, report, and provider ecosystem |
| Thai detection | PyThaiNLP, CRFsuite, regex/checksum layers | Current accuracy and source-span behavior |
| Optional fine-tuned NER | PyTorch and Transformers | External model is opt-in and not bundled |
| Optional scanned-PDF OCR | PaddlePaddle and PaddleOCR | Separate optional tier |
| HTTP adapter | FastAPI and Uvicorn | Existing local, hosted, Office, and browser contract |
| Desktop shell | Tauri 2 and Rust | Native window, lifecycle, watchdog, and packaging boundary |
| Storefronts | JavaScript/TypeScript and Vite | Browser and Microsoft 365 integration |
| Hosted packaging | Docker | Existing reverse-proxy and stateless deployment path |

The local mapping is held in memory inside the core. Browser and Office clients
may hold a session_id but never receive the mapping or provider credentials.
The hosted path is stateless by default and must not be described as keeping
raw PII on the user's device.

The tracked source inventory on this baseline was 194 Python files, 26
JavaScript files, 18 TypeScript files, and 7 Rust files. That count describes
the existing surface; it is not a justification for duplicating the core.

## 3. Current measured baseline

### Environment

Measurements were run on Windows 11 build 26200 with:

| Item | Value |
| --- | --- |
| Repository Python | .venv Python 3.13.14 |
| Node | 24.15.0 |
| Rust/cargo | 1.97.0 |
| uv | 0.11.18 |
| Docker | CLI present; local Docker Desktop Linux daemon unavailable |
| Go/.NET | Not installed on the evaluation machine |
| Fine-tuned model | AIGUARD_FINETUNED_MODEL_DIR unset |

The Office package declares Node 22.12 through <23. The local machine used
Node 24, so the Office command emitted an engine warning; the successful
Node 22 CI job is the authoritative compatibility result.

### Tests and static checks

| Check | Result |
| --- | --- |
| Python pytest | 1473 passed, 5 skipped, 1 warning in 193.39 s |
| Ruff lint | All checks passed |
| Ruff format | 208 files already formatted |
| Version check | All version-bearing files match 2.5.0 |
| Release readiness | Version targets, changelog, and release metadata agree |
| Root JavaScript tests | 60 tests passed in 12 files |
| Desktop JavaScript syntax | app.js and api.js passed node --check |
| Tauri/Rust tests | 19 passed, 0 failed |
| Office typecheck | Passed |
| Office tests | 65 tests passed in 9 files |
| Office build | Vite build passed |
| Office manifests | Upstream and local validation passed |
| Office package | 2.5.0 zip created and verified |
| Sidecar smoke | Health, sanitize, and port cleanup passed |

The only Python test warning was StarletteDeprecationWarning for the current
httpx/TestClient combination. It did not fail a test.

### In-process performance

The committed historical baseline in perf/baseline.json is:

| Operation | Historical median | Peak RSS |
| --- | ---: | ---: |
| detect | 5.73 ms | 151.4 MiB |
| sanitize | 10.08 ms | 151.4 MiB |
| restore | 0.28 ms | 151.4 MiB |
| pdf_redact | 67.67 ms | 151.4 MiB |

Command:

    $env:PYTHONUTF8='1'
    ..venvScriptspython.exe scriptsmeasure_perf.py --iterations 5 --json tmp	echnology-baseline.json

The first post-build run in this session reported detect 6.81 ms, sanitize
13.10 ms, restore 0.79 ms, pdf_redact 110.36 ms, and 151.3 MiB. The command
correctly returned a regression status. The committed baseline was not
updated.

Three additional runs showed the environment-sensitive range below:

| Operation | Repeat range | Interpretation |
| --- | ---: | --- |
| detect | 5.22-5.88 ms | Within the 20% time budget |
| sanitize | 10.27-11.14 ms | Within the 20% time budget |
| restore | 0.33-0.61 ms | One run was noisy; later runs were 0.33 ms |
| pdf_redact | 70.11-71.31 ms | Within the 20% time budget |
| peak RSS | 150.6-151.0 MiB | Within the 15% memory budget |

This is evidence of measurement variance, not evidence of a runtime
improvement. No baseline move is justified by this evaluation.

The final validation run returned detect 5.18 ms, sanitize 9.57 ms, restore
0.31 ms, pdf_redact 67.72 ms, and 151.3 MiB RSS, with the existing script
reporting within budget.

### Process startup and HTTP latency

The import-only measurement ran five fresh Python processes importing
app.server: 637.01, 668.54, 676.88, 830.17, and 1891.32 ms; median
676.88 ms. This includes Python/module import and is not fine-tuned model load.

A fresh local Uvicorn process on 127.0.0.1:18252 returned:

| Measurement | Result |
| --- | ---: |
| Process start to /api/health | 1203.58 ms |
| First synthetic /api/sanitize | 501.01 ms |
| Warm sanitize median over 10 calls | 4.32 ms |
| Warm sanitize maximum | 6.79 ms |

The first request includes lazy initialization and should not be compared with
the warm request as if it were only HTTP overhead.

### Packaging and deployment

The local PyInstaller sidecar build completed in 131.3 s. Both the one-file
build and staged Tauri binary were 137,558,149 bytes (131.19 MiB). The build
reported optional hidden-import and unauthenticated Hugging Face Hub analysis
warnings, but it completed and the executable smoke test passed. No weights
were included.

Published v2.5.0 assets provide a separate release baseline:

| Asset | Bytes |
| --- | ---: |
| Windows x64 setup | 69,456,194 |
| macOS aarch64 DMG | 69,049,796 |
| Linux amd64 AppImage | 172,308,984 |
| Linux amd64 deb | 96,324,058 |
| Linux aarch64 tar.gz | 68,981,723 |

The local Docker daemon was unavailable, so a local image build and local
cold-start measurement were not run. The successful CI run 30728747436 built
an image of 320,978,341 bytes, reported the container up after 2 s, and passed
the five-endpoint contract smoke. That is CI evidence, not a local Docker
benchmark.

### Fine-tuned model

No model directory was available through AIGUARD_FINETUNED_MODEL_DIR. Therefore
model load time, model inference time, model size, PyTorch accuracy, ONNX
accuracy, ONNX memory, and ONNX package/sidecar deltas are intentionally
unexecuted. No result is fabricated from a missing artifact.

## 4. Actual bottlenecks

The strongest evidence comes from cProfile over 30 detection calls on the
repository's synthetic Thai fixture:

| Path | Cumulative time in profile | Meaning |
| --- | ---: | --- |
| detect_all | 0.756 s | Top-level detector |
| detect_tb | 0.743 s | Thai contextual detector |
| sent_tokenize | 0.488 s | PyThaiNLP sentence/token path |
| crfcut.segment | 0.477 s | CRFsuite token segmentation |
| word_tokenize/newmm | 0.462 s | Thai dictionary tokenization |
| _ner_candidates / thainer | 0.216/0.210 s | Thai NER candidate path |

The profile also showed a one-time 0.374 s Thai dictionary-trie construction.
That is a startup or first-use concern, not a reason to rewrite the detector
in Rust without measuring a warmed process and a larger corpus.

A profile of the existing full performance harness showed PDF-specific work:

- redact_pdf accumulated 0.376 s over the profiled calls.
- Pillow ImagingCore.quantize accumulated 0.239 s.
- PDF text extraction accumulated 0.239 s, including pypdfium2 text extraction.
- pypdf page text-map extraction accumulated 0.140 s.

The PDF profile has cProfile overhead and uses a small fixture, so these values
locate work rather than establish production throughput. They do establish
that PDF image/text conversion and Thai tokenization are better optimization
targets than a thin FastAPI replacement or a small Python span utility.

Measured maintenance costs are also concrete:

- The core has separate web, ML, OCR, build, and platform dependency tiers.
- The sidecar build excludes large optional ML/OCR modules and still produces a
  131.19 MiB executable.
- CI covers Python, core-only Python, Windows, Ubuntu, Docker, Rust, browser/
  desktop JavaScript, Office Node 22, and packaging.
- The local Office toolchain is Node-version-sensitive.
- A loose uv resolution produced newer packages than the committed hash lock,
  so uv alone does not make the current requirements reproducible.

There is no measurement showing that FastAPI request dispatch, the localhost
HTTP boundary, or the Tauri command boundary is the dominant cost.

## 5. Technology options considered

### Option A: Keep the current architecture

Strengths:

- One shared detector, anonymizer, vault, leak guard, provider boundary, and
  PDF path serves all storefronts.
- The full existing Python contract has 1473 passing tests and all current CI
  lanes are green on main.
- PyThaiNLP and CRFsuite already provide Thai segmentation and NER behavior
  that a rewrite would need to reproduce at source-span level.
- FastAPI is reused for local and hosted paths and is observable with ordinary
  HTTP tools.
- Tauri/Rust provides a narrow native boundary without duplicating PII logic.

Weaknesses:

- Python import and first-use startup are measurable costs.
- The PyInstaller sidecar is large.
- Optional ML/OCR dependency tiers increase install and CI complexity.
- The PDF path has a meaningful conversion/redaction cost.

The current combination is justified because the language boundaries match
product surfaces. The measured core bottlenecks do not justify changing those
boundaries.

### Option B: Rewrite the shared core in Rust

Rust could improve memory control and native packaging in a new implementation,
but the repository would need replacements for PyThaiNLP segmentation,
CRFsuite behavior, Transformers inference, PDFium extraction/redaction,
ReportLab/HarfBuzz Thai shaping, and the existing character-offset semantics.
The largest risk is a silent accuracy or offset regression, not raw CPU speed.

The existing Rust code is valuable as the desktop shell. It is not evidence
that the shared PII core should be rewritten.

### Option C: Add a Go hosted gateway

Go is well suited to a small authentication, rate-limit, and routing gateway.
There is no measured gateway bottleneck and Go was not installed locally.
Adding Go would retain the Python core behind another service, adding routing,
deployment, observability, and trust-boundary work. It becomes reasonable only
when a concrete hosted platform requirement calls for it.

### Option D: Move the core to Node.js or TypeScript

This would share syntax with browser and Office surfaces, but it would not
share the Thai NLP, CRFsuite, PyTorch, PDFium, Pillow, ReportLab, or HarfBuzz
behavior that currently defines the core. It would create a second accuracy
implementation or force a large native-extension strategy. The storefront
layer already gets the benefits of TypeScript where those benefits apply.

### Option E: Move the product to C#/.NET

.NET could be attractive for a Windows-first enterprise integration or a
future Office-native component. It does not provide a low-risk replacement for
the current Thai NLP/PDF core, and dotnet was not available for a local
prototype. The current cross-platform desktop and hosted contracts would still
need to be preserved.

### Option F: Replace PyTorch inference with ONNX Runtime

ONNX is the highest-priority experiment because it can potentially reduce
runtime dependencies, memory, startup, and sidecar size while leaving the
shared Python contract in place. It is not production-ready until the external
model passes differential and accuracy gates.

### Option G: Rust/PyO3 for selected hot paths

The profile points to PyThaiNLP/CRFsuite and PDF/Pillow work, not a small pure
Python overlap routine. Moving Thai NER rules to Rust would move the accuracy
and maintenance boundary without evidence. A future isolated POC must preserve
the Python API, have a pure-Python fallback, pass differential tests, and
show a material improvement after packaging cost.

### Option H: Adopt uv

uv materially improves clean environment creation and can generate hash-pinned
lock material, but the current experiment resolved loose requirements to newer
packages than the committed lock. It is a promising supplemental workflow,
not a reason to delete requirements files or change CI in this evaluation.

### Option I: Free-threaded Python

No free-threaded interpreter was installed or discoverable through py -0p.
PyThaiNLP, python-crfsuite, PyTorch, Transformers, PDFium, Pillow, ReportLab,
HarfBuzz, FastAPI, and packaging compatibility were therefore not proven. The
current evidence is insufficient to accept the native-extension risk.

### Option J: Replace FastAPI or the local sidecar

Starlette, Flask, Litestar, gRPC, named pipes, direct Tauri commands, embedded
Python, and a Rust-native service could all be built, but each would either
change the existing HTTP contract or create a second execution path. The
localhost HTTP boundary serves the desktop, browser, Office, and hosted
adapter use cases and is easy to inspect. No measurement shows it is the
dominant bottleneck.

### Frontend and C++

The existing JavaScript/TypeScript storefronts are small and their tests/builds
are green. There is no measured UI or bundle bottleneck for a framework rewrite.
C++ could offer native control but would have the same Thai NLP/PDF accuracy
and migration problem as a Rust rewrite with a larger portability burden.

## 6. Decision matrix

For P, M, S, Pack, and Deploy, 1 is little benefit and 5 is strong benefit.
For AR, PR, MI, MA, and Test, 1 is low risk/effort/burden and 5 is high
risk/effort/burden. For Eco, Cross, and Rev, 1 is poor fit/reversibility and
5 is strong fit/reversibility.

| Option | P | M | S | Pack | Deploy | AR | PR | MI | MA | Eco | Cross | Test | Rev | Decision |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| A. Keep Python/FastAPI/Tauri | 3 | 3 | 3 | 3 | 4 | 1 | 1 | 1 | 2 | 5 | 4 | 1 | 5 | Adopt now |
| B. Rust core rewrite | 5 | 4 | 4 | 4 | 3 | 5 | 3 | 5 | 5 | 2 | 4 | 5 | 1 | Reject now |
| C. Go hosted gateway | 2 | 3 | 3 | 2 | 4 | 2 | 2 | 4 | 4 | 4 | 4 | 4 | 3 | Future option |
| D. Node/TypeScript core | 2 | 3 | 4 | 3 | 4 | 5 | 3 | 5 | 4 | 2 | 4 | 5 | 1 | Reject now |
| E. C#/.NET core | 3 | 3 | 3 | 3 | 3 | 4 | 2 | 5 | 4 | 3 | 3 | 5 | 1 | Reject now |
| F. ONNX optional backend | 4 | 4 | 4 | 4 | 4 | 3 | 1 | 3 | 3 | 3 | 4 | 4 | 4 | Run POC |
| G. Rust/PyO3 hot paths | 4 | 3 | 2 | 2 | 2 | 4 | 2 | 4 | 4 | 3 | 3 | 4 | 3 | Future POC |
| H. uv supplemental workflow | 2 | 2 | 2 | 3 | 4 | 1 | 1 | 2 | 2 | 4 | 4 | 2 | 5 | Adopt as POC |
| I. Free-threaded Python | 2 | 2 | 2 | 2 | 2 | 4 | 2 | 4 | 4 | 2 | 2 | 4 | 3 | Reject now |
| J. FastAPI/sidecar replacement | 2 | 2 | 3 | 2 | 2 | 4 | 3 | 4 | 4 | 3 | 3 | 4 | 2 | Reject now |
| Frontend framework rewrite | 2 | 2 | 2 | 2 | 2 | 3 | 1 | 4 | 4 | 4 | 4 | 4 | 2 | Reject now |
| C++ core rewrite | 4 | 4 | 4 | 2 | 3 | 5 | 3 | 5 | 5 | 3 | 3 | 5 | 1 | Reject now |

The scores are grounded in the measured boundaries:

- A has the strongest ecosystem, cross-platform, reversibility, and test
  evidence because it is the running system with green gates.
- F has the highest reversible upside among core-preserving options, but its
  performance and memory scores are potential benefits, not measured results.
- H has direct installation evidence but still needs lock and CI equivalence.
- B, D, E, and C++ have high migration/test scores because they must reproduce
  Thai tokenization, model labels, PDF coordinates, Thai shaping, and privacy
  contracts.
- G has no candidate hot path that the profile proves is worth a native build.
- J adds risk without evidence that the HTTP or sidecar boundary is the cost
  center.

## 7. ONNX Runtime findings

The current fine-tuned adapter uses a fast tokenizer with character offsets,
240-token windows, a 60-token stride, max-confidence voting for overlapping
windows, BIO decoding, and optional per-label thresholds loaded beside the
external model. The optional harness mirrors this logical output:

    list[tuple[int, int, str, float]]

The experiment was not executed because AIGUARD_FINETUNED_MODEL_DIR was unset.
Consequently the following remain unexecuted:

- PyTorch model load and inference timing.
- ONNX export success and model compatibility.
- FP32 span, label, character-offset, confidence, precision, recall, and F1
  comparison.
- INT8 span/label/offset/confidence and accuracy comparison.
- First-load time, warm inference, RSS, model size, runtime dependency size,
  sidecar size, and installer size deltas.

The new harness is scripts/compare_finetuned_onnx.py. It includes synthetic
probes for empty input, Thai names, Thai addresses, organizations, dates,
student IDs, long stride, overlapping windows, Unicode offsets, combining
Thai marks, unknown labels, and threshold filtering. It never uses blind-v1
as an evaluation dataset.

Required command when an external model is available:

    $env:AIGUARD_FINETUNED_MODEL_DIR='C:/external/model'
    ..venvScriptspython.exe scriptscompare_finetuned_onnx.py --model-dir C:/external/model --output-dir tmp	echnology-onnx

Only after FP32 differential validation passes:

    ..venvScriptspython.exe scriptscompare_finetuned_onnx.py --model-dir C:/external/model --output-dir tmp	echnology-onnx --quantize

An approved synthetic gold JSONL can be supplied with --gold-jsonl to report
exact-span precision, recall, and F1. The harness treats the PyTorch output as
the current reference for differential checks, but it does not treat reference
agreement as accuracy. The existing engine remains the default and no ONNX
configuration was added to production code.

Recommendation: run this as a POC. Adopt ONNX only if it preserves the
required accuracy and source-offset gates and provides a material operational
benefit after runtime and sidecar measurements.

## 8. uv findings

uv 0.11.18 was tested in ignored tmp/technology-uv without changing the
requirements files or committed locks.

| Experiment | Result |
| --- | --- |
| Clean Python 3.13 environment | Created in 270.3 ms |
| Core plus web install | 3,620.33 ms |
| Core plus web uv pip check | Passed |
| Focused tests | 152 passed in 2.18 s; measured command duration 4.93 s |
| ML install | 14,737.5 ms |
| OCR install | 4,971.29 ms |
| All optional uv pip check | Passed for 108 packages |
| Hash lock generation | 1,197 lines; 43 resolved packages |

The uv environment selected CPython 3.13.12, while the repository .venv uses
3.13.14. The optional environment ended with torch 2.13.0, transformers 5.14.1,
paddleocr 3.7.0, and paddlepaddle 3.2.2. It did not contain onnx or
onnxruntime because those packages are not in the current requirements tiers.
Paddle also emitted a no-ccache warning during import.

The loose requirements resolved newer packages than the existing hash-locked
requirements.lock. This demonstrates that uv is useful for generating a lock,
not that an unpinned uv sync is already equivalent to production installation.

Recommendation: keep requirements.txt, requirements-web.txt,
requirements-ml.txt, requirements-ocr.txt, requirements.lock, and the current
sidecar build during the next pilot. A future migration can add pyproject
dependency groups and uv.lock, then compare pip and uv in every CI tier and
Docker build before changing the default workflow.

## 9. Rust/PyO3 findings

Rust/Tauri is already the correct desktop-shell boundary. The existing Rust
tests passed 19 cases, and the shell owns native window/lifecycle concerns
without owning PII detection.

The profile does not identify span overlap resolution, structured identifier
scanning, or a small pure-Python normalization loop as a dominant cost. The
dominant work is PyThaiNLP/CRFsuite tokenization and NER, followed by PDF
extraction and Pillow conversion. Those paths depend on mature native or
model-backed libraries already called from Python.

No PyO3 prototype was built. A future candidate must:

- preserve the Python API and have a pure-Python fallback;
- pass entity-for-entity and offset differential tests;
- use larger representative Thai/PDF corpora;
- show a meaningful speed or memory improvement after build and packaging
  overhead is included.

Rust, Go, TypeScript, C#, and C++ therefore have clear boundary-specific uses,
but none has evidence for replacing the shared core today.

## 10. FastAPI and sidecar findings

FastAPI should remain the adapter. It preserves the existing HTTP contract for
local desktop, browser, Office, and hosted use, and it keeps the core
implementation reusable and inspectable. The measured warm local request was
4.32 ms median; the available evidence does not isolate FastAPI dispatch as a
dominant cost.

The Python sidecar should remain behind the Tauri shell. The current PyInstaller
one-file artifact is 131.19 MiB, which is a real packaging cost, but replacing
localhost HTTP with direct Tauri commands would create a second product path
for the desktop and reduce reuse with browser/Office/hosted clients.

Named pipes, Unix sockets, gRPC, embedded Python, a Rust-native local service,
Starlette, Flask, and Litestar remain possible alternatives, but none was
measured or required. A transport change should only follow a concrete
security, throughput, or packaging requirement.

For hosted deployment, keep the stateless FastAPI adapter and Docker image.
The successful CI image build and five-endpoint smoke are sufficient current
evidence; a separate Go or Rust gateway should wait for a platform requirement.

## 11. Rejected rewrite options

The following are rejected for the current product, not permanently impossible:

- Full Rust core: highest migration and accuracy risk; current profile does not
  prove enough benefit to reproduce the entire Thai/PDF/model stack.
- Node/TypeScript core: storefront code sharing does not replace the Thai NLP,
  CRFsuite, ML, PDF, and Thai shaping ecosystem.
- C#/.NET core: a potential future Windows integration layer, not a low-risk
  core replacement.
- C++ core: native speed potential is outweighed by portability, build,
  offset, accuracy, and maintenance costs.
- FastAPI/sidecar rewrite: no evidence that the HTTP/process boundary is the
  bottleneck; changing it would increase contract and packaging risk.
- Frontend framework rewrite: no UI, bundle, or test bottleneck.
- Free-threaded Python: no compatible interpreter or native dependency matrix
  was proven, and no concurrency benefit was measured.

## 12. Recommended architecture

The recommended architecture keeps one core and makes future optimizations
optional at explicit boundaries:

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

The ONNX path should be selected only by an explicit future configuration
choice and should implement the same logical span interface. It must never
move the pseudonym mapping, credentials, raw provider body, or restored answer
into a client or log.

## 13. Recommended next actions

1. Obtain an external fine-tuned model and an approved synthetic evaluation
   file. Run the FP32 harness, then INT8 only after FP32 passes.
2. Record exact span/label agreement, confidence delta, Unicode offsets,
   threshold behavior, gold precision/recall/F1, load/warm timing, RSS, model
   size, runtime size, and sidecar impact.
3. Profile larger representative Thai documents and PDFs. Optimize dictionary
   initialization, tokenization reuse, or PDF conversion only where a measured
   budget justifies it.
4. Run a separate uv migration pilot with pyproject dependency groups and a
   committed uv.lock only after requirements, Docker, CI, ML/OCR, and sidecar
   compatibility are proven.
5. Revisit Go only if the hosted platform specifies gateway, rate-limit, or
   concurrency requirements that the current adapter cannot meet.
6. Revisit free-threaded Python only with a supported interpreter and a full
   native-dependency matrix.

No ADR was added: this evaluation recommends a stable direction, but ONNX and
uv remain experiments and no production architecture decision needs to be
made from unexecuted model evidence.

## 14. Risks and limitations

- The fine-tuned model was unavailable, so ONNX accuracy and operational
  benefit remain unproven.
- The performance harness is small and local; one outlier exceeded the
  historical restore/PDF comparison while later runs were within budget.
- No local Docker daemon was available, so Docker cold-start evidence comes
  from CI and local Docker image sizing was not measured.
- Published installer sizes are v2.5.0 release artifacts, not a rebuild of
  this evaluation branch.
- The uv experiment used current loose requirement files and a temporary
  environment; it is not a replacement for the committed lock.
- No concurrent load test or multi-document memory soak was run.
- No free-threaded native-wheel compatibility was established.
- The PyInstaller build completed with optional-analysis warnings that should
  be cleaned up or documented before a packaging-focused release change.
- No model weights, ONNX files, binaries, large datasets, secrets, or personal
  documents were added to the branch.

## 15. Commands and evidence

Repository and baseline:

    git status --short --branch
    git switch -c research/technology-evaluation origin/main
    rg --files | Measure-Object
    $env:PYTHONUTF8='1'
    ..venvScriptspython.exe -m pytest -q
    ..venvScriptspython.exe -m ruff check .
    ..venvScriptspython.exe -m ruff format --check .
    ..venvScriptspython.exe scriptscheck_version.py
    ..venvScriptspython.exe scriptscheck_release_readiness.py

Existing performance and process measurements:

    ..venvScriptspython.exe scriptsmeasure_perf.py --iterations 5 --json tmp	echnology-baseline.json
    ..venvScriptspython.exe -c "import app.server"
    ..venvScriptspython.exe -m cProfile -s cumulative ...
    uvicorn app.server:app --host 127.0.0.1 --port 18252 --log-level warning

Packaging and storefront gates:

    ..venvScriptspython.exe scriptsuild_sidecar.py
    ..venvScriptspython.exe scriptssmoke_exe.py
    npm run test:js
    node --check srcapp.js
    node --check srcapi.js
    cargo test --manifest-path src-tauriCargo.toml
    npm run typecheck
    npm test
    npm run build
    npm run validate:manifest
    npm run validate:manifest:upstream
    npm run validate:manifest:local
    npm run package:manifest

uv experiment:

    uv venv --python 3.13 tmp	echnology-uv
    uv pip install --python tmp	echnology-uvScriptspython.exe -r requirements.txt -r requirements-web.txt
    uv pip check
    uv pip install --python tmp	echnology-uvScriptspython.exe -r requirements-ml.txt
    uv pip install --python tmp	echnology-uvScriptspython.exe -r requirements-ocr.txt
    uv pip compile --universal --generate-hashes --python-version 3.13 --output-file tmpequirements-uv-compile.lock requirements.txt requirements-web.txt

ONNX harness:

    ..venvScriptspython.exe scriptscompare_finetuned_onnx.py --list-cases
    ..venvScriptspython.exe scriptscompare_finetuned_onnx.py

The last command passed with the expected
MODEL_UNAVAILABLE/ONNX comparison not executed result. No model-dependent
command was reported as passed.

External CI evidence:

    gh run view 30728747436 --json jobs
    gh run view 30728747436 --job 91445102335 --log
    gh release view v2.5.0 --json tagName,assets

CI run 30728747436 passed all listed jobs, including Docker image build and
smoke, Windows packaged executable smoke, Rust, JavaScript, Python, Office,
and version checks. The branch did not modify main.
