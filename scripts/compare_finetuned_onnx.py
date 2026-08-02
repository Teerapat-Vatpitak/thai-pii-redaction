"""Optional PyTorch versus ONNX Runtime evaluation for the fine-tuned NER model.

The model is an external artifact selected by AIGUARD_FINETUNED_MODEL_DIR.
This harness does not change the product engine. It uses separate worker
processes for PyTorch and ONNX measurements so their RSS samples are not
combined in one process.

The real evaluation needs a model artifact with the 11-label mapping produced
by training/train.py. A short training run can be marked SMOKE_ONLY, but its
quality is not a production accuracy claim.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from statistics import median
from typing import Any

_DEFAULT_OUTPUT_DIR = Path("tmp") / "technology-onnx"
_ENTITY_LABELS = frozenset({"PERSON", "LOCATION", "ORGANIZATION", "DATE", "STUDENT_ID"})
_EXPECTED_LABELS = frozenset(
    {"O"} | {f"{prefix}-{label}" for prefix in ("B", "I") for label in _ENTITY_LABELS}
)
_CONFIDENCE_TOLERANCE = 1e-3

# Synthetic probes only. They are not a training set or a blind evaluation.
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


class EvaluationError(RuntimeError):
    """Safe, user-facing evaluation failure without model-path details."""


class ModelUnavailable(EvaluationError):
    """The requested external model is not available."""


class ModelInvalid(EvaluationError):
    """The external model exists but is not a compatible artifact."""


class OptionalDependencyUnavailable(EvaluationError):
    """A dependency needed only by this optional experiment is missing."""


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
        help="Optional raw-label synthetic gold JSONL for exact-span P/R/F1.",
    )
    parser.add_argument(
        "--quantize",
        action="store_true",
        help="Run dynamic INT8 only after FP32 differential validation passes.",
    )
    parser.add_argument(
        "--require-model",
        action="store_true",
        help="Treat an unavailable or invalid model as a non-zero failure.",
    )
    parser.add_argument(
        "--smoke-only",
        action="store_true",
        help="Mark a successful run as SMOKE_ONLY, never as production evidence.",
    )
    parser.add_argument(
        "--repeats",
        type=int,
        default=5,
        help="Warm inference repetitions per worker (default: 5).",
    )
    parser.add_argument(
        "--list-cases",
        action="store_true",
        help="List the required synthetic probes and exit.",
    )
    # Internal worker arguments keep PyTorch and ONNX measurements isolated.
    parser.add_argument(
        "--worker",
        choices=("export", "quantize", "pytorch", "onnx-fp32", "onnx-int8"),
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--worker-result-file", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--onnx-path", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--quantized-path", type=Path, help=argparse.SUPPRESS)
    return parser.parse_args()


def _print_cases() -> None:
    for name, _text in _CASES:
        print(name)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_parent_result(args: argparse.Namespace, payload: dict[str, Any]) -> None:
    _write_json(args.output_dir / "results.json", payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _finish_skipped(args: argparse.Namespace, reason: str) -> int:
    payload = {
        "status": "SKIPPED",
        "reason": reason,
        "model": None,
        "fp32": None,
        "int8": {"status": "NOT_EXECUTED", "reason": "FP32 was not executed"},
    }
    _write_parent_result(args, payload)
    return 2 if args.require_model else 0


def _finish_failed(args: argparse.Namespace, reason: str) -> int:
    payload = {
        "status": "FAIL",
        "reason": reason,
        "model": None,
        "fp32": None,
        "int8": {"status": "NOT_EXECUTED", "reason": "FP32 did not pass"},
    }
    _write_parent_result(args, payload)
    return 1


def _rss_mb() -> float | None:
    try:
        import psutil

        return round(psutil.Process().memory_info().rss / (1024 * 1024), 1)
    except ImportError:
        return None


def _model_size_bytes(model_dir: Path) -> int:
    return sum(path.stat().st_size for path in model_dir.rglob("*") if path.is_file())


def _validate_label_mapping(id2label: dict[int, str]) -> None:
    if set(id2label) != set(range(len(id2label))):
        raise ModelInvalid("model label ids are not contiguous")
    labels = set(id2label.values())
    if labels != _EXPECTED_LABELS:
        raise ModelInvalid("model label mapping is not the expected 11-label BIO space")


def _validate_tokenizer(tokenizer: Any) -> None:
    if not getattr(tokenizer, "is_fast", False):
        raise ModelInvalid("model tokenizer is not fast and cannot provide offsets")


def _load_thresholds(model_dir: Path) -> dict[str, float]:
    path = model_dir / "thresholds.json"
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ModelInvalid("thresholds.json is not valid JSON") from exc
    if not isinstance(raw, dict):
        raise ModelInvalid("thresholds.json is not an object")
    thresholds: dict[str, float] = {}
    for label, value in raw.items():
        if label not in _ENTITY_LABELS or not isinstance(value, (int, float)):
            raise ModelInvalid("thresholds.json has an invalid label or value")
        if not math.isfinite(float(value)) or not 0.0 <= float(value) <= 1.0:
            raise ModelInvalid("thresholds.json has an out-of-range threshold")
        thresholds[str(label)] = float(value)
    return thresholds


def _check_artifact_files(model_dir: Path) -> None:
    if not model_dir.is_dir():
        raise ModelUnavailable("model directory is unavailable")
    if not (model_dir / "config.json").is_file():
        raise ModelInvalid("model is missing config.json")
    weights = list(model_dir.glob("model*.safetensors"))
    weights += list(model_dir.glob("pytorch_model*.bin"))
    if not weights:
        raise ModelInvalid("model is missing PyTorch weights")


def _load_engine(model_dir: Path) -> tuple[Any, dict[str, Any]]:
    _check_artifact_files(model_dir)
    try:
        from pii_redactor.detectors.finetuned_engine import (
            FinetunedEngine,
            FinetunedEngineUnavailableError,
        )
    except ImportError as exc:
        raise OptionalDependencyUnavailable("fine-tuned engine imports are unavailable") from exc
    try:
        engine = FinetunedEngine(str(model_dir))
    except FinetunedEngineUnavailableError as exc:
        message = str(exc)
        if "requirements-ml" in message:
            raise OptionalDependencyUnavailable("requirements-ml.txt is unavailable") from exc
        raise ModelInvalid("fine-tuned model could not be loaded") from exc
    except Exception as exc:
        raise ModelInvalid("fine-tuned model could not be loaded") from exc
    _validate_tokenizer(engine._tok)
    _validate_label_mapping(engine._id2label)
    thresholds = _load_thresholds(model_dir)
    metadata = {
        "category": "external",
        "architecture": type(engine._model).__name__,
        "tokenizer": type(engine._tok).__name__,
        "labels": [engine._id2label[index] for index in range(len(engine._id2label))],
        "thresholds_present": bool(thresholds),
        "model_size_bytes": _model_size_bytes(model_dir),
        "thresholds": thresholds,
    }
    return engine, metadata


def _load_onnx_context(
    model_dir: Path,
    onnx_path: Path,
) -> tuple[Any, Any, dict[int, str], dict[str, float], list[str]]:
    _check_artifact_files(model_dir)
    try:
        import onnxruntime as ort
        from transformers import AutoTokenizer
    except ImportError as exc:
        raise OptionalDependencyUnavailable("ONNX evaluation dependencies are unavailable") from exc
    try:
        tokenizer = AutoTokenizer.from_pretrained(
            str(model_dir),
            local_files_only=True,
        )
        config = json.loads((model_dir / "config.json").read_text(encoding="utf-8"))
        id2label = {int(key): str(value) for key, value in config["id2label"].items()}
        _validate_tokenizer(tokenizer)
        _validate_label_mapping(id2label)
        thresholds = _load_thresholds(model_dir)
        available = ort.get_available_providers()
        providers = ["CPUExecutionProvider"] if "CPUExecutionProvider" in available else None
        session = (
            ort.InferenceSession(str(onnx_path), providers=providers)
            if providers
            else ort.InferenceSession(str(onnx_path))
        )
    except (KeyError, OSError, ValueError) as exc:
        raise ModelInvalid("ONNX model or tokenizer could not be loaded") from exc
    except Exception as exc:
        raise ModelInvalid("ONNX model or tokenizer could not be loaded") from exc
    return tokenizer, session, id2label, thresholds, list(session.get_providers())


def _decode_spans(
    ids: list[int],
    offsets: list[tuple[int, int]],
    best_label: dict[int, str],
    best_prob: dict[int, float],
) -> list[tuple[int, int, str, float]]:
    """Decode BIO output using the production engine's character-span rules."""

    out: list[tuple[int, int, str, float]] = []
    current_label: str | None = None
    current_start = current_end = 0
    current_probs: list[float] = []

    def flush() -> None:
        nonlocal current_label
        if current_label is not None and current_end > current_start:
            out.append(
                (
                    current_start,
                    current_end,
                    current_label,
                    sum(current_probs) / max(1, len(current_probs)),
                )
            )
        current_label = None

    for token_index in range(len(ids)):
        label = best_label.get(token_index, "O")
        start, end = offsets[token_index]
        if end <= start:
            continue
        if label == "O":
            flush()
            continue
        prefix, _, entity_type = label.partition("-")
        if current_label == entity_type and prefix == "I":
            current_end = end
            current_probs.append(best_prob.get(token_index, 0.0))
        else:
            flush()
            current_label = entity_type
            current_start, current_end = start, end
            current_probs = [best_prob.get(token_index, 0.0)]
    flush()
    return out


