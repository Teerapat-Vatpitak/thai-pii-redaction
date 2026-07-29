<!--
Keep a PR to one logical change. Conventional Commits style for the title
(feat:, fix:, docs:, test:, ci:, chore:), imperative mood.
-->

## What and why

<!-- What changes, and the problem it solves. Link the issue or decision record
     it comes from: "Closes #123", "Implements docs/decisions/....md". -->

## How it was verified

<!-- The commands you actually ran and what they printed. "Tests pass" without a
     result is not evidence; paste the summary line. -->

```
$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe -m pytest
```

## Checklist

- [ ] `ruff check .` and `ruff format --check .` are clean
- [ ] Tests cover the change — new detection logic, API behavior, or scripts land with a regression test in this PR
- [ ] No real PII anywhere in the diff, tests, fixtures, or PR description
- [ ] No hand-written volatile numbers in prose (test counts, versions, benchmark scores) — cite a generated source instead
- [ ] Version strings untouched unless this is a release PR using `scripts/bump_version.py`

If this PR touches detection, masking, the vault, or the leak guard:

- [ ] The design invariants in CLAUDE.md still hold, or the PR says which one it changes and why
- [ ] Recall-over-precision is respected: a new false negative needs a much stronger argument than a new false positive

If this PR touches the benchmark:

- [ ] Gold-set edits follow [docs/benchmark-contribution.md](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/blob/main/docs/benchmark-contribution.md) — version bumped in `benchmark/gold.py`, record added under `docs/decisions/`
- [ ] Any accuracy number quoted here comes from a report the reviewer can regenerate, and states corpus size
- [ ] The blind set was not opened, decrypted, printed, or scored outside the documented protocol
