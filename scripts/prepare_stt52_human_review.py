"""Create a blind packet for a second human annotator."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmark.human_review import (
    STT52_GOLD_COMMIT,
    STT52_GUIDELINE_PATH,
    STT52_REVIEW_PER_SLICE,
    STT52_REVIEW_SAMPLE_ID,
    STT52_REVIEW_SEED,
    build_review_packet,
    load_gold_at_commit,
)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--gold-commit", default=STT52_GOLD_COMMIT)
    args = parser.parse_args(argv)

    repo = Path(__file__).resolve().parents[1]
    samples, reference = load_gold_at_commit(repo, args.gold_commit)
    guideline_path = (repo / STT52_GUIDELINE_PATH).resolve()
    guideline_raw = guideline_path.read_bytes()
    packet = build_review_packet(
        samples,
        per_slice=STT52_REVIEW_PER_SLICE,
        seed=STT52_REVIEW_SEED,
        sample_id=STT52_REVIEW_SAMPLE_ID,
        reference=reference,
        guideline={
            "path": STT52_GUIDELINE_PATH,
            "sha256": hashlib.sha256(guideline_raw).hexdigest(),
        },
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(packet, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {len(packet['documents'])} documents to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
