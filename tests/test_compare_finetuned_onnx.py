"""Focused contract tests for the optional fine-tuned ONNX evaluation harness."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from pii_redactor.detectors.finetuned_engine import _STRIDE_TOKENS, _WINDOW_TOKENS

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "compare_finetuned_onnx.py"
SPEC = importlib.util.spec_from_file_location("compare_finetuned_onnx", SCRIPT)
harness = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = harness
SPEC.loader.exec_module(harness)


def _run_cli(*args: str, output_dir: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop("AIGUARD_FINETUNED_MODEL_DIR", None)
    env["PYTHONUTF8"] = "1"
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args, "--output-dir", str(output_dir)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_missing_model_is_skipped_and_require_model_is_strict(tmp_path):
    optional = _run_cli(output_dir=tmp_path / "optional")
    assert optional.returncode == 0
    assert json.loads((tmp_path / "optional" / "results.json").read_text())["status"] == "SKIPPED"

    required = _run_cli("--require-model", output_dir=tmp_path / "required")
    assert required.returncode == 2
    assert json.loads((tmp_path / "required" / "results.json").read_text())["status"] == "SKIPPED"


def test_existing_incompatible_model_is_fail(tmp_path):
    model_dir = tmp_path / "incompatible-model"
    model_dir.mkdir()
    result = _run_cli(
        "--model-dir",
        str(model_dir),
        "--require-model",
        output_dir=tmp_path / "invalid-result",
    )

    assert result.returncode == 1
    assert (
        json.loads((tmp_path / "invalid-result" / "results.json").read_text())["status"] == "FAIL"
    )


def test_invalid_label_space_is_rejected():
    valid = dict(enumerate(sorted(harness._EXPECTED_LABELS)))
    harness._validate_label_mapping(valid)

    invalid = dict(valid)
    invalid[0] = "B-NOT_ALLOWED"
    try:
        harness._validate_label_mapping(invalid)
    except harness.ModelInvalid as exc:
        assert "11-label" in str(exc)
    else:
        raise AssertionError("invalid label mapping was accepted")


def test_tokenizer_must_provide_fast_offsets():
    harness._validate_tokenizer(SimpleNamespace(is_fast=True))
    try:
        harness._validate_tokenizer(SimpleNamespace(is_fast=False))
    except harness.ModelInvalid as exc:
        assert "fast" in str(exc)
    else:
        raise AssertionError("slow tokenizer was accepted")


def test_decode_spans_preserves_unicode_character_offsets():
    text = "A\u0301ก\u0e49\u0e33"
    assert text[0:2] == "A\u0301"
    assert text[2:5] == "ก\u0e49\u0e33"
    ids = [11, 12]
    offsets = [(0, 2), (2, 5)]
    labels = {0: "B-PERSON", 1: "I-PERSON"}
    probabilities = {0: 0.9, 1: 0.8}

    spans = harness._decode_spans(ids, offsets, labels, probabilities)
    assert spans[0][:3] == (0, 5, "PERSON")
    assert spans[0][3] == pytest.approx(0.85)


class _FakeTokenizer:
    is_fast = True

    def __call__(self, _text, **_kwargs):
        return {
            "input_ids": list(range(300)),
            "offset_mapping": [(index, index + 1) for index in range(300)],
        }


class _FakeInput:
    def __init__(self, name):
        self.name = name


class _FakeSession:
    def get_inputs(self):
        return [_FakeInput("input_ids"), _FakeInput("attention_mask")]

    def run(self, _outputs, inputs):
        import numpy as np

        input_ids = inputs["input_ids"][0]
        logits = np.full((1, len(input_ids), 11), -10.0, dtype=np.float32)
        start = int(input_ids[0])
        if start == _WINDOW_TOKENS - _STRIDE_TOKENS:
            logits[0, 10, 1] = 10.0
            logits[0, 11, 2] = 10.0
        return [logits]


def test_onnx_windows_use_production_overlap_stride_and_merge_spans():
    pytest.importorskip("numpy")
    id2label = {0: "O", 1: "B-PERSON", 2: "I-PERSON"}
    spans = harness._windowed_onnx_spans(
        _FakeSession(),
        _FakeTokenizer(),
        id2label,
        "synthetic long text",
        window_tokens=_WINDOW_TOKENS,
        stride_tokens=_STRIDE_TOKENS,
    )

    assert spans == [(190, 192, "PERSON", 1.0)]


def _worker_payload(spans):
    cases = {name: [list(span) for span in spans] for name, _text in harness._CASES}
    return {"cases": cases, "thresholds": {"PERSON": 0.95}}


def test_differential_comparison_and_parent_gates(monkeypatch, tmp_path):
    left = _worker_payload([(0, 4, "PERSON", 0.9000)])
    right = _worker_payload([(0, 4, "PERSON", 0.9005)])
    comparison = harness._compare_worker_outputs(left, right)
    assert comparison["span_and_label_agreement"] is True
    assert comparison["threshold_agreement"] is True
    assert harness._differential_passed(comparison) is True

    right["cases"]["thai_names"] = [[0, 4, "LOCATION", 0.9005]]
    mismatch = harness._compare_worker_outputs(left, right)
    assert mismatch["span_and_label_agreement"] is False
    assert harness._differential_passed(mismatch) is False

    def run_parent_case(name, *, fp32_mismatch=False, int8_mismatch=False, quantize=False):
        model_dir = tmp_path / f"model-{name}"
        model_dir.mkdir()
        output_dir = tmp_path / f"result-{name}"
        calls = []

        def fake_invoke(_args, worker, **_paths):
            calls.append(worker)
            if worker == "export":
                return {"status": "PASS", "metadata": {"thresholds": {}}}
            if worker == "quantize":
                return {"status": "PASS"}
            spans = [(0, 4, "PERSON", 0.9)]
            if worker == "onnx-fp32" and fp32_mismatch:
                spans = [(0, 4, "LOCATION", 0.9)]
            if worker == "onnx-int8" and int8_mismatch:
                spans = [(0, 4, "LOCATION", 0.9)]
            payload = _worker_payload(spans)
            payload["status"] = "PASS"
            return payload

        monkeypatch.setattr(harness, "_invoke_worker", fake_invoke)
        args = SimpleNamespace(
            repeats=1,
            model_dir=str(model_dir),
            output_dir=output_dir,
            gold_jsonl=None,
            quantize=quantize,
            smoke_only=True,
            require_model=True,
        )
        exit_code = harness._run_parent(args)
        result = json.loads((output_dir / "results.json").read_text(encoding="utf-8"))
        return exit_code, result, calls

    passed_code, passed, passed_calls = run_parent_case("pass")
    assert passed_code == 0
    assert passed["status"] == "SMOKE_ONLY"
    assert passed["int8"]["status"] == "NOT_EXECUTED"
    assert passed_calls == ["export", "pytorch", "onnx-fp32"]

    blocked_code, blocked, blocked_calls = run_parent_case(
        "fp32-mismatch",
        fp32_mismatch=True,
        quantize=True,
    )
    assert blocked_code == 1
    assert blocked["status"] == "FAIL"
    assert blocked["int8"]["status"] == "NOT_EXECUTED"
    assert "quantize" not in blocked_calls

    int8_code, int8, int8_calls = run_parent_case(
        "int8-mismatch",
        int8_mismatch=True,
        quantize=True,
    )
    assert int8_code == 1
    assert int8["status"] == "FAIL"
    assert int8["int8"]["status"] == "FAIL"
    assert int8_calls == ["export", "pytorch", "onnx-fp32", "quantize", "onnx-int8"]


def test_synthetic_gold_metrics_are_exact_span_metrics(tmp_path):
    gold_path = tmp_path / "gold.jsonl"
    gold_path.write_text(
        json.dumps(
            {
                "text": "synthetic text",
                "spans": [{"start": 0, "end": 4, "label": "PERSON"}],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    records = harness._load_jsonl_gold(gold_path)
    metrics = harness._prf(
        records,
        lambda _text: [(0, 4, "PERSON", 0.99)],
    )

    assert metrics == {
        "gold_spans": 1,
        "predicted_spans": 1,
        "true_positive": 1,
        "precision": 1.0,
        "recall": 1.0,
        "f1": 1.0,
    }


def test_threshold_filtering_is_explicit():
    spans = [(0, 4, "PERSON", 0.90), (5, 9, "LOCATION", 0.91)]
    assert harness._apply_thresholds(spans, {"PERSON": 0.95, "LOCATION": 0.90}) == [spans[1]]
