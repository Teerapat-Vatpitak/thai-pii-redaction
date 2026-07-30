from __future__ import annotations

import subprocess
from copy import deepcopy
from pathlib import Path

import pytest

from benchmark.human_review import (
    STT52_REVIEW_SAMPLE_ID,
    HumanReviewError,
    build_review_packet,
    load_gold_at_commit,
    score_review_packet,
)
from benchmark.types import GoldSpan, Sample


def _samples():
    return [
        Sample(
            text="นายกิตติ ติดต่อ test@example.com",
            spans=[GoldSpan(0, 8, "NAME"), GoldSpan(16, 32, "EMAIL")],
            template_id="a1",
            slice="alpha",
        ),
        Sample(
            text="เอกสารอ้างอิง 123",
            spans=[],
            template_id="a2",
            slice="alpha",
        ),
        Sample(
            text="โทร 0812345678",
            spans=[GoldSpan(4, 14, "PHONE")],
            template_id="b1",
            slice="beta",
        ),
        Sample(
            text="ไม่มีข้อมูล",
            spans=[],
            template_id="b2",
            slice="beta",
        ),
    ]


def _attest(packet):
    packet["reviewer"] = {
        "code": "R02",
        "is_independent_human": True,
        "did_not_see_gold": True,
        "read_guideline": True,
    }


def test_packet_is_stratified_and_hides_reference_labels():
    packet = build_review_packet(_samples(), per_slice=1, seed=7)

    assert [doc["item_id"] for doc in packet["documents"]] == ["R001", "R002"]
    assert all("doc_id" not in doc and "slice" not in doc for doc in packet["documents"])
    assert all(doc["reviewed"] is False for doc in packet["documents"])
    assert all("[[" not in doc["annotated"] for doc in packet["documents"])


def test_packet_selection_is_deterministic():
    first = build_review_packet(_samples(), per_slice=1, seed=17)
    second = build_review_packet(_samples(), per_slice=1, seed=17)

    assert first == second


def test_exact_overlap_and_character_agreement_can_be_perfect():
    reference = [_samples()[0]]
    packet = build_review_packet(reference, per_slice=1, seed=1)
    packet["documents"][0]["annotated"] = "[[NAME|นายกิตติ]] ติดต่อ [[EMAIL|test@example.com]]"
    packet["documents"][0]["reviewed"] = True
    _attest(packet)

    report = score_review_packet(packet, reference)

    for metric in ("exact_span", "overlap_span", "character_label"):
        assert report["agreement"][metric]["f1"] == 1.0
    assert report["reference_entities"] == 2
    assert report["reviewer_entities"] == 2


def test_boundary_disagreement_is_visible_in_three_views():
    reference = [
        Sample(
            text="นายสมชาย ใจดี",
            spans=[GoldSpan(0, 13, "NAME")],
            template_id="n1",
            slice="name",
        )
    ]
    packet = build_review_packet(reference, per_slice=1, seed=1)
    packet["documents"][0]["annotated"] = "นาย[[NAME|สมชาย]] ใจดี"
    packet["documents"][0]["reviewed"] = True
    _attest(packet)

    report = score_review_packet(packet, reference)

    assert report["agreement"]["exact_span"]["f1"] == 0.0
    assert report["agreement"]["overlap_span"]["f1"] == 1.0
    assert 0.0 < report["agreement"]["character_label"]["f1"] < 1.0


def test_incomplete_packet_is_rejected():
    packet = build_review_packet(_samples(), per_slice=1, seed=7)
    _attest(packet)

    with pytest.raises(HumanReviewError, match="not complete"):
        score_review_packet(packet, _samples())


def test_removed_document_is_rejected():
    packet = build_review_packet(_samples(), per_slice=1, seed=7)
    packet["documents"] = packet["documents"][:1]
    packet["documents"][0]["reviewed"] = True
    _attest(packet)

    with pytest.raises(HumanReviewError, match="document set changed"):
        score_review_packet(packet, _samples())


