"""Wire the corpus through the product's real detect_all() and score it."""

from __future__ import annotations

import os

from .corpus import build_corpus
from .gold import load_gold
from .scorer import score


def run_benchmark(
    engine: str = "crf", seed: int = 42, size: int = 200, source: str = "synthetic"
) -> dict:
    from pii_redactor.detectors import tb_detector
    from pii_redactor.detectors.aggregate import detect_all

    # The NER engine is a process-global lazy singleton keyed off the env var at
    # first load. Reset it (and restore afterward) so switching engines in one
    # process actually takes effect and the benchmark never pollutes other tests.
    prev_env = os.environ.get("AIGUARD_NER_ENGINE")
    prev_ner = dict(tb_detector._ner_cache)
    os.environ["AIGUARD_NER_ENGINE"] = "wangchanberta" if engine == "wangchanberta" else "thainer"
    tb_detector._ner_cache = {}
    try:
        samples = load_gold() if source == "gold" else build_corpus(seed=seed, size=size)
        predictions = []
        for s in samples:
            ents = detect_all(s.text)
            predictions.append([(e.span[0], e.span[1], e.data_type) for e in ents])
    finally:
        tb_detector._ner_cache = prev_ner
        if prev_env is None:
            os.environ.pop("AIGUARD_NER_ENGINE", None)
        else:
            os.environ["AIGUARD_NER_ENGINE"] = prev_env

    report = score(samples, predictions)
    report["engine"] = engine
    report["seed"] = seed
    report["size"] = size
    report["source"] = source
    return report


def render_table(report: dict) -> str:
    lines = [
        f"engine={report['engine']} source={report.get('source', 'synthetic')} "
        f"seed={report['seed']} size={report['size']}",
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
    lines.append(f"coverage_recall={o['coverage_recall']:.3f} exact_recall={o['exact_recall']:.3f}")
    for sl in sorted(report["by_slice"]):
        s = report["by_slice"][sl]
        lines.append(f"slice {sl:<10} recall={s['recall']:.3f} coverage={s['coverage_recall']:.3f}")
    return "\n".join(lines)


def run_strategy_comparison(source: str = "synthetic", seed: int = 42, size: int = 200) -> dict:
    """Score four NER strategies (crf, wcb, union, route) on one corpus.

    Runs each engine once over the corpus (resetting the process-global NER
    singleton, as run_benchmark does), composes union/route per sample, and
    scores all four with the shared scorer.
    """
    from pii_redactor.detectors import tb_detector
    from pii_redactor.detectors.aggregate import detect_all

    from .strategies import route_entities, union_entities

    samples = load_gold() if source == "gold" else build_corpus(seed=seed, size=size)

    def _run(engine_env: str):
        prev_ner = dict(tb_detector._ner_cache)
        prev_env = os.environ.get("AIGUARD_NER_ENGINE")
        os.environ["AIGUARD_NER_ENGINE"] = engine_env
        tb_detector._ner_cache = {}
        try:
            return [detect_all(s.text) for s in samples]
        finally:
            tb_detector._ner_cache = prev_ner
            if prev_env is None:
                os.environ.pop("AIGUARD_NER_ENGINE", None)
            else:
                os.environ["AIGUARD_NER_ENGINE"] = prev_env

    crf_ents = _run("thainer")
    wcb_ents = _run("wangchanberta")

    strat_ents = {
        "crf": crf_ents,
        "wcb": wcb_ents,
        "union": [union_entities(c, w) for c, w in zip(crf_ents, wcb_ents)],
        "route": [route_entities(c, w) for c, w in zip(crf_ents, wcb_ents)],
    }

    reports: dict[str, dict] = {}
    for name, ents_list in strat_ents.items():
        preds = [[(e.span[0], e.span[1], e.data_type) for e in ents] for ents in ents_list]
        rep = score(samples, preds)
        rep["strategy"] = name
        rep["source"] = source
        rep["seed"] = seed
        rep["size"] = size
        reports[name] = rep
    return reports


def render_strategy_table(reports: dict) -> str:
    order = ["crf", "wcb", "union", "route"]
    base = reports[order[0]]
    types = sorted(base["by_type"])
    lines = [
        f"strategy comparison source={base.get('source', 'synthetic')} "
        f"seed={base['seed']} size={base['size']}  (values = recall)",
        f"{'type':<16}" + "".join(f"{s + '_R':>10}" for s in order),
    ]
    for t in types:
        row = f"{t:<16}"
        for s in order:
            c = reports[s]["by_type"].get(t)
            row += f"{c['recall']:>10.3f}" if c else f"{'-':>10}"
        lines.append(row)
    lines.append(
        f"{'OVERALL_R':<16}" + "".join(f"{reports[s]['overall']['recall']:>10.3f}" for s in order)
    )
    lines.append(
        f"{'OVERALL_P':<16}"
        + "".join(f"{reports[s]['overall']['precision']:>10.3f}" for s in order)
    )
    lines.append(
        f"{'coverage':<16}"
        + "".join(f"{reports[s]['overall']['coverage_recall']:>10.3f}" for s in order)
    )
    return "\n".join(lines)
