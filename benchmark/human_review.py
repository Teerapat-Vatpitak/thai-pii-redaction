"""Prepare and score a blind second-human annotation sample."""

from __future__ import annotations

import hashlib
import json
import random
import re
import subprocess
from collections import defaultdict
from pathlib import Path

from .gold import parse_gold
from .types import SHARED_ENTITY_TYPE_SET, SHARED_ENTITY_TYPES, GoldSpan, Sample

PACKET_SCHEMA = 2
STT52_GOLD_COMMIT = "d93d10b17be6783d5c684cb47f25d4156ed6fb4b"
STT52_GOLD_VERSION = "gold-v3"
STT52_GOLD_PATH = "benchmark/data/gold.jsonl"
STT52_REVIEW_SAMPLE_ID = "stt52-second-human-v1"
STT52_REVIEW_PER_SLICE = 4
STT52_REVIEW_SEED = 5252
STT52_GUIDELINE_PATH = "docs/research/stt52-human-review-guidelines.md"


class HumanReviewError(ValueError):
    pass


def _parse_gold_jsonl(raw: bytes) -> list[Sample]:
    try:
        records = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise HumanReviewError("cannot read the gold JSONL") from exc

    samples: list[Sample] = []
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
            raise HumanReviewError("gold JSONL has an invalid record") from exc
    if not samples:
        raise HumanReviewError("gold JSONL has no documents")
    return samples


def load_gold_at_commit(
    repo: Path,
    revision: str = STT52_GOLD_COMMIT,
) -> tuple[list[Sample], dict]:
    """Load the frozen paper corpus without changing the worktree."""
    try:
        resolved = (
            subprocess.run(
                ["git", "rev-parse", "--verify", f"{revision}^{{commit}}"],
                cwd=repo,
                capture_output=True,
                check=True,
            )
            .stdout.decode("ascii")
            .strip()
        )
        raw = subprocess.run(
            ["git", "show", f"{resolved}:{STT52_GOLD_PATH}"],
            cwd=repo,
            capture_output=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError, UnicodeError) as exc:
        raise HumanReviewError("cannot load the frozen gold commit") from exc

    samples = _parse_gold_jsonl(raw)
    return samples, {
        "gold_version": STT52_GOLD_VERSION,
        "commit": resolved,
        "path": STT52_GOLD_PATH,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "documents": len(samples),
        "entities": sum(len(sample.spans) for sample in samples),
    }


def _select_review_samples(
    samples: list[Sample],
    *,
    per_slice: int,
    seed: int,
) -> tuple[list[Sample], int]:
    """Select each stratum, then mix the review order."""
    if per_slice < 1:
        raise HumanReviewError("per_slice must be positive")
    by_slice: dict[str, list[Sample]] = defaultdict(list)
    for sample in samples:
        by_slice[sample.slice].append(sample)

    rng = random.Random(seed)
    selected: list[Sample] = []
    for slice_name in sorted(by_slice):
        choices = sorted(by_slice[slice_name], key=lambda sample: sample.template_id)
        if len(choices) < per_slice:
            raise HumanReviewError(f"slice has fewer than {per_slice} documents")
        selected.extend(rng.sample(choices, per_slice))
    rng.shuffle(selected)
    return selected, len(by_slice)


def build_review_packet(
    samples: list[Sample],
    *,
    per_slice: int = STT52_REVIEW_PER_SLICE,
    seed: int = STT52_REVIEW_SEED,
    sample_id: str = "human-review-sample",
    reference: dict | None = None,
    guideline: dict | None = None,
) -> dict:
    selected, strata_count = _select_review_samples(
        samples,
        per_slice=per_slice,
        seed=seed,
    )

    return {
        "schema": PACKET_SCHEMA,
        "sample_id": sample_id,
        "seed": seed,
        "per_slice": per_slice,
        "sample_size": len(selected),
        "strata_count": strata_count,
        "sampling": "equal-count stratified sample; strata hidden from reviewer",
        "reference": reference,
        "guideline": guideline,
        "reviewer": {
            "code": "",
            "is_independent_human": False,
            "did_not_see_gold": False,
            "read_guideline": False,
        },
        "instructions": (
            "Read the named guideline. Add [[TYPE|value]] marks without changing "
            "the text. Set reviewed to true for every document."
        ),
        "documents": [
            {
                "item_id": f"R{index:03d}",
                "annotated": sample.text,
                "reviewed": False,
            }
            for index, sample in enumerate(selected, 1)
        ],
    }


