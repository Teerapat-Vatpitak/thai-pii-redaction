"""Optional PyTorch versus ONNX Runtime evaluation for the fine-tuned NER model.

The model is an external artifact selected by AIGUARD_FINETUNED_MODEL_DIR.
This script never changes the product engine or writes generated model files
outside the ignored output directory. It mirrors the current 240-token,
60-token-stride and character-offset behavior so the experiment can be run
before an ONNX backend is considered for production.

Examples:

    python scripts/compare_finetuned_onnx.py --list-cases
    python scripts/compare_finetuned_onnx.py
    python scripts/compare_finetuned_onnx.py --model-dir C:/models/ner --quantize

An optional gold JSONL file can provide exact character spans for precision,
recall, and F1. Each line must be an object with "text" and "spans"; each
span must contain "start", "end", and "label". The file is not required for
the PyTorch/ONNX differential check.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Callable
from pathlib import Path
from statistics import median
from typing import Any

_WINDOW_TOKENS = 240
_STRIDE_TOKENS = 60
_DEFAULT_OUTPUT_DIR = Path("tmp") / "technology-onnx"
_KNOWN_LABELS = frozenset(
    {
        "PERSON",
        "LOCATION",
        "ORGANIZATION",
        "DATE",
        "STUDENT_ID",
    }
)

# These are synthetic probes, not a training or blind-evaluation dataset.
_CASES = (
    ("empty_input", ""),
    ("thai_names", "ผู้ติดต่อคือ คุณทดสอบ ทองดี"),
    (
        "thai_addresses",
        "ที่อยู่ 99/9 ถนนทดสอบ แขวงตัวอย่าง เขตทดลอง กรุงเทพมหานคร 10000",
    ),
    ("organizations", "ทำงานกับบริษัทตัวอย่างสังเคราะห์ จำกัด"),
    ("dates", "เริ่มงานวันที่ 12 มกราคม 2568"),
    ("student_ids", "รหัสนักเรียน STU-000001"),
    (
        "long_input_stride",
        ("ข้อความสังเคราะห์สำหรับตรวจหน้าต่าง " * 90) + " คุณทดสอบ ทองดี " + (" ข้อมูลส่วนท้าย " * 90),
    ),
    (
        "overlapping_token_windows",
        ("คำนำสังเคราะห์ " * 54) + " บริษัทตัวอย่างสังเคราะห์ จำกัด " + (" คำต่อท้าย " * 54),
    ),
    ("unicode_offsets", "Unicode A\u0301 และ คุณทดสอบ"),
    ("combining_thai_marks", "ข้อความ ก\u0e49\u0e33 คุณทดสอบ"),
    ("unknown_labels", "ป้ายกำกับที่ไม่อยู่ในชุดมาตรฐาน MISC-000"),
    ("threshold_filtering", "ชื่อทดสอบสำหรับตรวจ confidence threshold"),
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model-dir",
        default=os.environ.get("AIGUARD_FINETUNED_MODEL_DIR"),
        help="External Hugging Face token-classification model directory.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=_DEFAULT_OUTPUT_DIR,
        help="Ignored directory for ONNX artifacts and numeric results.",
    )
    parser.add_argument(
        "--gold-jsonl",
        type=Path,
        help="Optional synthetic gold JSONL for exact-span P/R/F1.",
    )
    parser.add_argument(
        "--quantize",
        action="store_true",
        help="Run dynamic INT8 only after FP32 differential validation passes.",
    )
    parser.add_argument(
        "--repeats",
        type=int,
        default=5,
        help="Warm inference repetitions per runner (default: 5).",
    )
    parser.add_argument(
        "--list-cases",
        action="store_true",
        help="List the required synthetic probes and exit.",
    )
    return parser.parse_args()


def _print_cases() -> None:
    for name, _text in _CASES:
        print(name)


def _rss_mb() -> float | None:
    try:
        import psutil

        return round(psutil.Process().memory_info().rss / (1024 * 1024), 1)
    except ImportError:
        return None


def _model_size_bytes(model_dir: Path) -> int:
    return sum(path.stat().st_size for path in model_dir.rglob("*") if path.is_file())


def _decode_spans(
    ids: list[int],
    offsets: list[tuple[int, int]],
    best_label: dict[int, str],
    best_prob: dict[int, float],
) -> list[tuple[int, int, str, float]]:
    """Decode model token output with the current engine's BIO semantics."""

    out: list[tuple[int, int, str, float]] = []
    cur_label: str | None = None
    cur_start = cur_end = 0
    cur_probs: list[float] = []

    def flush() -> None:
        nonlocal cur_label
        if cur_label is not None and cur_end > cur_start:
            out.append(
                (
                    cur_start,
                    cur_end,
                    cur_label,
                    sum(cur_probs) / max(1, len(cur_probs)),
                )
            )
        cur_label = None

    for tok_idx in range(len(ids)):
        label = best_label.get(tok_idx, "O")
        start, end = offsets[tok_idx]
        if end <= start:
            continue
        if label == "O":
            flush()
            continue
        prefix, _, entity_type = label.partition("-")
        if cur_label == entity_type and prefix == "I":
            cur_end = end
            cur_probs.append(best_prob.get(tok_idx, 0.0))
        else:
            flush()
            cur_label = entity_type
            cur_start, cur_end = start, end
            cur_probs = [best_prob.get(tok_idx, 0.0)]
    flush()
    return out


