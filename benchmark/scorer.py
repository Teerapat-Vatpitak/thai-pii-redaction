"""Span-level scorer.

Three views on the same predictions:
- type-aware overlap recall/precision (did we flag the entity at all, right type)
- type-agnostic char-coverage recall (did the black box actually cover the PII)
- exact-boundary recall (boundary quality)

F2 (beta=2) is the headline: recall > precision.
"""

from __future__ import annotations

import random
from collections import defaultdict

from .types import OUT_OF_SCHEME_TYPE, SHARED_ENTITY_TYPE_SET, SHARED_ENTITY_TYPES


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
    clean_docs = 0

    for sample, preds in zip(samples, predictions):
        if not preds:
            clean_docs += 1
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

    if gold_total == 0:
        # A group with no gold entities (the `negative` slice) has no recall to
        # report -- every prediction is a false positive by construction, and
        # emitting recall=0.0 for it reads as a catastrophic miss instead of the
        # clean sheet it may actually be. Report the FP view only, and mark the
        # group so renderers and callers can tell the two cases apart.
        return by_type, {
            "gold_entities": 0,
            "documents": len(samples),
            "false_positives": fp,
            "clean_docs": clean_docs,
            "clean_doc_rate": clean_docs / len(samples) if samples else 1.0,
            # Still meaningful here, and it is the FP-side metric: of what was
            # masked, how much was really PII. Nothing masked stays 1.0.
            "coverage_precision": (pred_char_on_gold / pred_char_total if pred_char_total else 1.0),
        }

    overall = {"tp": tp, "fp": fp, "fn": fn, **_prf(tp, fp, fn)}
    overall["gold_entities"] = gold_total
    overall["documents"] = len(samples)
    overall["coverage_recall"] = cov_covered / cov_total if cov_total else 0.0
    # No prediction means no wrongly-masked character, so 1.0 rather than 0.0:
    # this measures the quality of what was masked, and nothing was.
    overall["coverage_precision"] = pred_char_on_gold / pred_char_total if pred_char_total else 1.0
    overall["exact_recall"] = exact_hit / gold_total if gold_total else 0.0
    return by_type, overall


def _prepare_predictions(predictions, *, shared_only: bool):
    prepared = []
    for document in predictions:
        rows = []
        for start, end, entity_type in document:
            if entity_type in SHARED_ENTITY_TYPE_SET:
                rows.append((start, end, entity_type))
            elif not shared_only:
                rows.append((start, end, OUT_OF_SCHEME_TYPE))
        prepared.append(rows)
    return prepared


def _score_view(samples, predictions) -> dict:
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
        "overall": overall,
        "by_type": by_type,
        "by_slice": by_slice,
        "corpus_by_type": dict(corpus_by_type),
    }


def bootstrap_f2_ci(
    samples,
    predictions,
    *,
    iterations: int = 1000,
    seed: int = 0,
    confidence: float = 0.95,
    shared_only: bool = False,
) -> dict:
    """Return a deterministic percentile CI with documents as the sample unit."""
    if len(samples) != len(predictions):
        raise ValueError("samples and predictions must have the same length")
    if not samples:
        raise ValueError("bootstrap needs at least one document")
    if iterations < 1:
        raise ValueError("bootstrap iterations must be positive")
    if not 0.0 < confidence < 1.0:
        raise ValueError("bootstrap confidence must be between 0 and 1")

    prepared = _prepare_predictions(predictions, shared_only=shared_only)
    per_document: list[tuple[int, int, int]] = []
    for sample, document_predictions in zip(samples, prepared):
        _, overall = _score_group([sample], [document_predictions])
        if overall.get("gold_entities") == 0:
            per_document.append((0, overall["false_positives"], 0))
        else:
            per_document.append((overall["tp"], overall["fp"], overall["fn"]))

    rng = random.Random(seed)
    count = len(per_document)
    values: list[float] = []
    for _ in range(iterations):
        tp = fp = fn = 0
        for _ in range(count):
            doc_tp, doc_fp, doc_fn = per_document[rng.randrange(count)]
            tp += doc_tp
            fp += doc_fp
            fn += doc_fn
        values.append(_prf(tp, fp, fn)["f2"])
    values.sort()

    tail = (1.0 - confidence) / 2.0
    lower_index = min(iterations - 1, int(tail * iterations))
    upper_index = min(iterations - 1, max(0, int((1.0 - tail) * iterations) - 1))
    return {
        "metric": "f2",
        "method": "percentile",
        "unit": "document",
        "scope": "shared_11" if shared_only else "unrestricted",
        "confidence": confidence,
        "iterations": iterations,
        "seed": seed,
        "lower": values[lower_index],
        "upper": values[upper_index],
    }


def score(
    samples,
    predictions,
    *,
    bootstrap_iters: int = 1000,
    bootstrap_seed: int = 0,
) -> dict:
    """Score unrestricted product output and the shared 11-type view."""
    if len(samples) != len(predictions):
        raise ValueError("samples and predictions must have the same length")

    unrestricted_predictions = _prepare_predictions(predictions, shared_only=False)
    shared_predictions = _prepare_predictions(predictions, shared_only=True)
    unrestricted = _score_view(samples, unrestricted_predictions)
    shared = _score_view(samples, shared_predictions)
    corpus_by_type = unrestricted.pop("corpus_by_type")
    shared.pop("corpus_by_type")
    excluded = sum(
        1
        for document in predictions
        for _, _, entity_type in document
        if entity_type not in SHARED_ENTITY_TYPE_SET
    )

    confidence_intervals = {}
    shared_confidence_intervals = {}
    if samples and bootstrap_iters:
        confidence_intervals["overall_f2"] = bootstrap_f2_ci(
            samples,
            predictions,
            iterations=bootstrap_iters,
            seed=bootstrap_seed,
        )
        shared_confidence_intervals["overall_f2"] = bootstrap_f2_ci(
            samples,
            predictions,
            iterations=bootstrap_iters,
            seed=bootstrap_seed,
            shared_only=True,
        )

    return {
        "corpus": {
            "samples": len(samples),
            "entities": sum(corpus_by_type.values()),
            "by_type": corpus_by_type,
        },
        **unrestricted,
        "confidence_intervals": confidence_intervals,
        "shared_11": {
            **shared,
            "excluded_predictions": excluded,
            "confidence_intervals": shared_confidence_intervals,
        },
        "out_of_scheme_predictions": excluded,
        "type_scheme": {
            "name": "shared-11",
            "types": list(SHARED_ENTITY_TYPES),
            "out_of_scheme_bucket": OUT_OF_SCHEME_TYPE,
        },
    }
