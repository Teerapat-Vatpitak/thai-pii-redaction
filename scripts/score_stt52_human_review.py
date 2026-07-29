"""Score a completed second-human annotation packet."""

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
    load_gold_at_commit,
    score_review_packet,
)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("packet")
    parser.add_argument("--json", required=True)
    parser.add_argument("--gold-commit", default=STT52_GOLD_COMMIT)
    args = parser.parse_args(argv)

    repo = Path(__file__).resolve().parents[1]
    packet = json.loads(Path(args.packet).read_text(encoding="utf-8"))
    reference, provenance = load_gold_at_commit(repo, args.gold_commit)
    guideline_path = (repo / STT52_GUIDELINE_PATH).resolve()
    guideline_sha256 = hashlib.sha256(guideline_path.read_bytes()).hexdigest()
    if packet.get("guideline") != {
        "path": STT52_GUIDELINE_PATH,
        "sha256": guideline_sha256,
    }:
        raise SystemExit("review packet uses a different guideline")
    report = score_review_packet(
        packet,
        reference,
        reference_provenance=provenance,
        guideline_sha256=guideline_sha256,
    )
    output = Path(args.json)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    exact = report["agreement"]["exact_span"]["f1"]
    overlap = report["agreement"]["overlap_span"]["f1"]
    character = report["agreement"]["character_label"]["f1"]
    print(
        f"documents={report['documents']} exact_f1={exact:.3f} "
        f"overlap_f1={overlap:.3f} character_f1={character:.3f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
