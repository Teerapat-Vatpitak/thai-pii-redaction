# Government-form synthetic regression gate

- Date: 2026-07-31
- Evidence level: synthetic local regression
- Forms: official blank คร.1, ภ.ง.ด.91, and สปส.1-03
- Inputs: 9 (digital, print-like, and degraded for each form)
- Result: **functional fail**
- Blind set: not used
- Expectations: developer-authored and not independently adjudicated
- Independent annotation: deferred by the owner for broader real-form content

This run proves that the local runner can build and inspect all nine inputs. It
does not prove general government-form accuracy, physical-scan accuracy, or
handwriting support. The strict privacy gate stays red because four synthetic
fields remained visible; none were unmeasurable this run.

Run:

```powershell
$env:PYTHONUTF8='1'
.\.venv-full\Scripts\python.exe -m benchmark.data.probe.gov_forms.run_acceptance `
  --output-dir benchmark/reports/gov-forms-2026-07-31-final
```

The command writes one safe diagnostic JSON result per input and a canonical
`summary.json` file under the gitignored report directory. The detailed files
omit expected values, OCR text, surviving values, and decoy strings. It returns
`1` while any strict gate fails. The summary records the full Git commit,
repository state, runtime versions, per-input safe metrics, and aggregate
metrics. The table below comes from those summary fields.

## Aggregate result

| Measure | Result |
|---|---:|
| Input route | 9/9 correct |
| OCR route | 9/9 inputs measured |
| Exact or whitespace-normalized extraction | 39/45 |
| Detection overlap | 41/45 |
| Type match | 36/42 scored values |
| Fully covered region | 41/45 |
| Residual verdict | 41 removed, 4 exposed, 0 unmeasurable |
| Redacted-render OCR check | 3 of the 4 exposed values were also read back from the redacted render |
| Declared decoy extraction check | No declared decoy string appeared in 9/9 inputs |

The three failing inputs triggered eleven gate-failure codes: coverage
incomplete on 3 inputs, residual exposed on 3, a non-removed residual row on
3, and redacted-render OCR exposure on 2. These counts are gate events, not
unique field counts. The failing inputs were the print-like คร.1 input, the
print-like ภ.ง.ด.91 input, and the degraded ภ.ง.ด.91 input.

The exposed fields were the first and second applicant names in the
print-like คร.1 input, and the spouse name in both the print-like and the
degraded ภ.ง.ด.91 input (four exposed values total, since the spouse name
failed in two separate inputs). For the print-like คร.1 applicant names, the
source OCR read the name at roughly 0.90 character accuracy — not an exact
match — so the pipeline treated the value as not found, drew no redaction box,
and the redacted-render OCR then read the name straight back off the page.
The degraded ภ.ง.ด.91 spouse name was read correctly by the source OCR but the
detector never tagged it as a NAME, so no box was drawn there either, and the
redacted-render OCR again read it back. The print-like ภ.ง.ด.91 spouse name
was exposed for a different reason: its redaction box covered only 31.5% of
the field's pixel area, not because the redacted-render OCR could read it.
No fields were unmeasurable this run. No raw or real PII is stored in this
record.

Runtime: Python 3.13.12, PaddlePaddle 3.2.2, PaddleOCR 3.7.0, OpenCV 4.10.0,
Pillow 12.3.0, ReportLab 5.0.0, and pypdfium2 5.12.1.

## Runner and code integrity verified alongside this run

- Focused OCR tests verify that retry images stay three-channel; this batch
  completed all nine OCR routes.
- Focused probe tests verify that exact, whitespace-normalized, and close OCR
  matches cannot reuse one source range for two expected values.
- Runner tests require each expected index once in extraction, coverage, and
  residual rows. They also reject empty expectations.
- Runner tests keep dirty or unknown repository results below release-grade
  evidence.
- Code and endpoint tests verify that the PDF endpoint and probe use the shared
  `detect_all` path.

## Accuracy work kept in scope

The default CRF now retries at most eight eligible short Thai lines that have
no non-NAME entity. It adds a NAME on an empty line. It replaces an existing
NAME only when the isolated result keeps the same start and extends the right
edge. The retry runs only for the default `thainer` engine, keeps source spans,
trims role labels, and rejects tested non-name lines. On the visible gold-v4
set (648 entities plus 45 negative documents), overall recall is 0.937 and F2
is 0.910; NAME recall is 0.910, precision 0.953, and F2 0.918. Exact-boundary
recall is 0.793 and the government-form slice recall is 0.857.

A broader “name near an ID or date” rule was not kept after visible-gold
regression testing. The runner does not access `blind-v1`; the reveal log
remains at 4/6. Independent annotation and adjudication of broader real-form
content remain deferred.
