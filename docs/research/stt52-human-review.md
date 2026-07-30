# STT52 second-human review

Status: waiting for an independent human reviewer

The reviewer must not be the person who wrote the gold annotations. The
reviewer reads `docs/research/stt52-human-review-guidelines.md`, but does not
see the gold labels.

## Prepare the packet

```powershell
.\.venv\Scripts\python.exe scripts\prepare_stt52_human_review.py `
  --output research\stt52\second-human-v1.json
```

The packet selects four documents from each of the twelve slices. It contains
48 documents, or 19% of gold-v3. It hides slice names and source document IDs,
then mixes the order. It records the corpus commit, corpus hash, and guideline
hash.

For each document:

1. Do not change the text.
2. Add `[[TYPE|value]]` around every in-scope entity.
3. Set `reviewed` to `true`.
4. Use an opaque code such as `R02A`. Do not use a name or e-mail.
5. Complete the reviewer checks at the top of the file.

Example:

```text
ติดต่อ [[NAME|นายสมชาย ใจดี]] ที่ [[EMAIL|test@example.com]]
```

## Score the completed packet

```powershell
.\.venv\Scripts\python.exe scripts\score_stt52_human_review.py `
  research\stt52\second-human-v1.json `
  --json research\stt52\second-human-v1-agreement.json
```

The report contains aggregate counts only. It reports:

- exact span and type F1;
- overlap span and type F1;
- character and type F1;
- exact F1 by type;
- agreement on negative documents.

The paper must not report agreement until a real second human completes the
packet.
