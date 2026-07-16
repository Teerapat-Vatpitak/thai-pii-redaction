from __future__ import annotations

import argparse
import json
import sys

from .runner import run_benchmark, render_table, run_strategy_comparison, render_strategy_table


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="benchmark")
    ap.add_argument("--engine", default="crf", choices=["crf", "wangchanberta"])
    ap.add_argument("--source", default="synthetic", choices=["synthetic", "gold"])
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--size", type=int, default=200)
    ap.add_argument("--compare-strategies", action="store_true",
                    help="score crf/wcb/union/route on one corpus")
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)

    if args.compare_strategies:
        reports = run_strategy_comparison(source=args.source, seed=args.seed, size=args.size)
        print(render_strategy_table(reports))
        report_out = reports
    else:
        report_out = run_benchmark(
            engine=args.engine, seed=args.seed, size=args.size, source=args.source
        )
        print(render_table(report_out))

    if args.json:
        import os
        os.makedirs(os.path.dirname(args.json) or ".", exist_ok=True)
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(report_out, f, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
