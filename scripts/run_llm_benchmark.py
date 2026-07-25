"""Score a hosted LLM as a PII detector on the gold set.

    python scripts/run_llm_benchmark.py --provider pathumma
    python scripts/run_llm_benchmark.py --provider dotblue:openai/gpt-4o-mini

Every response is cached under benchmark/reports/llm_cache/<provider>/ keyed by
document id, so re-scoring after a prompt or scorer change costs nothing and a
run interrupted halfway resumes instead of re-spending the quota. Pass --refresh
to ignore the cache.

The gold set contains only fabricated PII, which is what makes sending it to a
third-party endpoint acceptable at all. Do not point this at real documents.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmark.gold import load_gold
from benchmark.llm_providers import ProviderUnavailable, build_caller
from benchmark.llm_strategy import detect_with_llm
from benchmark.scorer import score

CACHE_ROOT = Path(__file__).resolve().parents[1] / "benchmark" / "reports" / "llm_cache"


def _cache_dir(spec: str) -> Path:
    return CACHE_ROOT / spec.replace("/", "_").replace(":", "_")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="run_llm_benchmark")
    ap.add_argument(
        "--provider", required=True, help="pathumma | dotblue:<model> | thaillm:<model>"
    )
    ap.add_argument("--limit", type=int, default=0, help="first N documents (0 = all)")
    ap.add_argument("--refresh", action="store_true", help="ignore cached responses")
    ap.add_argument("--json", default=None, help="write the scored report here")
    args = ap.parse_args(argv)

    try:
        call = build_caller(args.provider)
    except ProviderUnavailable as exc:
        print(f"provider unavailable: {exc}", file=sys.stderr)
        return 2

    samples = load_gold()
    if args.limit:
        samples = samples[: args.limit]

    cache = _cache_dir(args.provider)
    cache.mkdir(parents=True, exist_ok=True)

    predictions: list[list[tuple[int, int, str]]] = []
    stats = {"cached": 0, "called": 0, "failed": 0, "unlocatable": 0, "empty": 0}
    rejected_types: dict[str, int] = {}
    started = time.monotonic()

    for n, s in enumerate(samples, 1):
        path = cache / f"{s.template_id}.json"
        if path.exists() and not args.refresh:
            rec = json.loads(path.read_text(encoding="utf-8"))
            stats["cached"] += 1
        else:
            try:
                spans, meta = detect_with_llm(s.text, call)
                rec = {"spans": spans, "meta": meta}
                path.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
                stats["called"] += 1
            except Exception as exc:
                # abandon the other 251; the failure is counted and scored as
                # "found nothing", which is the honest reading of no answer.
                print(f"  {s.template_id}: {type(exc).__name__}: {exc}"[:200], file=sys.stderr)
                rec = {"spans": [], "meta": {"error": type(exc).__name__}}
                stats["failed"] += 1
        predictions.append([tuple(x) for x in rec["spans"]])
        meta = rec.get("meta", {})
        stats["unlocatable"] += meta.get("unlocatable", 0)
        stats["empty"] += bool(meta.get("empty_response"))
        for t in meta.get("rejected_types", []):
            rejected_types[t] = rejected_types.get(t, 0) + 1
        if n % 25 == 0 or n == len(samples):
            print(f"  {n}/{len(samples)} ({time.monotonic() - started:.0f}s)", file=sys.stderr)

    report = score(samples, predictions)
    report["provider"] = args.provider
    report["source"] = "gold"
    report["run"] = stats
    report["invented_types"] = rejected_types
    report["wall_seconds"] = round(time.monotonic() - started, 1)

    o = report["overall"]
    print(f"\nprovider={args.provider}  documents={len(samples)}")
    print(f"{'type':<16}{'n':>5}{'recall':>9}{'prec':>9}{'f2':>9}")
    for t in sorted(report["by_type"]):
        c = report["by_type"][t]
        print(
            f"{t:<16}{report['corpus']['by_type'].get(t, 0):>5}"
            f"{c['recall']:>9.3f}{c['precision']:>9.3f}{c['f2']:>9.3f}"
        )
    print(
        f"{'OVERALL':<16}{report['corpus']['entities']:>5}"
        f"{o['recall']:>9.3f}{o['precision']:>9.3f}{o['f2']:>9.3f}"
    )
    print(f"coverage_recall={o['coverage_recall']:.3f} exact_recall={o['exact_recall']:.3f}")
    neg = report["by_slice"].get("negative", {})
    if neg.get("gold_entities") == 0:
        print(
            f"negative slice: false_positives={neg['false_positives']} "
            f"clean_docs={neg['clean_docs']}/{neg['documents']} ({neg['clean_doc_rate']:.3f})"
        )
    print(f"run={stats} invented_types={rejected_types} wall={report['wall_seconds']}s")

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
