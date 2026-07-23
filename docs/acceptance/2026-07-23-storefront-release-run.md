# Storefront release acceptance — 2026-07-23

Candidate: `codex/storefront-release-2.4.2`; runtime behavior commits
`bea7525` and `175f1ea`. Product version during the run was `2.4.1`; the
accepted fixes are intended for the compatible `2.4.2` patch. Microsoft 365
remains paused and acceptance-pending, and is not part of this release claim.

This record contains counts and outcomes only. Raw request text, mappings,
provider response bodies, and credentials are not stored.

## Automated and live-provider gates

The repeatable runner completed with all eleven checks passing:

```powershell
$env:PYTHONUTF8='1'
.\.venv\Scripts\python.exe scripts\run_acceptance.py --live-pathumma --live-tner
```

Evidence:
`artifacts/acceptance/acceptance-20260723T153958Z.json` (gitignored).

| Gate | Result |
|---|---|
| API health and demo enablement | Pass |
| Fake protected roundtrip | Pass |
| Prompt-injection warning semantics | Pass |
| PII-free PDPA PDF report | Pass |
| Text-layer PDF redaction and non-PDF rejection | Pass |
| Pathumma completion | Pass |
| Pathumma protected roundtrip | Pass |
| Live TNER tagging | Pass |
| Live TNER pipeline mapping | Pass |

## Browser extension

Environment: Windows, Chrome `150.0.7871.181`, unpacked extension `2.4.1`
loaded from the exact repository `extension/` directory. The backend used the
same working tree. No prompt was submitted to any AI service.

| Site | URL | Result | Evidence |
|---|---|---|---|
| ChatGPT | `https://chatgpt.com/` | Pass | One bar; four entities masked in the composer; raw fixture fields absent; two-turn tokens stable; selected synthetic reply restored in a closed-shadow overlay while the host DOM contained no restored value |
| Claude | `https://claude.ai/new` | Pass | One bar; four entities masked; raw fixture fields absent; send was not pressed |
| Gemini | `https://gemini.google.com/app` | Pass | One bar; four entities masked; raw fixture fields absent; send was not pressed |
| Grok | `https://grok.com/` | Pass after fix | Live UI exposed a Tiptap editor plus a visible helper textarea. The old selector read the helper and reported zero entities. Commit `175f1ea` prefers the real editor; rerun masked four entities with raw fixture fields absent. |
| Perplexity | `https://www.perplexity.ai/` | Pass after fix | Current `#ask-input` is a Lexical controlled editor. The old write was repaired by the host and failed closed. Commit `175f1ea` writes through `beforeinput` and waits for the bounded visible-state commit; rerun masked four entities with no warning overlay and raw fixture fields absent. |
| GLM/Z.ai | `https://chat.z.ai/` | Pass | One bar; four entities masked; raw fixture fields absent; send was not pressed |

Additional ChatGPT checks passed:

- stopping the backend kept the raw fixture in the composer, displayed the
  blocking red warning overlay, and did not report masking success;
- the backend was restarted before continuing;
- Restore displayed the synthetic originals in the closed shadow UI only; and
- the same name and phone reused the same token in a second unsent turn.

Synthetic-only screenshots are stored locally under
`artifacts/acceptance/screenshots-20260723/` (gitignored):
`chatgpt_restore.png`, `chatgpt_offline.png`, `claude_masked.png`,
`gemini_masked.png`, `grok_masked.png`, `perplexity_masked.png`, and
`zai_masked.png`.

The owner completed the generic side-panel Mask check manually and confirmed it
passed on 2026-07-23. Browser automation correctly refused direct navigation to
the extension-owned `chrome-extension://` page, so that policy boundary was not
bypassed.

## Playground

The live browser run passed:

- detection of four synthetic entities while typing;
- exact fake-provider token and surrogate restoration;
- live Pathumma completion with no raw fixture value in provider-visible text;
- warning-only prompt-injection behavior;
- readable, one-page, aggregate-only PDPA PDF download;
- PDF upload, before/after previews, and redacted-file download;
- backend-offline and no-result recovery states;
- `/demo` returning 404 without `AIGUARD_DEMO=1`; and
- usable layouts at 1366 px and 800 px without horizontal overflow.

The surrogate run first exposed a full-name boundary bug: a one-part generated
name caused the outbound high-recall detector to absorb the following ordinary
phrase. Commit `bea7525` preserves the two-part shape of a multi-part Thai name.
The exact playground fixture then restored successfully, and the regression is
pinned in both generator and API tests.

## PDF

The real browser/file flow passed with `examples/sample_document.pdf`:

- before and after previews rendered;
- the downloaded redacted PDF opened successfully;
- the output retained one page and exposed zero extractable text characters;
- no fixture value remained in extraction;
- a 200-DPI visual inspection showed black boxes covering the source values;
- non-PDF input returned 400;
- a sparse 50 MB + 1 byte upload returned 413 before full buffering;
- a synthetic scanned PDF returned the documented 503 when OCR extras were
  absent; and
- no `aiguard_redact_*` temporary directory remained.

The downloaded PDPA report also opened successfully, rendered Thai text
readably, and contained no raw fixture value.

## Automated regression gates

Before the two live-browser fixes, the full gates passed:

- Python: `787 passed, 6 skipped`;
- JavaScript: `52 passed`;
- Rust: `19 passed`; and
- Ruff lint and format checks: pass.

After the live-browser fixes, the JavaScript suite is `55 passed`. The exact
release merge commit `5c7149d` then passed all 11 main CI lanes, including
Python on Windows/Linux/core-only, Ruff, JavaScript, Office Node 22, Rust,
Docker, and the packaged-executable smoke.

## Installer and publication

Tag `v2.4.2` points to merge commit `5c7149d`. Release run `30023639048` passed
metadata preflight, Windows/macOS/Linux builds, asset-version validation,
`SHA256SUMS`, and GitHub build provenance. All downloaded checksum entries
matched locally, and provenance identified the expected repository, tag,
workflow, and source commit.

The exact Windows installer registered `AI Guard 2.4.2`, installed
`desktop.exe` with product/file version `2.4.2`, and launched a sidecar whose
`/api/health` version was `2.4.2`. Synthetic token and surrogate sessions both
restored exactly, the fake-provider roundtrip restored exactly, and closing the
desktop released port 8000. The release was published as Latest on 2026-07-23.
