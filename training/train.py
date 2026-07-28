"""Fine-tune a Thai token-classification NER model on the generated data.

Init: pythainlp/thainer-corpus-v2-base-model (already Thai-NER-adapted) with a
fresh 11-label BIO head over PERSON/LOCATION/ORGANIZATION/DATE/STUDENT_ID.
Hyperparameters follow the adversarial review's recommendation for this data
size; checkpoint selection uses span-level F1 on the generator-disjoint dev
split, never gold.

Run (CPU, ~2-4h):
  PYTHONUTF8=1 python training/train.py --data training/data --out <models-dir-outside-repo>
Pilot (sanity, ~5 min): add --max-steps 100
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

LABELS = ["PERSON", "LOCATION", "ORGANIZATION", "DATE", "STUDENT_ID"]
ID2LABEL = {0: "O"}
for _t in LABELS:
    ID2LABEL[len(ID2LABEL)] = f"B-{_t}"
    ID2LABEL[len(ID2LABEL)] = f"I-{_t}"
LABEL2ID = {v: k for k, v in ID2LABEL.items()}

BASE_MODEL = "pythainlp/thainer-corpus-v2-base-model"
MAX_LEN = 256


def _read(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def _encode(records, tokenizer):
    """Tokenize with offsets and align char spans to BIO token labels."""
    encoded = []
    for rec in records:
        enc = tokenizer(
            rec["text"],
            truncation=True,
            max_length=MAX_LEN,
            return_offsets_mapping=True,
        )
        labels = []
        spans = sorted((s, e, t) for s, e, t in rec["spans"])
        for start, end in enc["offset_mapping"]:
            if end <= start:
                labels.append(-100)
                continue
            lab = "O"
            for s, e, t in spans:
                if start >= s and end <= e:
                    lab = ("B-" if start == s else "I-") + t
                    break
            labels.append(LABEL2ID[lab])
        encoded.append(
            {
                "input_ids": enc["input_ids"],
                "attention_mask": enc["attention_mask"],
                "labels": labels,
            }
        )
    return encoded


def _span_f1(pred_bio: list[list[str]], true_bio: list[list[str]]) -> dict:
    def to_spans(tags):
        spans, cur, start = set(), None, 0
        for i, t in enumerate(tags):
            p, _, e = t.partition("-")
            if p == "B":
                if cur:
                    spans.add((start, i, cur))
                cur, start = e, i
            elif p == "I" and cur == e:
                continue
            else:
                if cur:
                    spans.add((start, i, cur))
                cur = None
        if cur:
            spans.add((start, len(tags), cur))
        return spans

    tp = fp = fn = 0
    for pt, tt in zip(pred_bio, true_bio):
        ps, ts = to_spans(pt), to_spans(tt)
        tp += len(ps & ts)
        fp += len(ps - ts)
        fn += len(ts - ps)
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return {"precision": prec, "recall": rec, "f1": f1}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(Path(__file__).with_name("data")))
    ap.add_argument("--out", required=True, help="model output dir (keep OUTSIDE the repo)")
    ap.add_argument("--epochs", type=float, default=3.0)
    ap.add_argument("--lr", type=float, default=2e-5)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--grad-accum", type=int, default=2)
    ap.add_argument("--seed", type=int, default=20260728)
    ap.add_argument("--max-steps", type=int, default=-1)
    args = ap.parse_args()

    import numpy as np
    from transformers import (
        AutoModelForTokenClassification,
        AutoTokenizer,
        DataCollatorForTokenClassification,
        Trainer,
        TrainingArguments,
        set_seed,
    )

    set_seed(args.seed)
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)
    model = AutoModelForTokenClassification.from_pretrained(
        BASE_MODEL,
        num_labels=len(ID2LABEL),
        id2label=ID2LABEL,
        label2id=LABEL2ID,
        ignore_mismatched_sizes=True,  # fresh head over our label space
    )

    data_dir = Path(args.data)
    train_ds = _encode(_read(data_dir / "train.jsonl"), tokenizer)
    dev_ds = _encode(_read(data_dir / "dev.jsonl"), tokenizer)
    print(f"train={len(train_ds)} dev={len(dev_ds)}", flush=True)

    def compute_metrics(eval_pred):
        logits, labels = eval_pred
        preds = np.argmax(logits, axis=-1)
        pred_bio, true_bio = [], []
        for p_row, l_row in zip(preds, labels):
            pb, tb = [], []
            for p, lab in zip(p_row, l_row):
                if lab == -100:
                    continue
                pb.append(ID2LABEL[int(p)])
                tb.append(ID2LABEL[int(lab)])
            pred_bio.append(pb)
            true_bio.append(tb)
        return _span_f1(pred_bio, true_bio)

    train_args = TrainingArguments(
        output_dir=args.out,
        num_train_epochs=args.epochs,
        max_steps=args.max_steps,
        learning_rate=args.lr,
        per_device_train_batch_size=args.batch,
        per_device_eval_batch_size=args.batch * 2,
        gradient_accumulation_steps=args.grad_accum,
        warmup_ratio=0.06,
        weight_decay=0.01,
        max_grad_norm=1.0,
        eval_strategy="epoch" if args.max_steps < 0 else "no",
        save_strategy="epoch" if args.max_steps < 0 else "no",
        load_best_model_at_end=args.max_steps < 0,
        metric_for_best_model="f1",
        logging_steps=50,
        seed=args.seed,
        use_cpu=True,
        report_to=[],
        save_total_limit=2,
    )
    trainer = Trainer(
        model=model,
        args=train_args,
        train_dataset=train_ds,
        eval_dataset=dev_ds,
        data_collator=DataCollatorForTokenClassification(tokenizer),
        compute_metrics=compute_metrics,
    )
    trainer.train()
    if args.max_steps < 0:
        print("final dev:", trainer.evaluate(), flush=True)
    trainer.save_model(args.out)
    tokenizer.save_pretrained(args.out)
    print("saved to", args.out, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
