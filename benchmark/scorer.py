"""Span-level scorer.

Three views on the same predictions:
- type-aware overlap recall/precision (did we flag the entity at all, right type)
- type-agnostic char-coverage recall (did the black box actually cover the PII)
- exact-boundary recall (boundary quality)

F2 (beta=2) is the headline: recall > precision.
"""

from __future__ import annotations

from collections import defaultdict


def _overlap(a, b) -> int:
    return max(0, min(a[1], b[1]) - max(a[0], b[0]))


def _prf(tp: int, fp: int, fn: int) -> dict:
    p = tp / (tp + fp) if (tp + fp) else 0.0
    r = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * p * r / (p + r) if (p + r) else 0.0
    f2 = 5 * p * r / (4 * p + r) if (4 * p + r) else 0.0
    return {"precision": p, "recall": r, "f1": f1, "f2": f2}


def _score_group(samples, predictions):
    by_type = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
    cov_covered = cov_total = exact_hit = gold_total = 0
    pred_char_total = pred_char_on_gold = 0

    for sample, preds in zip(samples, predictions):
        preds_by_type = defaultdict(list)
        for p in preds:
            preds_by_type[p[2]].append((p[0], p[1]))
        golds_by_type = defaultdict(list)
        for g in sample.spans:
            golds_by_type[g.entity_type].append((g.start, g.end))

        for etype in set(list(golds_by_type) + list(preds_by_type)):
            golds = golds_by_type.get(etype, [])
            plist = preds_by_type.get(etype, [])
            matched_p = set()
            for g in golds:
                hit = None
                for i, pr in enumerate(plist):
                    if i in matched_p:
                        continue
                    if _overlap(g, pr) > 0:
                        hit = i
                        break
                if hit is not None:
                    matched_p.add(hit)
                    by_type[etype]["tp"] += 1
                else:
                    by_type[etype]["fn"] += 1
            by_type[etype]["fp"] += len(plist) - len(matched_p)

        all_pred = [(p[0], p[1]) for p in preds]

        # Character-level precision, the counterpart of coverage_recall.
        # Entity-level precision matches one-to-one, so a detector that splits
        # a span gold labels as one piece is scored as if the extra pieces were
        # wrong -- 44 of 45 ADDRESS "false positives" on this corpus were that,
        # not real errors. Counting characters asks the question that actually
        # matters instead: of what we masked, how much was really PII.
        # Predicted ranges are unioned first so overlapping predictions are not
        # counted twice.
        gold_chars = set()
        for g in sample.spans:
            gold_chars.update(range(g.start, g.end))
        pred_chars = set()
        for ps, pe in all_pred:
            pred_chars.update(range(ps, pe))
        pred_char_total += len(pred_chars)
        pred_char_on_gold += len(pred_chars & gold_chars)

        for g in sample.spans:
            gold_total += 1
            glen = g.end - g.start
            cov_total += glen
            covered = [False] * glen
            for pr in all_pred:
                lo = max(g.start, pr[0])
                hi = min(g.end, pr[1])
                for k in range(lo, hi):
                    covered[k - g.start] = True
            cov_covered += sum(covered)
            if any(p[0] == g.start and p[1] == g.end and p[2] == g.entity_type for p in preds):
                exact_hit += 1

    by_type = {k: {**v, **_prf(v["tp"], v["fp"], v["fn"])} for k, v in by_type.items()}
    tp = sum(c["tp"] for c in by_type.values())
    fp = sum(c["fp"] for c in by_type.values())
    fn = sum(c["fn"] for c in by_type.values())
    overall = {"tp": tp, "fp": fp, "fn": fn, **_prf(tp, fp, fn)}
    overall["coverage_recall"] = cov_covered / cov_total if cov_total else 0.0
    # No prediction means no wrongly-masked character, so 1.0 rather than 0.0:
    # this measures the quality of what was masked, and nothing was.
    overall["coverage_precision"] = pred_char_on_gold / pred_char_total if pred_char_total else 1.0
    overall["exact_recall"] = exact_hit / gold_total if gold_total else 0.0
    return by_type, overall


def score(samples, predictions) -> dict:
    by_type, overall = _score_group(samples, predictions)
    corpus_by_type = defaultdict(int)
    for s in samples:
        for g in s.spans:
            corpus_by_type[g.entity_type] += 1
    by_slice = {}
    for sl in sorted({s.slice for s in samples}):
        idx = [i for i, s in enumerate(samples) if s.slice == sl]
        _, ov = _score_group([samples[i] for i in idx], [predictions[i] for i in idx])
        by_slice[sl] = ov
    return {
        "corpus": {
            "samples": len(samples),
            "entities": sum(corpus_by_type.values()),
            "by_type": dict(corpus_by_type),
        },
        "overall": overall,
        "by_type": by_type,
        "by_slice": by_slice,
    }
