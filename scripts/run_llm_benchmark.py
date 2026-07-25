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
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmark.gold import load_gold
from benchmark.llm_providers import ProviderUnavailable, build_caller
from benchmark.llm_strategy import UNTYPED, detect_with_llm, score_raw
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
    ap.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="seconds to wait between API calls (default 1.0; 0 disables)",
    )
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
    untyped_predictions: list[list[tuple[int, int, str]]] = []
    stats = {"cached": 0, "called": 0, "failed": 0, "unlocatable": 0, "empty": 0}
    rejected_types: dict[str, int] = {}
    started = time.monotonic()

    for n, s in enumerate(samples, 1):
        path = cache / f"{s.template_id}.json"
        raw: str | None = None
        rec: dict | None = None
        if path.exists() and not args.refresh:
            cached = json.loads(path.read_text(encoding="utf-8"))
            raw = cached.get("raw")
            if raw is None:
                # Pre-raw cache entry. It cannot produce the type-agnostic view,
                # so refetch rather than silently mixing two kinds of number in
                # one report.
                raw = None
            else:
                rec = score_raw(s.text, raw)
                stats["cached"] += 1
        if rec is None:
            try:
                raw, rec = detect_with_llm(s.text, call)
                path.write_text(
                    json.dumps({"raw": raw, **rec}, ensure_ascii=False, indent=1),
                    encoding="utf-8",
                )
                stats["called"] += 1
            except Exception as exc:
                # One bad document must not abandon the other 251; the failure
                # is counted and scored as "found nothing", which is the honest
                # reading of no answer.
                print(f"  {s.template_id}: {type(exc).__name__}: {exc}"[:200], file=sys.stderr)
                rec = {"spans": [], "untyped_spans": [], "meta": {"error": type(exc).__name__}}
                stats["failed"] += 1
            # Only after a real call. Sleeping on a cache hit would make
            # re-scoring an already-fetched run cost minutes for nothing.
            if args.delay > 0:
                time.sleep(args.delay)
        predictions.append([tuple(x) for x in rec["spans"]])
        untyped_predictions.append([tuple(x) for x in rec.get("untyped_spans", [])])
        meta = rec.get("meta", {})
        stats["unlocatable"] += meta.get("unlocatable", 0)
        stats["empty"] += bool(meta.get("empty_response"))
        for t in meta.get("rejected_types", []):
            rejected_types[t] = rejected_types.get(t, 0) + 1
        if n % 25 == 0 or n == len(samples):
            print(f"  {n}/{len(samples)} ({time.monotonic() - started:.0f}s)", file=sys.stderr)

    report = score(samples, predictions)
    # Type-agnostic view: relabel BOTH sides to one type and reuse the same
    # scorer, so "found the PII" is measured without "named it correctly"
    # riding along. Relabelling is why this cannot just read coverage_recall
    # off the strict run -- that run has already dropped the rows whose type
    # name was not in the vocabulary.
    untyped_samples = [
        replace(s, spans=[replace(g, entity_type=UNTYPED) for g in s.spans]) for s in samples
    ]
    report["untyped"] = score(untyped_samples, untyped_predictions)
    report["provider"] = args.provider
    report["source"] = "gold"
    report["run"] = stats
    report["invented_types"] = rejected_types
    report["wall_seconds"] = round(time.monotonic() - started, 1)
    report["delay_seconds"] = args.delay

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
    u = report["untyped"]["overall"]
    print(
        f"{'UNTYPED':<16}{report['corpus']['entities']:>5}"
        f"{u['recall']:>9.3f}{u['precision']:>9.3f}{u['f2']:>9.3f}"
        f"   (type ignored; coverage_recall={u['coverage_recall']:.3f})"
    )
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