def _windowed_onnx_spans(
    session: Any,
    tokenizer: Any,
    id2label: dict[int, str],
    text: str,
    window_tokens: int,
    stride_tokens: int,
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
    if len(input_names) < 2:
        raise EvaluationError("ONNX model does not expose two token inputs")
    ids_name = next((name for name in input_names if "input_ids" in name), input_names[0])
    mask_name = next(
        (name for name in input_names if "attention_mask" in name),
        input_names[1],
    )
    best_prob: dict[int, float] = {}
    best_label: dict[int, str] = {}
    start_token = 0
    while start_token < len(ids):
        window = ids[start_token : start_token + window_tokens]
        input_ids = np.asarray([window], dtype=np.int64)
        attention_mask = np.ones_like(input_ids, dtype=np.int64)
        logits = session.run(None, {ids_name: input_ids, mask_name: attention_mask})[0][0]
        probs = _softmax(logits)
        for index in range(len(window)):
            token_index = start_token + index
            label_id = int(np.argmax(probs[index]))
            probability = float(probs[index][label_id])
            if probability > best_prob.get(token_index, 0.0):
                best_prob[token_index] = probability
                best_label[token_index] = id2label.get(label_id, f"UNKNOWN_{label_id}")
        if start_token + window_tokens >= len(ids):
            break
        start_token += window_tokens - stride_tokens
    return _decode_spans(ids, offsets, best_label, best_prob)


def _softmax(logits: Any) -> Any:
    import numpy as np

    values = logits - np.max(logits, axis=-1, keepdims=True)
    exp_values = np.exp(values)
    return exp_values / np.sum(exp_values, axis=-1, keepdims=True)


def _apply_thresholds(
    spans: list[tuple[int, int, str, float]],
    thresholds: dict[str, float],
) -> list[tuple[int, int, str, float]]:
    return [span for span in spans if span[3] >= thresholds.get(span[2], 0.0)]


def _same_spans(
    left: list[tuple[int, int, str, float]],
    right: list[tuple[int, int, str, float]],
    confidence_tolerance: float = _CONFIDENCE_TOLERANCE,
) -> bool:
    if len(left) != len(right):
        return False
    return all(
        a[:3] == b[:3] and abs(float(a[3]) - float(b[3])) <= confidence_tolerance
        for a, b in zip(left, right)
    )


def _compare_worker_outputs(
    left: dict[str, Any],
    right: dict[str, Any],
) -> dict[str, Any]:
    left_cases = left["cases"]
    right_cases = right["cases"]
    rows: list[dict[str, Any]] = []
    span_label_agreement = True
    confidence_agreement = True
    threshold_agreement = True
    confidence_max_delta = 0.0
    for name, _text in _CASES:
        left_spans = [tuple(span) for span in left_cases[name]]
        right_spans = [tuple(span) for span in right_cases[name]]
        span_match = [span[:3] for span in left_spans] == [span[:3] for span in right_spans]
        confidence_match = _same_spans(left_spans, right_spans)
        threshold_match = [
            span[:3] for span in _apply_thresholds(left_spans, left["thresholds"])
        ] == [span[:3] for span in _apply_thresholds(right_spans, right["thresholds"])]
        deltas = [abs(float(a[3]) - float(b[3])) for a, b in zip(left_spans, right_spans)]
        confidence_max_delta = max(confidence_max_delta, *deltas, 0.0)
        span_label_agreement = span_label_agreement and span_match
        confidence_agreement = confidence_agreement and confidence_match
        threshold_agreement = threshold_agreement and threshold_match
        rows.append(
            {
                "case": name,
                "left_span_count": len(left_spans),
                "right_span_count": len(right_spans),
                "span_and_label_match": span_match,
                "confidence_match": confidence_match,
                "threshold_match": threshold_match,
            }
        )
    return {
        "cases": rows,
        "span_and_label_agreement": span_label_agreement,
        "confidence_agreement": confidence_agreement,
        "threshold_agreement": threshold_agreement,
        "confidence_tolerance": _CONFIDENCE_TOLERANCE,
        "confidence_max_delta": round(confidence_max_delta, 8),
    }


def _differential_passed(comparison: dict[str, Any]) -> bool:
    """Require stable spans and threshold decisions; allow small score drift."""

    return bool(comparison["span_and_label_agreement"] and comparison["threshold_agreement"])


def _load_jsonl_gold(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not line.strip():
            continue
        record = json.loads(line)
        if not isinstance(record.get("text"), str) or not isinstance(
            record.get("spans"),
            list,
        ):
            raise ValueError(f"gold line {line_number} needs text and spans")
        records.append(record)
    if not records:
        raise ValueError("gold JSONL has no records")
    return records


def _prf(
    records: list[dict[str, Any]],
    predict: Callable[[str], list[tuple[int, int, str, float]]],
) -> dict[str, float | int]:
    gold_total = predicted_total = true_positive = 0
    for record in records:
        gold = {
            (int(span["start"]), int(span["end"]), str(span["label"])) for span in record["spans"]
        }
        predicted = {(start, end, label) for start, end, label, _ in predict(record["text"])}
        gold_total += len(gold)
        predicted_total += len(predicted)
        true_positive += len(gold & predicted)
    precision = true_positive / predicted_total if predicted_total else 0.0
    recall = true_positive / gold_total if gold_total else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "gold_spans": gold_total,
        "predicted_spans": predicted_total,
        "true_positive": true_positive,
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "f1": round(f1, 6),
    }


def _worker_cases() -> list[tuple[str, str]]:
    return list(_CASES)


def _run_worker(args: argparse.Namespace) -> int:
    result_path = args.worker_result_file or args.output_dir / "worker-result.json"
    try:
        if args.worker == "export":
            engine, metadata = _load_engine(Path(args.model_dir))
            if args.onnx_path is None:
                raise EvaluationError("ONNX output path is missing")
            import time as _time

            started = _time.perf_counter()
            _export_fp32(engine._model, engine._tok, args.onnx_path)
            payload = {
                "status": "PASS",
                "backend": "export",
                "export_ms": round((_time.perf_counter() - started) * 1000, 3),
                "metadata": metadata,
                "onnx_size_bytes": args.onnx_path.stat().st_size,
            }
        elif args.worker == "quantize":
            if args.onnx_path is None or args.quantized_path is None:
                raise EvaluationError("INT8 paths are missing")
            _quantize_fp32(args.onnx_path, args.quantized_path)
            payload = {
                "status": "PASS",
                "backend": "quantize",
                "onnx_int8_size_bytes": args.quantized_path.stat().st_size,
            }
        else:
            model_dir = Path(args.model_dir)
            started = time.perf_counter()
            if args.worker == "pytorch":
                engine, metadata = _load_engine(model_dir)
                predict = engine.spans
                providers = ["PyTorch CPU"]
            else:
                if args.onnx_path is None:
                    raise EvaluationError("ONNX input path is missing")
                tokenizer, session, id2label, thresholds, providers = _load_onnx_context(
                    model_dir,
                    args.onnx_path,
                )
                from pii_redactor.detectors.finetuned_engine import (
                    _STRIDE_TOKENS,
                    _WINDOW_TOKENS,
                )

                metadata = {
                    "category": "external",
                    "architecture": "ONNX Runtime token-classification graph",
                    "tokenizer": type(tokenizer).__name__,
                    "labels": [id2label[index] for index in range(len(id2label))],
                    "thresholds_present": bool(thresholds),
                    "model_size_bytes": _model_size_bytes(model_dir),
                    "thresholds": thresholds,
                }

                def predict(text: str) -> list[tuple[int, int, str, float]]:
                    return _windowed_onnx_spans(
                        session,
                        tokenizer,
                        id2label,
                        text,
                        _WINDOW_TOKENS,
                        _STRIDE_TOKENS,
                    )

            load_ms = round((time.perf_counter() - started) * 1000, 3)
            rss_after_load = _rss_mb()
            first_started = time.perf_counter()
            cases = {name: predict(text) for name, text in _worker_cases()}
            first_ms = round((time.perf_counter() - first_started) * 1000, 3)
            rss_after_first = _rss_mb()
            warm_samples: list[float] = []
            for _ in range(args.repeats):
                warm_started = time.perf_counter()
                for _name, text in _worker_cases():
                    predict(text)
                warm_samples.append((time.perf_counter() - warm_started) * 1000)
            rss_after_warm = _rss_mb()
            payload = {
                "status": "PASS",
                "backend": args.worker,
                "cases": {name: [list(span) for span in spans] for name, spans in cases.items()},
                "load_ms": load_ms,
                "first_inference_ms": first_ms,
                "first_inference_ms_per_case": round(
                    first_ms / len(_CASES),
                    3,
                ),
                "warm_inference_ms_per_case": round(
                    median(warm_samples) / len(_CASES),
                    3,
                ),
                "rss_after_load_mb": rss_after_load,
                "rss_after_first_mb": rss_after_first,
                "rss_after_warm_mb": rss_after_warm,
                "memory_method": "current RSS samples in an isolated subprocess; not a peak sampler",
                "python": platform.python_version(),
                "platform": platform.platform(),
                "cpu": platform.processor() or "unknown",
                "providers": providers,
                "thresholds": metadata["thresholds"],
                "metadata": metadata,
            }
            if args.gold_jsonl:
                records = _load_jsonl_gold(args.gold_jsonl)
                payload["gold_metrics"] = _prf(records, predict)
    except ModelUnavailable as exc:
        payload = {"status": "SKIPPED", "reason": str(exc)}
    except ModelInvalid as exc:
        payload = {"status": "FAIL", "reason": str(exc)}
    except OptionalDependencyUnavailable as exc:
        payload = {"status": "SKIPPED", "reason": str(exc)}
    except Exception:
        payload = {"status": "FAIL", "reason": "worker evaluation failed"}
    _write_json(result_path, payload)
    return 0 if payload["status"] == "PASS" else 1


def _export_fp32(model: Any, tokenizer: Any, output_path: Path) -> None:
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
    kwargs = {
        "input_names": ["input_ids", "attention_mask"],
        "output_names": ["logits"],
        "dynamic_axes": {
            "input_ids": {0: "batch", 1: "sequence"},
            "attention_mask": {0: "batch", 1: "sequence"},
            "logits": {0: "batch", 1: "sequence"},
        },
        # Use the legacy exporter so this optional harness does not require
        # the separate onnxscript package when the PyTorch exporter provides it.
        "dynamo": False,
        "opset_version": 17,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with torch.no_grad():
        torch.onnx.export(
            wrapper,
            (sample["input_ids"], sample["attention_mask"]),
            str(output_path),
            **kwargs,
        )


def _quantize_fp32(fp32_path: Path, quantized_path: Path) -> None:
    from onnxruntime.quantization import QuantType, quantize_dynamic

    quantized_path.parent.mkdir(parents=True, exist_ok=True)
    quantize_dynamic(
        str(fp32_path),
        str(quantized_path),
        weight_type=QuantType.QInt8,
    )


def _invoke_worker(
    args: argparse.Namespace,
    worker: str,
    *,
    onnx_path: Path | None = None,
    quantized_path: Path | None = None,
) -> dict[str, Any]:
    args.output_dir.mkdir(parents=True, exist_ok=True)
    result_path = args.output_dir / f"{worker.replace('-', '_')}-worker.json"
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--worker",
        worker,
        "--model-dir",
        str(args.model_dir),
        "--output-dir",
        str(args.output_dir),
        "--worker-result-file",
        str(result_path),
        "--repeats",
        str(args.repeats),
    ]
    if args.gold_jsonl:
        command.extend(["--gold-jsonl", str(args.gold_jsonl)])
    if onnx_path is not None:
        command.extend(["--onnx-path", str(onnx_path)])
    if quantized_path is not None:
        command.extend(["--quantized-path", str(quantized_path)])
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["HF_HUB_OFFLINE"] = "1"
    started = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
    )
    process_ms = round((time.perf_counter() - started) * 1000, 3)
    if not result_path.exists():
        raise EvaluationError("worker did not produce a result")
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    payload["process_elapsed_ms"] = process_ms
    if payload.get("status") == "FAIL" or completed.returncode not in (0, 1):
        raise EvaluationError("worker evaluation failed")
    return payload


