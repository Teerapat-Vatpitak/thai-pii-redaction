"""Score a hosted LLM as a PII detector on the gold set.

    python scripts/run_llm_benchmark.py --provider pathumma
    python scripts/run_llm_benchmark.py --provider dotblue:openai/gpt-4o-mini

Each response's parsed (type, value) pairs -- not the response body itself --
are cached under benchmark/reports/llm_cache/<provider>/. Each row is bound to
the model settings, prompt and document text. A scorer-only change can reuse
the cache. Pass --refresh to ignore it.

The gold set contains only fabricated PII, which is what makes sending it to a
third-party endpoint acceptable at all. Do not point this at real documents.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from dataclasses import replace
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmark.gold import _DATA_PATH, GOLD_VERSION, load_gold, parse_gold
from benchmark.llm_providers import (
    ProviderUnavailable,
    build_caller,
    provider_request_config,
)
from benchmark.llm_strategy import (
    SYSTEM_PROMPT,
    USER_TEMPLATE,
    detect_with_llm,
    parse_values,
    score_values,
)
from benchmark.scorer import score
from benchmark.types import SHARED_ENTITY_TYPES

CACHE_ROOT = Path(__file__).resolve().parents[1] / "benchmark" / "reports" / "llm_cache"
CACHE_SCHEMA = 2

# Both prompt parts can change the response.
PROMPT_IDENTITY = SYSTEM_PROMPT + "\x00" + USER_TEMPLATE


def _cache_dir(spec: str) -> Path:
    return CACHE_ROOT / spec.replace("/", "_").replace(":", "_")


def _cache_provenance(provider_config: dict, prompt: str) -> dict:
    return {
        "schema": CACHE_SCHEMA,
        "provider": provider_config,
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
    }


def _cache_identity(provider_config: dict, prompt: str, text: str) -> str:
    """Bind a cache row to the request settings, prompt and text."""
    h = hashlib.sha256()
    config = json.dumps(provider_config, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    for part in (config, prompt, text):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()[:32]


def _cache_path(cache: Path, sample, provider_config: dict) -> Path:
    identity = _cache_identity(provider_config, PROMPT_IDENTITY, sample.text)
    return cache / f"{sample.template_id}-{identity}.json"


def _read_cached(path: Path, text: str, expected_provenance: dict) -> dict | None:
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if cached.get("schema") != CACHE_SCHEMA or cached.get("provenance") != expected_provenance:
        return None
    values = cached.get("values")
    if not isinstance(values, list):
        return None
    clean_values: list[tuple[str, str]] = []
    for row in values:
        if (
            not isinstance(row, (list, tuple))
            or len(row) != 2
            or not all(isinstance(part, str) for part in row)
        ):
            return None
        clean_values.append((row[0], row[1]))
    return score_values(text, clean_values)


def _load_frozen_gold(path: Path) -> tuple[list, str]:
    raw = path.read_bytes()
    records = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
    samples = []
    for record in records:
        try:
            samples.append(
                parse_gold(
                    str(record["doc_id"]),
                    str(record["slice"]),
                    str(record["annotated"]),
                )
            )
        except (KeyError, TypeError) as exc:
            raise ValueError("frozen gold JSONL has an invalid record") from exc
    if not samples:
        raise ValueError("frozen gold JSONL has no documents")
    return samples, hashlib.sha256(raw).hexdigest()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="run_llm_benchmark")
    ap.add_argument(
        "--provider",
        required=True,
        help="pathumma | tokenmind | dotblue:<model> | thaillm:<model>",
    )
    ap.add_argument("--limit", type=int, default=0, help="first N documents (0 = all)")
    ap.add_argument("--refresh", action="store_true", help="ignore cached responses")
    ap.add_argument(
        "--cache-only",
        action="store_true",
        help="rescore a complete cache without credentials or network",
    )
    ap.add_argument(
        "--gold-jsonl",
        type=Path,
        default=None,
        help="frozen gold JSONL to rescore (cache-only only)",
    )
    ap.add_argument(
        "--gold-version",
        default=None,
        help="version label required with --gold-jsonl",
    )
    ap.add_argument(
        "--allow-frozen-network",
        action="store_true",
        help="allow missing frozen-gold cache rows to call the provider",
    )
    ap.add_argument("--json", default=None, help="write the scored report here")
    ap.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="seconds to wait between API calls (default 1.0; 0 disables)",
    )
    ap.add_argument("--bootstrap-iterations", type=int, default=1000)
    ap.add_argument("--bootstrap-seed", type=int, default=0)
    args = ap.parse_args(argv)

    if args.cache_only and args.refresh:
        print("--cache-only cannot be combined with --refresh", file=sys.stderr)
        return 2
    if args.gold_jsonl is not None and not args.cache_only and not args.allow_frozen_network:
        print(
            "--gold-jsonl needs --cache-only or --allow-frozen-network",
            file=sys.stderr,
        )
        return 2
    if args.allow_frozen_network and (args.gold_jsonl is None or args.cache_only):
        print(
            "--allow-frozen-network is only for a live frozen-gold run",
            file=sys.stderr,
        )
        return 2
    if args.gold_jsonl is not None and not (args.gold_version or "").strip():
        print("--gold-version is required with --gold-jsonl", file=sys.stderr)
        return 2
    if args.gold_jsonl is None and args.gold_version is not None:
        print("--gold-version is only used with --gold-jsonl", file=sys.stderr)
        return 2
    if args.bootstrap_iterations < 1:
        print("--bootstrap-iterations must be positive", file=sys.stderr)
        return 2
    try:
        provider_config = provider_request_config(args.provider)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    cache_provenance = _cache_provenance(provider_config, PROMPT_IDENTITY)

    if args.gold_jsonl is None:
        samples = load_gold()
        gold_version = GOLD_VERSION
        corpus_sha256 = hashlib.sha256(_DATA_PATH.read_bytes()).hexdigest()
    else:
        try:
            samples, corpus_sha256 = _load_frozen_gold(args.gold_jsonl)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            print(f"cannot load frozen gold: {type(exc).__name__}", file=sys.stderr)
            return 2
        gold_version = args.gold_version.strip()
    if args.limit:
        samples = samples[: args.limit]

    cache = _cache_dir(args.provider)
    if not args.cache_only:
        cache.mkdir(parents=True, exist_ok=True)

    preloaded: list[dict] = []
    if args.cache_only:
        misses = 0
        for sample in samples:
            rec = _read_cached(
                _cache_path(cache, sample, provider_config),
                sample.text,
                cache_provenance,
            )
            if rec is None:
                misses += 1
            else:
                preloaded.append(rec)
        if misses:
            print(
                f"cache-only failed: {misses} of {len(samples)} cache entries are missing or invalid",
                file=sys.stderr,
            )
            return 3
        call = None
    else:
        try:
            call = build_caller(args.provider)
        except ProviderUnavailable as exc:
            print(f"provider unavailable: {exc}", file=sys.stderr)
            return 2

    predictions: list[list[tuple[int, int, str]]] = []
    untyped_predictions: list[list[tuple[int, int, str]]] = []
    stats = {"cached": 0, "called": 0, "failed": 0, "unlocatable": 0, "no_values": 0}
    out_of_scheme_type_rows = 0
    # Indices whose document the endpoint never answered for. Scoring them as
    # "found nothing" is right for the headline number -- a service that will
    # not answer protects nothing -- but it buries the model's detection
    # ability under the endpoint's reliability. Both are reported.
    answered: list[int] = []
    errors: dict[str, int] = {}
    started = time.monotonic()

    for n, s in enumerate(samples, 1):
        path = _cache_path(cache, s, provider_config)
        raw: str | None = None
        rec: dict | None = None
        if args.cache_only:
            rec = preloaded[n - 1]
            stats["cached"] += 1
        elif path.exists() and not args.refresh:
            rec = _read_cached(path, s.text, cache_provenance)
            if rec is not None:
                stats["cached"] += 1
        if rec is None:
            try:
                assert call is not None
                raw, rec = detect_with_llm(s.text, call)
                path.write_text(
                    json.dumps(
                        {
                            "schema": CACHE_SCHEMA,
                            "provenance": cache_provenance,
                            "values": parse_values(raw),
                        },
                        ensure_ascii=False,
                        indent=1,
                    ),
                    encoding="utf-8",
                )
                stats["called"] += 1
            except Exception as exc:
                # One bad document must not abandon the other 251.
                label = type(exc).__name__
                if isinstance(exc, httpx.HTTPStatusError):
                    label = f"HTTP {exc.response.status_code}"
                print(f"  provider call failed: {label}", file=sys.stderr)
                rec = {"spans": [], "untyped_spans": [], "meta": {"error": label}}
                stats["failed"] += 1
                errors[label] = errors.get(label, 0) + 1
            # Only after a real call. Sleeping on a cache hit would make
            # re-scoring an already-fetched run cost minutes for nothing.
            if args.delay > 0:
                time.sleep(args.delay)
        predictions.append([tuple(x) for x in rec["spans"]])
        untyped_predictions.append([tuple(x) for x in rec.get("untyped_spans", [])])
        meta = rec.get("meta", {})
        # Failures are never written to the cache, so an errored record can only
        # have come from this run's exception path, which already counted it.
        if not meta.get("error"):
            answered.append(len(predictions) - 1)
        stats["unlocatable"] += meta.get("unlocatable", 0)
        stats["no_values"] += bool(meta.get("no_values"))
        out_of_scheme_type_rows += meta.get("out_of_scheme_types", 0)
        if n % 25 == 0 or n == len(samples):
            print(f"  {n}/{len(samples)} ({time.monotonic() - started:.0f}s)", file=sys.stderr)

    if args.cache_only and (
        stats["cached"] != len(samples) or stats["called"] != 0 or stats["failed"] != 0
    ):
        print("cache-only integrity check failed", file=sys.stderr)
        return 3

    report = score(
        samples,
        predictions,
        bootstrap_iters=args.bootstrap_iterations,
        bootstrap_seed=args.bootstrap_seed,
    )
    # Relabel both sides to measure location without type.
    untyped_score_type = SHARED_ENTITY_TYPES[0]
    untyped_samples = [
        replace(s, spans=[replace(g, entity_type=untyped_score_type) for g in s.spans])
        for s in samples
    ]
    untyped_score_predictions = [
        [(start, end, untyped_score_type) for start, end, _ in document]
        for document in untyped_predictions
    ]
    report["untyped"] = score(
        untyped_samples,
        untyped_score_predictions,
        bootstrap_iters=args.bootstrap_iterations,
        bootstrap_seed=args.bootstrap_seed,
    )
    report["provider"] = args.provider
    report["provider_config"] = provider_config
    report["prompt_sha256"] = cache_provenance["prompt_sha256"]
    report["cache_schema"] = CACHE_SCHEMA
    report["source"] = "gold"
    report["gold_version"] = gold_version
    report["corpus_sha256"] = corpus_sha256
    report["run"] = stats
    report["errors"] = errors
    report["out_of_scheme_type_rows"] = out_of_scheme_type_rows
    report["cache_only"] = args.cache_only
    report["frozen_network_allowed"] = args.allow_frozen_network
    report["wall_seconds"] = round(time.monotonic() - started, 1)
    report["delay_seconds"] = args.delay

    # Same scorer over only the documents the endpoint actually answered.
    # Without this, a provider that refuses a third of the set is reported as a
    # weak detector when it is really an unreliable service -- two different
    # problems with two different fixes. The headline number above stays the
    # full set, because for a user a refused document is not protected either.
    report["answered_only"] = None
    if answered and len(answered) < len(samples):
        report["answered_only"] = {
            "documents": len(answered),
            **score(
                [samples[i] for i in answered],
                [predictions[i] for i in answered],
                bootstrap_iters=args.bootstrap_iterations,
                bootstrap_seed=args.bootstrap_seed,
            ),
        }

    o = report["overall"]
    print(
        f"\nprovider={args.provider} gold={gold_version} "
        f"documents={len(samples)} cache_only={args.cache_only}"
    )
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
    shared = report["shared_11"]["overall"]
    print(
        f"{'SHARED-11':<16}{report['corpus']['entities']:>5}"
        f"{shared['recall']:>9.3f}{shared['precision']:>9.3f}{shared['f2']:>9.3f}"
        f"   (excluded={report['shared_11']['excluded_predictions']})"
    )
    ci = report["confidence_intervals"]["overall_f2"]
    print(
        f"overall_f2_ci{int(ci['confidence'] * 100)}="
        f"{ci['lower']:.3f}-{ci['upper']:.3f} "
        f"({ci['method']}, {ci['unit']}, n={ci['iterations']}, seed={ci['seed']})"
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
            f"untouched_docs={neg['clean_docs']}/{neg['documents']} "
            f"({neg['clean_doc_rate']:.3f})"
        )
    ao = report.get("answered_only")
    if ao:
        a = ao["overall"]
        print(
            f"{'ANSWERED ONLY':<16}{ao['corpus']['entities']:>5}"
            f"{a['recall']:>9.3f}{a['precision']:>9.3f}{a['f2']:>9.3f}"
            f"   ({ao['documents']}/{len(samples)} documents the endpoint answered)"
        )
    print(
        f"run={stats} errors={errors} out_of_scheme_type_rows={out_of_scheme_type_rows} "
        f"wall={report['wall_seconds']}s"
    )

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
