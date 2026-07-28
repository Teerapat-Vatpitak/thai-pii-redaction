"""Hand-authored Thai PII gold set (v4).

Realistic, un-templated Thai documents with fake PII, labeled inline with
[[TYPE|value]] markup that parse_gold() converts to exact-span Samples.
v4 is the 2026-07-28 adjudication pass (two independent reviewers against
docs/annotation-guidelines.md; see the dated decision record): boundary
normalization (address cues out of brackets), one missed annotation, one
negative-slice look-alike fix, and a per-document long_form boundary
guarantee. Annotation conventions live in docs/annotation-guidelines.md. The
documents live in `data/gold.jsonl` (one JSON object per line) so the set can be
released as a paper artifact without shipping Python; this module is only the
parser and loader.

Two layers share one set, tagged per document:

- `natural` -- slices `gov_form` / `medical` / `finance` / `education`, written
  after the structure of ordinary Thai paperwork. Entity mix follows what those
  documents actually contain, so overall numbers mean something.
- `balanced` -- slices `name_no_cue` / `address_varied` / `messy` /
  `bank_phone` / `id_docs` / `student_id_varied`, which push the rare types up
  to a reportable n and vary one format axis at a time so a miss names its own
  cause.

`long_form` sits in the natural layer but exists for a second reason: every
other document here is short enough to fit in one NER chunk, so the stride-chunk
windowing the product actually runs was never exercised. Those documents clear
LONG_FORM_MIN_CHARS and carry PII throughout, including past the boundary.

The `negative` slice is its own thing: documents with NO PII at all, carrying
only look-alikes that must not be flagged (document numbers, receipt numbers,
statute numbers, prices, ISBN, public hotlines). Anything a detector returns
there is a false positive. Province and organization names are deliberately
absent from it -- the system flags those on purpose as quasi-identifiers, so
counting them as errors would be measuring the wrong thing.

All PII is fake (privacy-safe): the checksum-bearing values (THAI_ID,
CREDIT_CARD) were generated valid, the rest are plausible fabrications.

Gold is a DIAGNOSTIC -- it exists to expose where recall drops, not to be
gated to green.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .types import GoldSpan, Sample

# slice -> layer. `negative` is its own layer because it is scored differently
# (no gold spans, so recall is undefined and only false positives count).
SLICE_LAYERS: dict[str, str] = {
    "name_no_cue": "balanced",
    "address_varied": "balanced",
    "messy": "balanced",
    "bank_phone": "balanced",
    "id_docs": "balanced",
    "student_id_varied": "balanced",
    "gov_form": "natural",
    "medical": "natural",
    "finance": "natural",
    "education": "natural",
    "long_form": "natural",
    "negative": "negative",
}

# `long_form` documents must clear this to exercise the detector's stride-chunk
# windowing, whose core is 500 characters. Everything else in the set is a short
# document that never reaches a chunk boundary, so without this slice the
# chunking path is measured by nothing at all.
LONG_FORM_MIN_CHARS = 500

GOLD_SLICES = list(SLICE_LAYERS)

_DATA_PATH = Path(__file__).with_name("data") / "gold.jsonl"

_MARKUP = re.compile(r"\[\[([A-Z_]+)\|(.*?)\]\]")


def parse_gold(doc_id: str, slice_: str, annotated: str) -> Sample:
    parts: list[str] = []
    spans: list[GoldSpan] = []
    pos = 0
    out_len = 0
    for m in _MARKUP.finditer(annotated):
        pre = annotated[pos : m.start()]
        parts.append(pre)
        out_len += len(pre)
        etype, value = m.group(1), m.group(2)
        start = out_len
        parts.append(value)
        out_len += len(value)
        spans.append(GoldSpan(start, out_len, etype))
        pos = m.end()
    parts.append(annotated[pos:])
    return Sample(text="".join(parts), spans=spans, template_id=doc_id, slice=slice_)


def _read_records() -> list[dict]:
    with _DATA_PATH.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


_RECORDS = _read_records()

# (doc_id, slice, annotated_text) -- same shape the set had when it was inline.
GOLD_DOCS: list[tuple[str, str, str]] = [
    (r["doc_id"], r["slice"], r["annotated"]) for r in _RECORDS
]

# doc_id -> layer. Kept beside GOLD_DOCS rather than on Sample because Sample is
# shared with the synthetic corpus, which has no layer.
GOLD_LAYERS: dict[str, str] = {r["doc_id"]: r["layer"] for r in _RECORDS}


def load_gold() -> list[Sample]:
    return [parse_gold(doc_id, slice_, text) for doc_id, slice_, text in GOLD_DOCS]