def _windowed_onnx_spans(
    session: Any,
    tokenizer: Any,
    id2label: dict[int, str],
    text: str,
) -> list[tuple[int, int, str, float]]:
    import numpy as np

    if not text or not text.strip():
        return []
    encoded = tokenizer(text, return_offsets_mapping=True, add_special_tokens=False)
    ids = encoded["input_ids"]
    offsets = [tuple(pair) for pair in encoded["offset_mapping"]]
    if not ids:
        return []

    input_names = [item.name for item in session.get_inputs()]
    ids_name = next((name for name in input_names if "input_ids" in name), input_names[0])
    mask_name = next(
        (name for name in input_names if "attention_mask" in name),
        input_names[1],
    )
    best_prob: dict[int, float] = {}
    best_label: dict[int, str] = {}
    start_tok = 0
    while start_tok < len(ids):
        window = ids[start_tok : start_tok + _WINDOW_TOKENS]
        input_ids = np.asarray([window], dtype=np.int64)
        attention_mask = np.ones_like(input_ids, dtype=np.int64)
        logits = session.run(
            None,
            {ids_name: input_ids, mask_name: attention_mask},
        )[0][0]
        probs = _softmax(logits)
        for index in range(len(window)):
            token_index = start_tok + index
            label_id = int(np.argmax(probs[index]))
            probability = float(probs[index][label_id])
            if probability > best_prob.get(token_index, 0.0):
                best_prob[token_index] = probability
                best_label[token_index] = id2label[label_id]
        if start_tok + _WINDOW_TOKENS >= len(ids):
            break
        start_tok += _WINDOW_TOKENS - _STRIDE_TOKENS
    return _decode_spans(ids, offsets, best_label, best_prob)


def _softmax(logits: Any) -> Any:
    import numpy as np

    values = logits - np.max(logits, axis=-1, keepdims=True)
    exp_values = np.exp(values)
    return exp_values / np.sum(exp_values, axis=-1, keepdims=True)


def _same_spans(
    left: list[tuple[int, int, str, float]],
    right: list[tuple[int, int, str, float]],
    confidence_tolerance: float = 1e-3,
) -> bool:
    if len(left) != len(right):
        return False
    return all(
        a[:3] == b[:3] and abs(float(a[3]) - float(b[3])) <= confidence_tolerance
        for a, b in zip(left, right)
    )


def _apply_thresholds(
    spans: list[tuple[int, int, str, float]],
    thresholds: dict[str, float],
) -> list[tuple[int, int, str, float]]:
    return [span for span in spans if span[3] >= thresholds.get(span[2], 0.0)]


