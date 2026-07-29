"""Build aggregate evidence for the frozen STT52 study."""

from __future__ import annotations

from .scorer import score

PAPER_TITLE = "Negative Controls and Complementary Span Metrics for Thai PII Redaction"


class EvidenceIntegrityError(RuntimeError):
    pass


def prediction_records(samples, predictions) -> list[dict]:
    if len(samples) != len(predictions):
        raise EvidenceIntegrityError("prediction documents do not balance")
    return [
        {
            "doc_id": sample.template_id,
            "spans": [[start, end, entity_type] for start, end, entity_type in document],
        }
        for sample, document in zip(samples, predictions)
    ]


def build_external_evidence(
    report: dict,
    *,
    reference: dict,
    cache_fill: dict[str, int],
) -> dict:
    corpus = report.get("corpus", {})
    if (
        report.get("source") != "gold"
        or report.get("gold_version") != reference.get("gold_version")
        or corpus.get("samples") != reference.get("documents")
        or corpus.get("entities") != reference.get("entities")
    ):
        raise EvidenceIntegrityError("external baseline uses a different corpus")
    ci = report.get("confidence_intervals", {}).get("overall_f2", {})
    if ci.get("unit") != "document":
        raise EvidenceIntegrityError("external baseline has no document-level CI")
    run = report.get("run", {})
    if (
        not report.get("cache_only")
        or run.get("cached") != corpus["samples"]
        or run.get("called") != 0
        or run.get("failed") != 0
    ):
        raise EvidenceIntegrityError("external baseline final score is not a cache-only rescore")
    if (
        sum(cache_fill.get(key, 0) for key in ("cached", "called", "failed")) != corpus["samples"]
        or cache_fill.get("failed") != 0
    ):
        raise EvidenceIntegrityError("external baseline cache-fill counts do not balance")
    provider_config = report.get("provider_config")
    prompt_sha256 = report.get("prompt_sha256")
    if (
        not isinstance(provider_config, dict)
        or provider_config.get("provider_spec") != report.get("provider")
        or not isinstance(provider_config.get("model"), str)
        or not isinstance(prompt_sha256, str)
        or len(prompt_sha256) != 64
        or report.get("cache_schema") != 2
    ):
        raise EvidenceIntegrityError("external baseline provenance is incomplete")

    score_keys = (
        "corpus",
        "overall",
        "by_type",
        "by_slice",
        "confidence_intervals",
        "shared_11",
        "out_of_scheme_predictions",
        "type_scheme",
    )
    return {
        "schema": 2,
        "paper_title": PAPER_TITLE,
        "corpus": reference,
        "baseline": {
            "provider": report["provider"],
            "model": provider_config["model"],
            "request": provider_config,
            "prompt_sha256": prompt_sha256,
            "cache_schema": report["cache_schema"],
        },
        "score": {key: report[key] for key in score_keys},
        "cache_fill": cache_fill,
        "final_rescore": {
            "cache_only": True,
            "run": report["run"],
        },
    }


def _overlaps(left: tuple[int, int], right: tuple[int, int]) -> bool:
    return left[0] < right[1] and right[0] < left[1]


def audit_unmatched_address(samples, predictions) -> dict[str, int]:
    unmatched = inside = outside = 0
    for sample, document in zip(samples, predictions):
        gold = [(span.start, span.end) for span in sample.spans if span.entity_type == "ADDRESS"]
        predicted = [
            (start, end) for start, end, entity_type in document if entity_type == "ADDRESS"
        ]
        used: set[int] = set()
        for gold_span in gold:
            for index, predicted_span in enumerate(predicted):
                if index not in used and _overlaps(gold_span, predicted_span):
                    used.add(index)
                    break
        for index, predicted_span in enumerate(predicted):
            if index in used:
                continue
            unmatched += 1
            if any(
                gold_start <= predicted_span[0] and predicted_span[1] <= gold_end
                for gold_start, gold_end in gold
            ):
                inside += 1
            else:
                outside += 1
    return {
        "unmatched_predictions": unmatched,
        "inside_gold_address": inside,
        "outside_gold_address": outside,
    }


def build_system_evidence(
    samples,
    predictions,
    *,
    reference: dict,
    system_commit: str,
    ner_chunks: dict[str, int],
    bootstrap_iterations: int = 10_000,
    bootstrap_seed: int = 5252,
) -> dict:
    if ner_chunks.get("skipped") != 0:
        raise EvidenceIntegrityError("one or more NER chunks were skipped")
    if ner_chunks.get("attempted") != ner_chunks.get("succeeded"):
        raise EvidenceIntegrityError("NER chunk counts do not balance")

    result = score(
        samples,
        predictions,
        bootstrap_iters=bootstrap_iterations,
        bootstrap_seed=bootstrap_seed,
    )
    return {
        "schema": 1,
        "paper_title": PAPER_TITLE,
        "corpus": reference,
        "system": {
            "commit": system_commit,
            "engine": "thainer-crf",
        },
        "score": result,
        "ner_chunks": ner_chunks,
        "integrity": {
            "ok": True,
            "no_ner_chunks_skipped": True,
        },
        "address_posthoc": audit_unmatched_address(samples, predictions),
    }