def _prf(tp: int, reference_only: int, reviewer_only: int) -> dict:
    precision = tp / (tp + reviewer_only) if tp + reviewer_only else 1.0
    recall = tp / (tp + reference_only) if tp + reference_only else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "matches": tp,
        "reference_only": reference_only,
        "reviewer_only": reviewer_only,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def _exact_counts(reference: list[GoldSpan], reviewer: list[GoldSpan]) -> tuple[int, int, int]:
    left = {(span.start, span.end, span.entity_type) for span in reference}
    right = {(span.start, span.end, span.entity_type) for span in reviewer}
    return len(left & right), len(left - right), len(right - left)


def _maximum_overlap_matches(reference: list[GoldSpan], reviewer: list[GoldSpan]) -> int:
    edges: list[list[int]] = []
    for left in reference:
        edges.append(
            [
                index
                for index, right in enumerate(reviewer)
                if left.entity_type == right.entity_type
                and left.start < right.end
                and right.start < left.end
            ]
        )

    matched_right: dict[int, int] = {}

    def claim(left_index: int, seen: set[int]) -> bool:
        for right_index in edges[left_index]:
            if right_index in seen:
                continue
            seen.add(right_index)
            owner = matched_right.get(right_index)
            if owner is None or claim(owner, seen):
                matched_right[right_index] = left_index
                return True
        return False

    return sum(claim(index, set()) for index in range(len(reference)))


def _character_labels(spans: list[GoldSpan]) -> set[tuple[int, str]]:
    return {
        (position, span.entity_type) for span in spans for position in range(span.start, span.end)
    }


def _add_counts(total: list[int], counts: tuple[int, int, int]) -> None:
    for index, value in enumerate(counts):
        total[index] += value


def _reviewed_samples(packet: dict, reference: list[Sample]) -> list[Sample]:
    if packet.get("schema") != PACKET_SCHEMA:
        raise HumanReviewError("unsupported review packet schema")
    documents = packet.get("documents")
    if not isinstance(documents, list) or not documents:
        raise HumanReviewError("review packet has no documents")
    reviewer = packet.get("reviewer")
    if not isinstance(reviewer, dict):
        raise HumanReviewError("reviewer attestation is missing")
    reviewer_code = reviewer.get("code")
    if not isinstance(reviewer_code, str) or not re.fullmatch(r"R[0-9A-F]{2,12}", reviewer_code):
        raise HumanReviewError("reviewer attestation is incomplete")
    for field in ("is_independent_human", "did_not_see_gold", "read_guideline"):
        if reviewer.get(field) is not True:
            raise HumanReviewError("reviewer attestation is incomplete")

    seed = packet.get("seed")
    per_slice = packet.get("per_slice")
    if not isinstance(seed, int) or not isinstance(per_slice, int):
        raise HumanReviewError("review packet sampling metadata is invalid")
    if packet.get("sample_id") == STT52_REVIEW_SAMPLE_ID and (
        seed != STT52_REVIEW_SEED or per_slice != STT52_REVIEW_PER_SLICE
    ):
        raise HumanReviewError("STT52 review sample settings changed")

    selected, strata_count = _select_review_samples(
        reference,
        per_slice=per_slice,
        seed=seed,
    )
    if packet.get("sample_size") != len(selected) or packet.get("strata_count") != strata_count:
        raise HumanReviewError("review packet sample metadata changed")
    expected = {f"R{index:03d}": sample for index, sample in enumerate(selected, 1)}
    if len(documents) != len(expected):
        raise HumanReviewError("review packet document set changed")

    reviewed: list[Sample] = []
    seen: set[str] = set()
    for record in documents:
        if not isinstance(record, dict):
            raise HumanReviewError("review packet has an invalid document")
        item_id = record.get("item_id")
        if not isinstance(item_id, str) or item_id in seen or item_id not in expected:
            raise HumanReviewError("review packet has an invalid item id")
        seen.add(item_id)
        if record.get("reviewed") is not True:
            raise HumanReviewError("review packet is not complete")
        annotated = record.get("annotated")
        if not isinstance(annotated, str):
            raise HumanReviewError("reviewed document has no annotation text")
        first = expected[item_id]
        parsed = parse_gold(first.template_id, first.slice, annotated)
        if parsed.text != first.text:
            raise HumanReviewError(f"reviewed document text changed: {item_id}")
        if any(span.entity_type not in SHARED_ENTITY_TYPE_SET for span in parsed.spans):
            raise HumanReviewError(f"unknown entity type in reviewed document: {item_id}")
        reviewed.append(parsed)
    if seen != set(expected):
        raise HumanReviewError("review packet document set changed")
    return reviewed


