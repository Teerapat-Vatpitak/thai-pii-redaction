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
handwriting support. The strict privacy gate stays red because two synthetic
fields remained visible and five fields had no reliable region to inspect.

Run:

```powershell
$env:PYTHONUTF8='1'
.\.venv-full\Scripts\python.exe -m benchmark.data.probe.gov_forms.run_acceptance `
  --output-dir benchmark/reports/gov-forms-2026-07-31-clean
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
| OCR route | 6/6 image-only inputs measured |
| Exact or whitespace-normalized extraction | 33/45 |
| Detection overlap | 38/45 |
| Type match | 31/37 scored values |
| Fully covered region | 38/45 |
| Residual verdict | 38 removed, 2 exposed, 5 unmeasurable |
| Declared decoy extraction check | No declared decoy string appeared in 9/9 inputs |

The 19 input-level gate failures were: extraction incomplete on 6 inputs,
coverage incomplete on 4, exposed residual on 2, unmeasurable residual on 3,
and a non-removed residual row on 4. These counts are gate events, not unique
field counts.

The exposed fields were the second applicant name in the digital คร.1 input
and the insured-person name in the degraded สปส.1-03 input. The five
unmeasurable fields were address, spouse tax ID, date of birth, and national-ID
cases where OCR did not provide a reliable unique region. No raw or real PII
is stored in this record.

Runtime: Python 3.13.12, PaddlePaddle 3.2.2, PaddleOCR 3.7.0, OpenCV 4.10.0,
Pillow 12.3.0, ReportLab 5.0.0, and pypdfium2 5.12.1.

## Runner and code integrity verified alongside this run

- Focused OCR tests verify that retry images stay three-channel; this batch
  completed all six OCR routes.
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
