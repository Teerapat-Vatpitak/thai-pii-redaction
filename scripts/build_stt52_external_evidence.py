"""Freeze the aggregate external-baseline evidence for the STT52 paper."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmark.human_review import load_gold_at_commit
from benchmark.llm_providers import provider_request_config
from benchmark.paper_evidence import build_external_evidence, prediction_records
from benchmark.scorer import score
from scripts.run_llm_benchmark import (
    CACHE_SCHEMA,
    PROMPT_IDENTITY,
    _cache_dir,
    _cache_path,
    _cache_provenance,
    _load_frozen_gold,
    _read_cached,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_text(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        check=True,
        text=True,
    ).stdout.strip()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--gold-jsonl", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--predictions-output", type=Path, required=True)
    parser.add_argument("--fill-report", type=Path, required=True)
    args = parser.parse_args(argv)

    repo = Path(__file__).resolve().parents[1]
    if _git_text(repo, "status", "--porcelain", "--untracked-files=no"):
        raise SystemExit("evaluator worktree has tracked changes")
    evaluator_commit = _git_text(repo, "rev-parse", "HEAD")
    _, reference = load_gold_at_commit(repo)
    gold_raw = args.gold_jsonl.read_bytes()
    normalized_sha256 = hashlib.sha256(gold_raw.replace(b"\r\n", b"\n")).hexdigest()
    if normalized_sha256 != reference["sha256"]:
        raise SystemExit("external baseline gold file is not the frozen paper corpus")

    report = json.loads(args.report.read_text(encoding="utf-8"))
    fill_report = json.loads(args.fill_report.read_text(encoding="utf-8"))
    provider_config = provider_request_config("tokenmind")
    prompt_provenance = _cache_provenance(provider_config, PROMPT_IDENTITY)
    if (
        report.get("provider_config") != provider_config
        or fill_report.get("provider_config") != provider_config
        or report.get("prompt_sha256") != prompt_provenance["prompt_sha256"]
        or fill_report.get("prompt_sha256") != prompt_provenance["prompt_sha256"]
        or report.get("cache_schema") != CACHE_SCHEMA
        or fill_report.get("cache_schema") != CACHE_SCHEMA
        or fill_report.get("cache_only")
        or fill_report.get("corpus_sha256") != report.get("corpus_sha256")
        or fill_report.get("gold_version") != report.get("gold_version")
    ):
        raise SystemExit("external baseline reports use different request settings")
    fill_run = fill_report.get("run", {})
    if (
        fill_run.get("failed") != 0
        or fill_run.get("cached", 0) + fill_run.get("called", 0) != reference["documents"]
    ):
        raise SystemExit("external baseline cache fill is incomplete")

    samples, _ = _load_frozen_gold(args.gold_jsonl)
    predictions = []
    cache = _cache_dir("tokenmind")
    for sample in samples:
        cache_path = _cache_path(cache, sample, provider_config)
        cached = _read_cached(cache_path, sample.text, prompt_provenance)
        if cached is None:
            raise SystemExit("external baseline cache is incomplete")
        predictions.append([tuple(row) for row in cached["spans"]])

    ci = report["confidence_intervals"]["overall_f2"]
    rescored = score(
        samples,
        predictions,
        bootstrap_iters=ci["iterations"],
        bootstrap_seed=ci["seed"],
    )
    for key in (
        "corpus",
        "overall",
        "by_type",
        "by_slice",
        "confidence_intervals",
        "shared_11",
        "out_of_scheme_predictions",
        "type_scheme",
    ):
        if rescored[key] != report[key]:
            raise SystemExit("external predictions do not reproduce the report")

    evidence = build_external_evidence(
        report,
        reference=reference,
        cache_fill={
            "cached": fill_run["cached"],
            "called": fill_run["called"],
            "failed": fill_run["failed"],
            "synthetic_documents_only": True,
            "report_sha256": _sha256(args.fill_report),
        },
    )
    evidence["evaluator"] = {
        "commit": evaluator_commit,
        "scorer_sha256": _sha256(repo / "benchmark" / "scorer.py"),
        "runner_sha256": _sha256(repo / "scripts" / "run_llm_benchmark.py"),
        "evidence_builder_sha256": _sha256(repo / "benchmark" / "paper_evidence.py"),
    }
    evidence["corpus"]["checkout_sha256"] = hashlib.sha256(gold_raw).hexdigest()
    records = prediction_records(samples, predictions)
    predictions_output = args.predictions_output.resolve()
    predictions_output.parent.mkdir(parents=True, exist_ok=True)
    predictions_output.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )
    evidence["predictions"] = {
        "path": predictions_output.relative_to(repo).as_posix(),
        "sha256": _sha256(predictions_output),
        "contains_text": False,
    }

    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"wrote aggregate evidence to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
