from __future__ import annotations

import argparse
import json
import sys

from .runner import render_strategy_table, render_table, run_benchmark, run_strategy_comparison


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="benchmark")
    ap.add_argument("--engine", default="crf", choices=["crf", "wangchanberta", "union"])
    ap.add_argument("--source", default="synthetic", choices=["synthetic", "gold", "blind"])
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--size", type=int, default=200)
    ap.add_argument(
        "--compare-strategies", action="store_true", help="score crf/wcb/union/route on one corpus"
    )
    ap.add_argument(
        "--reason",
        default="",
        help="blind runs only: why this reveal is happening (recorded in the audit log)",
    )
    ap.add_argument(
        "--verify-blind-log",
        action="store_true",
        help="verify the blind score log hash chain and exit",
    )
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)

    if args.verify_blind_log:
        from . import blind

        n = blind.verify_log(blind.DATA_DIR / blind.LOG_NAME)
        print(f"blind score log OK: {n} entries, chain intact")
        return 0

    if args.source == "blind":
        import os

        from . import blind

        if args.compare_strategies:
            print("--compare-strategies is not available for the blind set", file=sys.stderr)
            return 2
        try:
            result = blind.run_blind(
                engine=args.engine,
                key_file=os.environ.get("AIGUARD_BLIND_KEY_FILE"),
                reason=args.reason,
            )
        except blind.BlindError as exc:
            print(f"blind: {exc}", file=sys.stderr)
            return 2
        print(blind.render_blind_table(result))
        report_out = result
        if args.json:
            import os as _os

            _os.makedirs(_os.path.dirname(args.json) or ".", exist_ok=True)
            with open(args.json, "w", encoding="utf-8") as f:
                json.dump(report_out, f, ensure_ascii=False, indent=2)
        return 0

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
