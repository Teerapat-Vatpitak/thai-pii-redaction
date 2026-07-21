"""Character-level precision, the missing half of coverage_recall.

Entity-level precision matches gold to predictions one-to-one, so a detector
that splits an address gold labels as ONE span into its components scores
1 tp + (N-1) fp even when every piece lands on real PII. Measured on the gold
corpus: 44 of 45 ADDRESS "false positives" were exactly that, and 1 was a real
miss. A number that moves that much for that reason cannot be the headline.

`coverage_recall` already sidesteps the problem on the recall side by counting
characters instead of spans. These tests pin its counterpart: of the characters
we masked, how many were actually PII.
"""

from benchmark.scorer import score
from benchmark.types import GoldSpan, Sample


def _sample(text, spans, slice_="s", template_id="t"):
    return Sample(
        text=text,
        spans=[GoldSpan(a, b, t) for a, b, t in spans],
        template_id=template_id,
        slice=slice_,
    )


def test_splitting_one_gold_span_into_pieces_does_not_cost_coverage_precision():
    """The exact case that made ADDRESS precision collapse.

    Gold labels the whole address; the detector returns its parts. Every
    predicted character is inside the gold span, so character precision is
    perfect even though entity precision is 1/3.
    """
    text = "ที่อยู่ 99 ซอยลาดพร้าว 71 กรุงเทพ"
    gold_start, gold_end = 8, len(text)
    samples = [_sample(text, [(gold_start, gold_end, "ADDRESS")])]
    predictions = [
        [(8, 10, "ADDRESS"), (14, 25, "ADDRESS"), (26, len(text), "ADDRESS")],
    ]

    report = score(samples, predictions)

    assert report["overall"]["coverage_precision"] == 1.0
    assert report["overall"]["precision"] < 0.5, "entity-level view still penalises the split"


def test_masking_text_that_is_not_pii_does_cost_coverage_precision():
    """The metric must still punish over-masking, or it measures nothing."""
    text = "ราคา 500 บาท ชื่อ สมชาย"
    samples = [_sample(text, [(18, 23, "NAME")])]
    predictions = [[(0, 12, "ADDRESS"), (18, 23, "NAME")]]

    report = score(samples, predictions)

    assert 0.0 < report["overall"]["coverage_precision"] < 0.5


def test_coverage_precision_is_one_when_nothing_is_predicted():
    """No prediction, no wrongly-masked character. Vacuous but must not divide by zero."""
    samples = [_sample("ไม่มีอะไร", [])]
    report = score(samples, [[]])
    assert report["overall"]["coverage_precision"] == 1.0