def score_review_packet(
    packet: dict,
    reference: list[Sample],
    *,
    reference_provenance: dict | None = None,
    guideline_sha256: str | None = None,
) -> dict:
    if reference_provenance is not None and packet.get("reference") != reference_provenance:
        raise HumanReviewError("review packet uses a different gold snapshot")
    packet_guideline = packet.get("guideline")
    if guideline_sha256 is not None and (
        not isinstance(packet_guideline, dict) or packet_guideline.get("sha256") != guideline_sha256
    ):
        raise HumanReviewError("review packet uses a different guideline")

    reviewed = _reviewed_samples(packet, reference)
    reference_by_id = {sample.template_id: sample for sample in reference}
    exact_total = [0, 0, 0]
    overlap_total = [0, 0, 0]
    character_total = [0, 0, 0]
    by_type: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    negative_total = negative_both_empty = 0

    for second in reviewed:
        first = reference_by_id[second.template_id]
        _add_counts(exact_total, _exact_counts(first.spans, second.spans))
        matches = _maximum_overlap_matches(first.spans, second.spans)
        _add_counts(
            overlap_total,
            (matches, len(first.spans) - matches, len(second.spans) - matches),
        )
        first_chars = _character_labels(first.spans)
        second_chars = _character_labels(second.spans)
        _add_counts(
            character_total,
            (
                len(first_chars & second_chars),
                len(first_chars - second_chars),
                len(second_chars - first_chars),
            ),
        )
        for entity_type in SHARED_ENTITY_TYPES:
            first_type = [span for span in first.spans if span.entity_type == entity_type]
            second_type = [span for span in second.spans if span.entity_type == entity_type]
            _add_counts(by_type[entity_type], _exact_counts(first_type, second_type))
        if first.slice == "negative":
            negative_total += 1
            negative_both_empty += not first.spans and not second.spans

    return {
        "schema": 1,
        "sample_id": packet.get("sample_id"),
        "sampling": packet.get("sampling"),
        "reference": packet.get("reference"),
        "guideline": packet.get("guideline"),
        "reviewer_code_sha256": hashlib.sha256(
            packet["reviewer"]["code"].encode("ascii")
        ).hexdigest(),
        "documents": len(reviewed),
        "documents_by_slice": dict(
            sorted(
                (slice_name, sum(sample.slice == slice_name for sample in reviewed))
                for slice_name in {sample.slice for sample in reviewed}
            )
        ),
        "reference_entities": sum(len(reference_by_id[s.template_id].spans) for s in reviewed),
        "reviewer_entities": sum(len(sample.spans) for sample in reviewed),
        "agreement": {
            "exact_span": _prf(*exact_total),
            "overlap_span": _prf(*overlap_total),
            "character_label": _prf(*character_total),
        },
        "by_type_exact_span": {
            entity_type: _prf(*counts)
            for entity_type, counts in sorted(by_type.items())
            if any(counts)
        },
        "negative_documents": {
            "total": negative_total,
            "both_empty": negative_both_empty,
        },
    }