def _load_jsonl_gold(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        record = json.loads(line)
        if not isinstance(record.get("text"), str) or not isinstance(record.get("spans"), list):
            raise ValueError(f"gold line {line_number} needs text and spans")
        records.append(record)
    if not records:
        raise ValueError("gold JSONL has no records")
    return records


def _prf(
    records: list[dict[str, Any]],
    predict: Callable[[str], list[tuple[int, int, str, float]]],
) -> dict[str, float | int]:
    true_total = predicted_total = true_positive = 0
    for record in records:
        gold = {
            (int(span["start"]), int(span["end"]), str(span["label"])) for span in record["spans"]
        }
        predicted = {(start, end, label) for start, end, label, _ in predict(record["text"])}
        true_total += len(gold)
        predicted_total += len(predicted)
        true_positive += len(gold & predicted)
    precision = true_positive / predicted_total if predicted_total else 0.0
    recall = true_positive / true_total if true_total else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "gold_spans": true_total,
        "predicted_spans": predicted_total,
        "true_positive": true_positive,
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "f1": round(f1, 6),
    }


def _warm_median(
    predict: Callable[[str], Any],
    texts: list[str],
    repeats: int,
) -> float:
    samples: list[float] = []
    for _ in range(repeats):
        started = time.perf_counter()
        for text in texts:
            predict(text)
        samples.append((time.perf_counter() - started) * 1000)
    return round(median(samples) / len(texts), 3)


def _export_fp32(
    model: Any,
    tokenizer: Any,
    output_path: Path,
) -> None:
    import torch

    class LogitsWrapper(torch.nn.Module):
        def __init__(self, wrapped: Any) -> None:
            super().__init__()
            self.wrapped = wrapped

        def forward(self, input_ids: Any, attention_mask: Any) -> Any:
            return self.wrapped(
                input_ids=input_ids,
                attention_mask=attention_mask,
            ).logits

    wrapper = LogitsWrapper(model).eval()
    sample = tokenizer(
        "ข้อความสังเคราะห์",
        return_tensors="pt",
        add_special_tokens=False,
    )
    input_ids = sample["input_ids"]
    attention_mask = sample["attention_mask"]
    kwargs = {
        "input_names": ["input_ids", "attention_mask"],
        "output_names": ["logits"],
        "dynamic_axes": {
            "input_ids": {0: "batch", 1: "sequence"},
            "attention_mask": {0: "batch", 1: "sequence"},
            "logits": {0: "batch", 1: "sequence"},
        },
        "opset_version": 17,
    }
    with torch.no_grad():
        try:
            torch.onnx.export(
                wrapper,
                (input_ids, attention_mask),
                str(output_path),
                dynamo=False,
                **kwargs,
            )
        except TypeError as exc:
            if "dynamo" not in str(exc):
                raise
            torch.onnx.export(
                wrapper,
                (input_ids, attention_mask),
                str(output_path),
                **kwargs,
            )


def _quantize_fp32(fp32_path: Path, quantized_path: Path) -> None:
    from onnxruntime.quantization import QuantType, quantize_dynamic

    quantize_dynamic(
        str(fp32_path),
        str(quantized_path),
        weight_type=QuantType.QInt8,
    )


