"""Export safe span predictions from a frozen system worktree."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


class _CountedNER:
    def __init__(self, inner, counts):
        self._inner = inner
        self._counts = counts

    def tag(self, text):
        self._counts["attempted"] += 1
        try:
            result = self._inner.tag(text)
        except Exception:
            self._counts["skipped"] += 1
            raise
        self._counts["succeeded"] += 1
        return result

    def __getattr__(self, name):
        return getattr(self._inner, name)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--system-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    system_root = args.system_root.resolve()
    sys.path.insert(0, str(system_root))

    from benchmark.gold import load_gold
    from pii_redactor.detectors import tb_detector
    from pii_redactor.detectors.aggregate import detect_all

    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=system_root,
        capture_output=True,
        check=True,
        text=True,
    ).stdout.strip()
    counts = {"attempted": 0, "succeeded": 0, "skipped": 0}
    original_load = tb_detector._load_ner
    wrappers = {}

    def counted_load(name):
        inner = original_load(name)
        key = id(inner)
        if key not in wrappers:
            wrappers[key] = _CountedNER(inner, counts)
        return wrappers[key]

    old_env = os.environ.get("AIGUARD_NER_ENGINE")
    old_cache = dict(tb_detector._ner_cache)
    os.environ["AIGUARD_NER_ENGINE"] = "thainer"
    tb_detector._ner_cache = {}
    tb_detector._load_ner = counted_load
    try:
        samples = load_gold()
        documents = []
        for sample in samples:
            entities = detect_all(sample.text)
            documents.append(
                {
                    "doc_id": sample.template_id,
                    "predictions": [
                        [entity.span[0], entity.span[1], entity.data_type] for entity in entities
                    ],
                }
            )
    finally:
        tb_detector._load_ner = original_load
        tb_detector._ner_cache = old_cache
        if old_env is None:
            os.environ.pop("AIGUARD_NER_ENGINE", None)
        else:
            os.environ["AIGUARD_NER_ENGINE"] = old_env

    payload = {
        "schema": 1,
        "system_commit": commit,
        "engine": "thainer-crf",
        "ner_chunks": counts,
        "documents": documents,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