def _run_parent(args: argparse.Namespace) -> int:
    if args.repeats < 1:
        return _finish_failed(args, "repeats must be positive")
    if not args.model_dir:
        return _finish_skipped(args, "AIGUARD_FINETUNED_MODEL_DIR is not set")
    model_dir = Path(args.model_dir)
    if not model_dir.is_dir():
        return _finish_skipped(args, "model directory is unavailable")
    if args.gold_jsonl and not args.gold_jsonl.is_file():
        return _finish_failed(args, "gold JSONL is unavailable")

    fp32_path = args.output_dir / "finetuned-fp32.onnx"
    try:
        export = _invoke_worker(args, "export", onnx_path=fp32_path)
        if export.get("status") == "SKIPPED":
            return _finish_skipped(args, export.get("reason", "model is unavailable"))
        if export.get("status") != "PASS":
            return _finish_failed(args, "ONNX FP32 export failed")
        pytorch = _invoke_worker(args, "pytorch")
        if pytorch.get("status") == "SKIPPED":
            return _finish_skipped(args, pytorch.get("reason", "model is unavailable"))
        onnx_fp32 = _invoke_worker(args, "onnx-fp32", onnx_path=fp32_path)
        if onnx_fp32.get("status") == "SKIPPED":
            return _finish_skipped(args, onnx_fp32.get("reason", "ONNX is unavailable"))
        fp32_comparison = _compare_worker_outputs(pytorch, onnx_fp32)
    except (EvaluationError, OSError, subprocess.TimeoutExpired):
        return _finish_failed(args, "ONNX FP32 evaluation failed")

    result: dict[str, Any] = {
        "status": "SMOKE_ONLY" if args.smoke_only else "PASS",
        "model": export["metadata"],
        "fp32": {
            "export": export,
            "pytorch": pytorch,
            "onnx": onnx_fp32,
            "comparison": fp32_comparison,
        },
        "int8": {"status": "NOT_EXECUTED", "reason": "not requested"},
        "gold_metrics": {
            "pytorch": pytorch.get("gold_metrics"),
            "onnx_fp32": onnx_fp32.get("gold_metrics"),
        },
    }
    fp32_passed = _differential_passed(fp32_comparison)
    if not fp32_passed:
        result["status"] = "FAIL"
        result["int8"] = {
            "status": "NOT_EXECUTED",
            "reason": "FP32 differential validation did not pass",
        }
    elif args.quantize:
        int8_path = args.output_dir / "finetuned-int8.onnx"
        try:
            quantize = _invoke_worker(
                args,
                "quantize",
                onnx_path=fp32_path,
                quantized_path=int8_path,
            )
            onnx_int8 = _invoke_worker(args, "onnx-int8", onnx_path=int8_path)
            if quantize.get("status") != "PASS" or onnx_int8.get("status") != "PASS":
                raise EvaluationError("INT8 worker failed")
            vs_pytorch = _compare_worker_outputs(pytorch, onnx_int8)
            vs_onnx_fp32 = _compare_worker_outputs(onnx_fp32, onnx_int8)
            int8_passed = _differential_passed(vs_pytorch) and _differential_passed(vs_onnx_fp32)
            result["int8"] = {
                "status": "SMOKE_ONLY" if args.smoke_only and int8_passed else "PASS",
                "quantize": quantize,
                "onnx": onnx_int8,
                "vs_pytorch": vs_pytorch,
                "vs_onnx_fp32": vs_onnx_fp32,
                "gold_metrics": onnx_int8.get("gold_metrics"),
            }
            if not int8_passed:
                result["status"] = "FAIL"
                result["int8"]["status"] = "FAIL"
        except (EvaluationError, OSError, subprocess.TimeoutExpired):
            result["status"] = "FAIL"
            result["int8"] = {
                "status": "FAIL",
                "reason": "INT8 evaluation failed after FP32 passed",
            }
    _write_parent_result(args, result)
    if result["status"] == "FAIL":
        return 1
    return 0


def main() -> int:
    args = _parse_args()
    if args.list_cases:
        _print_cases()
        return 0
    if args.worker:
        return _run_worker(args)
    try:
        return _run_parent(args)
    except Exception:
        return _finish_failed(args, "evaluation failed")


if __name__ == "__main__":
    raise SystemExit(main())
