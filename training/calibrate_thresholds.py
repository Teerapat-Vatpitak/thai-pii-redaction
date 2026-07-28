"""Calibrate per-label confidence floors on the SYNTHETIC dev split only.

Predeclared rule (option-2 procedure, 2026-07-28): for each label, choose the
highest threshold whose dev span recall stays within 0.005 of the
unthresholded recall — cut the low-confidence tail (where hallucinations
live) while bounding recall loss, recall-first. Gold and blind are never
consulted here. The result is written to <model-dir>/thresholds.json, part
of the model artifact.

Run: PYTHONUTF8=1 python training/calibrate_thresholds.py --model <dir> --data training/data
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

RECALL_TOLERANCE = 0.005
GRID = [round(0.50 + 0.02 * i, 2) for i in range(25)]  # 0.50 .. 0.98


def _spans_overlap_match(pred, true):
    """Greedy one-to-one overlap matching per label (same spirit as scorer)."""
    matched = set()
    tp = 0
    for ts, te, tl in true:
        for i, (ps, pe, pl, _c) in enumerate(pred):
            if i in matched or pl != tl:
                continue
            if ps < te and ts < pe:
                matched.add(i)
                tp += 1
                break
    return tp, len(pred) - len(matched), len(true) - tp


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--data", default=str(Path(__file__).with_name("data")))
    args = ap.parse_args()

    import os

    os.environ["AIGUARD_FINETUNED_MODEL_DIR"] = args.model
    from pii_redactor.detectors.finetuned_engine import FinetunedEngine

    engine = FinetunedEngine(args.model)
    engine.thresholds = {}  # calibrate from raw output

    dev = [
        json.loads(x)
        for x in (Path(args.data) / "dev.jsonl").read_text(encoding="utf-8").splitlines()
        if x.strip()
    ]
    print(f"dev docs: {len(dev)}", flush=True)

    per_label_preds: dict[str, list] = {}
    per_label_true: dict[str, list] = {}
    for di, rec in enumerate(dev):
        preds = engine.spans(rec["text"])
        for s, e, lab, c in preds:
            per_label_preds.setdefault(lab, []).append((di, s, e, c))
        for s, e, lab in rec["spans"]:
            per_label_true.setdefault(lab, []).append((di, s, e))

    thresholds: dict[str, float] = {}
    report = {}
    for label in sorted(per_label_true):
        true_by_doc: dict[int, list] = {}
        for di, s, e in per_label_true[label]:
            true_by_doc.setdefault(di, []).append((s, e, label))
        preds_all = per_label_preds.get(label, [])

        def eval_at(threshold: float, preds_all=preds_all, label=label, true_by_doc=true_by_doc):
            tp = fp = fn = 0
            preds_by_doc: dict[int, list] = {}
            for di, s, e, c in preds_all:
                if c >= threshold:
                    preds_by_doc.setdefault(di, []).append((s, e, label, c))
            for di in set(true_by_doc) | set(preds_by_doc):
                t, f_, n = _spans_overlap_match(preds_by_doc.get(di, []), true_by_doc.get(di, []))
                tp += t
                fp += f_
                fn += n
            rec_ = tp / (tp + fn) if tp + fn else 1.0
            prec = tp / (tp + fp) if tp + fp else 1.0
            return rec_, prec

        base_recall, base_prec = eval_at(0.0)
        chosen = 0.0
        chosen_stats = (base_recall, base_prec)
        for th in GRID:
            r, p = eval_at(th)
            if r >= base_recall - RECALL_TOLERANCE:
                chosen = th
                chosen_stats = (r, p)
            else:
                break
        thresholds[label] = chosen
        report[label] = {
            "base": {"recall": round(base_recall, 4), "precision": round(base_prec, 4)},
            "chosen_threshold": chosen,
            "at_threshold": {
                "recall": round(chosen_stats[0], 4),
                "precision": round(chosen_stats[1], 4),
            },
        }

    out = Path(args.model) / "thresholds.json"
    out.write_text(json.dumps(thresholds, indent=1), encoding="utf-8")
    print(json.dumps(report, indent=1))
    print("wrote", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