def _run(args: argparse.Namespace) -> int:
    if args.repeats < 1:
        raise ValueError("--repeats must be positive")
    if not args.model_dir:
        print("MODEL_UNAVAILABLE: set AIGUARD_FINETUNED_MODEL_DIR or pass --model-dir")
        print("ONNX comparison not executed; no model weights are bundled.")
        return 0

    model_dir = Path(args.model_dir)
    if not model_dir.is_dir():
        print(f"MODEL_UNAVAILABLE: model directory does not exist: {model_dir}")
        print("ONNX comparison not executed; no model weights are bundled.")
        return 0

    try:
        import onnxruntime as ort

        from pii_redactor.detectors.finetuned_engine import FinetunedEngine
    except ImportError as exc:
        print(f"OPTIONAL_DEPENDENCY_UNAVAILABLE: {exc}")
        return 0

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    fp32_path = output_dir / "finetuned-fp32.onnx"
    quantized_path = output_dir / "finetuned-int8.onnx"

    started = time.perf_counter()
    engine = FinetunedEngine(str(model_dir))
    pt_load_ms = round((time.perf_counter() - started) * 1000, 3)
    tokenizer = engine._tok
    model = engine._model
    id2label = engine._id2label
    texts = [text for _, text in _CASES]

    export_started = time.perf_counter()
    _export_fp32(model, tokenizer, fp32_path)
    export_ms = round((time.perf_counter() - export_started) * 1000, 3)

    providers = (
        ["CPUExecutionProvider"]
        if "CPUExecutionProvider" in ort.get_available_providers()
        else None
    )
    onnx_started = time.perf_counter()
    session = (
        ort.InferenceSession(str(fp32_path), providers=providers)
        if providers
        else ort.InferenceSession(str(fp32_path))
    )
    onnx_load_ms = round((time.perf_counter() - onnx_started) * 1000, 3)

    pt_predict = engine.spans

    def onnx_predict(text: str) -> list[tuple[int, int, str, float]]:
        return _windowed_onnx_spans(session, tokenizer, id2label, text)

    rows: list[dict[str, Any]] = []
    exact = True
    confidence_max_delta = 0.0
    unknown_labels: set[str] = set()
    threshold_exact = True
    thresholds = getattr(engine, "thresholds", {}) or {}
    for name, text in _CASES:
        pt_spans = pt_predict(text)
        onnx_spans = onnx_predict(text)
        row_exact = _same_spans(pt_spans, onnx_spans)
        exact = exact and row_exact
        deltas = [
            abs(float(left[3]) - float(right[3])) for left, right in zip(pt_spans, onnx_spans)
        ]
        confidence_max_delta = max([confidence_max_delta, *deltas])
        unknown_labels.update(span[2] for span in onnx_spans if span[2] not in _KNOWN_LABELS)
        threshold_exact = threshold_exact and _same_spans(
            _apply_thresholds(pt_spans, thresholds),
            _apply_thresholds(onnx_spans, thresholds),
        )
        rows.append(
            {
                "case": name,
                "pytorch_span_count": len(pt_spans),
                "onnx_span_count": len(onnx_spans),
                "exact_span_and_confidence_match": row_exact,
            }
        )

    result: dict[str, Any] = {
        "cases": rows,
        "pytorch_load_ms": pt_load_ms,
        "onnx_export_ms": export_ms,
        "onnx_first_load_ms": onnx_load_ms,
        "pytorch_warm_inference_ms_per_case": _warm_median(
            pt_predict,
            texts,
            args.repeats,
        ),
        "onnx_warm_inference_ms_per_case": _warm_median(
            onnx_predict,
            texts,
            args.repeats,
        ),
        "pytorch_rss_mb_after_load": _rss_mb(),
        "onnx_fp32_size_mb": round(fp32_path.stat().st_size / (1024 * 1024), 3),
        "external_model_size_mb": round(
            _model_size_bytes(model_dir) / (1024 * 1024),
            3,
        ),
        "exact_span_and_label_agreement": exact,
        "thresholded_span_agreement": threshold_exact,
        "confidence_max_delta": round(confidence_max_delta, 8),
        "unknown_onnx_labels": sorted(unknown_labels),
        "gold_metrics": None,
    }
    if args.gold_jsonl:
        gold_records = _load_jsonl_gold(args.gold_jsonl)
        result["gold_metrics"] = {
            "pytorch": _prf(gold_records, pt_predict),
            "onnx_fp32": _prf(gold_records, onnx_predict),
        }

    if args.quantize:
        if not exact or not threshold_exact:
            raise RuntimeError("refusing INT8 export because FP32 differential validation failed")
        _quantize_fp32(fp32_path, quantized_path)
        quantized_session = (
            ort.InferenceSession(str(quantized_path), providers=providers)
            if providers
            else ort.InferenceSession(str(quantized_path))
        )

        def quantized_predict(text: str) -> list[tuple[int, int, str, float]]:
            return _windowed_onnx_spans(
                quantized_session,
                tokenizer,
                id2label,
                text,
            )

        int8_exact = all(_same_spans(pt_predict(text), quantized_predict(text)) for text in texts)
        result["onnx_int8_size_mb"] = round(
            quantized_path.stat().st_size / (1024 * 1024),
            3,
        )
        result["onnx_int8_span_and_confidence_agreement"] = int8_exact
        if args.gold_jsonl:
            result["gold_metrics"]["onnx_int8"] = _prf(
                _load_jsonl_gold(args.gold_jsonl),
                quantized_predict,
            )

    (output_dir / "results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if exact and threshold_exact else 1


def main() -> int:
    args = _parse_args()
    if args.list_cases:
        _print_cases()
        return 0
    try:
        return _run(args)
    except Exception as exc:
        print(f"ONNX_EVALUATION_FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
