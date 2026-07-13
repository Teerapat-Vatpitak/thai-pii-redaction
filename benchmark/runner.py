"""Wire the corpus through the product's real detect_all() and score it."""
from __future__ import annotations

import os

from .corpus import build_corpus
from .scorer import score


def run_benchmark(engine: str = "crf", seed: int = 42, size: int = 200) -> dict:
    from pii_redactor.detectors import tb_detector
    from pii_redactor.detectors.aggregate import detect_all

    # The NER engine is a process-global lazy singleton keyed off the env var at
    # first load. Reset it (and restore afterward) so switching engines in one
    # process actually takes effect and the benchmark never pollutes other tests.
    prev_env = os.environ.get("AIGUARD_NER_ENGINE")
    prev_ner = tb_detector._ner
    os.environ["AIGUARD_NER_ENGINE"] = (
        "wangchanberta" if engine == "wangchanberta" else "thainer"
    )
    tb_detector._ner = None
    try:
        samples = build_corpus(seed=seed, size=size)
        predictions = []
        for s in samples:
            ents = detect_all(s.text)
            predictions.append([(e.span[0], e.span[1], e.data_type) for e in ents])
    finally:
        tb_detector._ner = prev_ner
        if prev_env is None:
            os.environ.pop("AIGUARD_NER_ENGINE", None)
        else:
            os.environ["AIGUARD_NER_ENGINE"] = prev_env

    report = score(samples, predictions)
    report["engine"] = engine
    report["seed"] = seed
    report["size"] = size
    return report


def render_table(report: dict) -> str:
    lines = [
        f"engine={report['engine']} seed={report['seed']} size={report['size']}",
        f"{'type':<16}{'n':>5}{'recall':>9}{'prec':>9}{'f2':>9}",
    ]
    for t in sorted(report["by_type"]):
        c = report["by_type"][t]
        n = report["corpus"]["by_type"].get(t, 0)
        lines.append(f"{t:<16}{n:>5}{c['recall']:>9.3f}{c['precision']:>9.3f}{c['f2']:>9.3f}")
    o = report["overall"]
    lines.append(
        f"{'OVERALL':<16}{report['corpus']['entities']:>5}"
        f"{o['recall']:>9.3f}{o['precision']:>9.3f}{o['f2']:>9.3f}"
    )
    lines.append(
        f"coverage_recall={o['coverage_recall']:.3f} exact_recall={o['exact_recall']:.3f}"
    )
    for sl in sorted(report["by_slice"]):
        s = report["by_slice"][sl]
        lines.append(
            f"slice {sl:<10} recall={s['recall']:.3f} coverage={s['coverage_recall']:.3f}"
        )
    return "\n".join(lines)
