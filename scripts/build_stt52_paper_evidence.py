"""Build reproducible aggregate evidence for the STT52 paper."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmark.human_review import STT52_GOLD_COMMIT, load_gold_at_commit
from benchmark.paper_evidence import build_system_evidence, prediction_records


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
    parser.add_argument("--system-worktree", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--predictions-output", type=Path, required=True)
    parser.add_argument("--bootstrap-iterations", type=int, default=10_000)
    parser.add_argument("--bootstrap-seed", type=int, default=5252)
    args = parser.parse_args(argv)

    repo = Path(__file__).resolve().parents[1]
    if _git_text(repo, "status", "--porcelain", "--untracked-files=no"):
        raise SystemExit("evaluator worktree has tracked changes")
    evaluator_commit = _git_text(repo, "rev-parse", "HEAD")
    system_root = args.system_worktree.resolve()
    system_commit = _git_text(system_root, "rev-parse", "HEAD")
    if system_commit != STT52_GOLD_COMMIT:
        raise SystemExit("system worktree is not at the frozen STT52 commit")
    if _git_text(system_root, "status", "--porcelain", "--untracked-files=no"):
        raise SystemExit("system worktree has tracked changes")

    exporter = repo / "scripts" / "export_frozen_stt52_predictions.py"
    with tempfile.TemporaryDirectory(prefix="stt52-evidence-") as temp_dir:
        predictions_path = Path(temp_dir) / "predictions.json"
        subprocess.run(
            [
                sys.executable,
                str(exporter),
                "--system-root",
                str(system_root),
                "--output",
                str(predictions_path),
            ],
            cwd=system_root,
            check=True,
        )
        exported = json.loads(predictions_path.read_text(encoding="utf-8"))

    samples, reference = load_gold_at_commit(repo)
    expected_ids = [sample.template_id for sample in samples]
    actual_ids = [record["doc_id"] for record in exported["documents"]]
    if actual_ids != expected_ids:
        raise SystemExit("prediction documents do not match the frozen corpus")
    predictions = [
        [tuple(row) for row in record["predictions"]] for record in exported["documents"]
    ]
    evidence = build_system_evidence(
        samples,
        predictions,
        reference=reference,
        system_commit=system_commit,
        ner_chunks=exported["ner_chunks"],
        bootstrap_iterations=args.bootstrap_iterations,
        bootstrap_seed=args.bootstrap_seed,
    )
    evidence["evaluator"] = {
        "commit": evaluator_commit,
        "scorer_sha256": _sha256(repo / "benchmark" / "scorer.py"),
        "evidence_builder_sha256": _sha256(repo / "benchmark" / "paper_evidence.py"),
        "exporter_sha256": _sha256(exporter),
    }

    expected = {
        "documents": 252,
        "entities": 641,
        "tp": 561,
        "fp": 378,
        "fn": 80,
        "unmatched_address": 183,
        "inside_address": 175,
        "outside_address": 8,
    }
    score = evidence["score"]
    audit = evidence["address_posthoc"]
    observed = {
        "documents": score["corpus"]["samples"],
        "entities": score["corpus"]["entities"],
        "tp": score["overall"]["tp"],
        "fp": score["overall"]["fp"],
        "fn": score["overall"]["fn"],
        "unmatched_address": audit["unmatched_predictions"],
        "inside_address": audit["inside_gold_address"],
        "outside_address": audit["outside_gold_address"],
    }
    if observed != expected:
        raise SystemExit("frozen paper counts did not reproduce")

    predictions_output = args.predictions_output.resolve()
    predictions_output.parent.mkdir(parents=True, exist_ok=True)
    records = prediction_records(samples, predictions)
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