def test_stt52_sample_settings_are_fixed():
    packet = build_review_packet(
        _samples(),
        per_slice=1,
        seed=7,
        sample_id=STT52_REVIEW_SAMPLE_ID,
    )
    for document in packet["documents"]:
        document["reviewed"] = True
    _attest(packet)

    with pytest.raises(HumanReviewError, match="settings changed"):
        score_review_packet(packet, _samples())


def test_changed_plain_text_is_rejected_without_echoing_it():
    reference = [_samples()[0]]
    packet = build_review_packet(reference, per_slice=1, seed=1)
    packet["documents"][0]["annotated"] = "secret changed text"
    packet["documents"][0]["reviewed"] = True
    _attest(packet)

    with pytest.raises(HumanReviewError) as error:
        score_review_packet(packet, reference)

    assert "secret changed text" not in str(error.value)


def test_unknown_type_is_rejected_without_echoing_text():
    reference = [_samples()[0]]
    packet = build_review_packet(reference, per_slice=1, seed=1)
    packet["documents"][0]["annotated"] = "[[SECRET_KIND|นายกิตติ]] ติดต่อ test@example.com"
    packet["documents"][0]["reviewed"] = True
    _attest(packet)

    with pytest.raises(HumanReviewError, match="unknown entity type") as error:
        score_review_packet(packet, reference)

    assert "นายกิตติ" not in str(error.value)


def test_report_contains_no_document_text_or_values():
    reference = [_samples()[0]]
    packet = build_review_packet(reference, per_slice=1, seed=1)
    packet["documents"][0]["annotated"] = "[[NAME|นายกิตติ]] ติดต่อ [[EMAIL|test@example.com]]"
    packet["documents"][0]["reviewed"] = True
    _attest(packet)

    report = score_review_packet(deepcopy(packet), reference)

    rendered = str(report)
    assert "นายกิตติ" not in rendered
    assert "test@example.com" not in rendered
    assert "annotated" not in rendered
    assert "R02" not in rendered
    assert len(report["reviewer_code_sha256"]) == 64


def test_reviewer_must_attest_before_scoring():
    packet = build_review_packet([_samples()[0]], per_slice=1, seed=1)
    packet["documents"][0]["reviewed"] = True

    with pytest.raises(HumanReviewError, match="attestation"):
        score_review_packet(packet, [_samples()[0]])


def test_reviewer_code_must_be_opaque():
    packet = build_review_packet([_samples()[0]], per_slice=1, seed=1)
    packet["documents"][0]["reviewed"] = True
    packet["reviewer"] = {
        "code": "reviewer@example.com",
        "is_independent_human": True,
        "did_not_see_gold": True,
        "read_guideline": True,
    }

    with pytest.raises(HumanReviewError, match="attestation"):
        score_review_packet(packet, [_samples()[0]])


def test_reference_provenance_must_match():
    reference = [_samples()[0]]
    packet = build_review_packet(
        reference,
        per_slice=1,
        seed=1,
        reference={"commit": "a"},
    )
    packet["documents"][0]["reviewed"] = True
    _attest(packet)

    with pytest.raises(HumanReviewError, match="different gold snapshot"):
        score_review_packet(
            packet,
            reference,
            reference_provenance={"commit": "b"},
        )


def test_frozen_paper_gold_can_be_loaded_from_git():
    repo = Path(__file__).resolve().parents[1]
    shallow = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--is-shallow-repository"],
        capture_output=True,
        text=True,
    )
    if shallow.stdout.strip() == "true":
        # CI checks out depth 1, which cannot reach the frozen commit. A FULL
        # clone that cannot resolve it must still fail below: that is a
        # rewritten history, not a shallow one.
        pytest.skip("shallow clone carries no history to load the frozen gold from")

    samples, provenance = load_gold_at_commit(repo)

    assert len(samples) == 252
    assert sum(len(sample.spans) for sample in samples) == 641
    assert provenance["gold_version"] == "gold-v3"
    assert len(provenance["sha256"]) == 64
