"""Same-line NAME boundary hygiene (2026-08-04 boundary inventory B1/B2/B3/B4/B6).

Every catch below is a verbatim gold/inventory case (61 same-line rows across
B1 role prefixes, B2 trailing field labels and B3 both-sides spans, plus the
md03/lf11 role-cue qualifier leaks and the B4/LATENT-1 dedupe-order conflict),
grouped by mechanism: the CRF glues a leading role word (ผู้จัดการฝ่ายขาย,
ผู้ค้ำประกัน) or a trailing field label (เลขประจำตัวประชาชน, วันเกิด) onto the
person's name on label-dense form lines; the ผู้ป่วย/ผู้ติดต่อ cues take a glued
qualifier (หญิง/ชาย/กรณี) as a first name and the wrong span then evicts the
CRF's exact one; and `_deduplicate`'s start-first key contradicted the score
contract name_context documents. All values fabricated.

Trimming UNMASKS the trimmed text, so the controls pin the safety boundary the
findings demand: a token is trimmed only on an exact whole-token closed-lexicon
match (บัตรงาม/บุตรศรี tokenize onto a label word and survive because their
second token matches nothing), at least two name groups always remain, titles
stay in the span (B5 by design), and — the LATENT-1 counterexample, verified
constructible through the real CRF path — evicting a wide two-person span for a
narrow higher-score cue span must never unmask the second person.
"""

from __future__ import annotations

import pytest

import pii_redactor.detectors.tb_detector as tbd
from pii_redactor.detectors.name_context import detect_name_context
from pii_redactor.models import Entity


def _hygiene_texts(entity_text: str) -> list[str]:
    text = "หัว\n" + entity_text + "\nท้าย"
    start = len("หัว\n")
    spans = tbd._name_hygiene(text, start, start + len(entity_text))
    for s, e in spans:
        assert 0 <= s < e <= len(text)
    return [text[s:e] for s, e in spans]


def _ctx_names(text: str) -> set[str]:
    return {e.original_text for e in detect_name_context(text)}


def _tb_names(text: str) -> set[str]:
    return {e.original_text for e in tbd.detect_tb(text) if e.data_type == "NAME"}


# ── A. B1: leading role words are trimmed off a same-line NAME span ────────


@pytest.mark.parametrize(
    ("entity_text", "expected"),
    [
        # single-token ผู้-compounds newmm keeps whole
        ("ผู้จัดการฝ่ายขาย วิชัย ประสงค์ดี", "วิชัย ประสงค์ดี"),
        ("ผู้ค้ำประกัน ดารณี สินสมบัติ", "ดารณี สินสมบัติ"),
        ("ผู้เช่า ชลดา ภูมิพัฒน์", "ชลดา ภูมิพัฒน์"),
        # newmm splits ผู้รับเงิน into ผู้|รับเงิน — the bare nominalizer token
        # vouches for the rest of its own group (the lead-token idiom
        # is_non_person_segment already uses; no Thai given name begins ผู้)
        ("ผู้รับเงิน สมชาย ใจดี", "สมชาย ใจดี"),
        # glued role+first-name (ผู้ป่วย|รัตนา): only the compound lead TOKEN
        # is trimmed, so the name half of the glued group survives
        ("ผู้ป่วยรัตนา แสงวิเชียร", "รัตนา แสงวิเชียร"),
    ],
)
def test_leading_role_words_are_trimmed(entity_text, expected):
    assert _hygiene_texts(entity_text) == [expected], entity_text


# ── B. B2: the span is truncated at the first trailing field-label group ───


@pytest.mark.parametrize(
    ("entity_text", "expected"),
    [
        ("อรุณี วัฒนสิทธิ์ เลขประจำตัวประชาชน", "อรุณี วัฒนสิทธิ์"),
        ("สมหญิง รักดี วันเกิด", "สมหญิง รักดี"),
        ("ศักดิ์ชัย รุ่งอรุณ รหัสประจำตัว", "ศักดิ์ชัย รุ่งอรุณ"),
        ("รัตนา แสงวิเชียร อาชีพ พยาบาล", "รัตนา แสงวิเชียร"),
        # the label group ends the claim even over a compound surname (ณ สงขลา)
        ("กาญจนา ณ สงขลา ความสัมพันธ์ ภรรยา", "กาญจนา ณ สงขลา"),
    ],
)
def test_trailing_field_labels_are_truncated(entity_text, expected):
    assert _hygiene_texts(entity_text) == [expected], entity_text


# ── C. B3: both defects in one span, and the digit-run interplay ───────────


def test_role_prefix_and_trailing_label_trimmed_together():
    # lf08 shape: ผู้ให้เช่า splits ผู้|ให้เช่า, เลขประจำตัวประชาชน splits onto
    # two label tokens — head and tail evidence are judged independently.
    segs = _hygiene_texts("ผู้ให้เช่า บุญส่ง วรรณโภคิน เลขประจำตัวประชาชน")
    assert segs == ["บุญส่ง วรรณโภคิน"], segs


def test_digit_truncation_and_label_trim_compose():
    # The earlier wave's digit-run truncation cuts the id; the tail rule then
    # removes the label it exposed; the head rule removes the role word.
    segs = _hygiene_texts("ผู้ยื่นคำขอ อรุณี วัฒนสิทธิ์ เลขประจำตัวประชาชน 3589434161754")
    assert segs == ["อรุณี วัฒนสิทธิ์"], segs


def test_multiline_model_tail_uses_the_same_closed_role_trim():
    text = "**คำตอบ:**\n\nผู้สมัครสังเคราะห์ สมชาย ใจดี"
    start = text.index("คำตอบ")

    spans = tbd._name_hygiene(text, start, len(text))
    values = [text[lo:hi] for lo, hi in spans]

    assert values == ["สังเคราะห์ สมชาย ใจดี"]


def test_provider_markdown_label_is_not_a_person_name():
    text = "**คำตอบ:**\n\nข้อความสังเคราะห์ทั่วไป"

    assert "คำตอบ:**" not in _tb_names(text)


# ── D. safety controls: whole-token evidence, group floor, titles ──────────


def test_trim_needs_whole_token_lexicon_evidence():
    # บัตรงาม tokenizes onto the label word บัตร and บุตรศรี onto บุตร|ศรี —
    # a prefix/substring hit is not evidence, so the surnames survive. ทองอยู่
    # splits ONTO a stop word (ทอง|อยู่) and survives because only a group
    # made entirely of label tokens may be truncated.
    for entity_text in (
        "นาย สมชาย บัตรงาม",
        "นาย สมชาย บุตรศรี",
        "นาย วิชัย ประสงค์ดี",
        "กิตติ พรดี ชลธิชา ทองอยู่",
    ):
        assert _hygiene_texts(entity_text) == [entity_text], entity_text


def test_trim_never_leaves_less_than_two_name_groups():
    # role + a single name group: trimming would leave one group — kept whole
    # (over-masking a role word is the safe direction; unmasking is not).
    for entity_text in ("ผู้ค้ำประกัน ดารณี", "ผู้จัดการฝ่ายขาย วิชัย"):
        assert _hygiene_texts(entity_text) == [entity_text], entity_text


def test_title_spans_and_parenthesised_roles_survive():
    for entity_text in (
        "นาย ประกาศิต ชัยมงคล",  # titles stay in the span (B5, by design)
        "สมชาย ใจดี (ผู้ยื่น)",  # the tail group leads with punctuation
        "John Smith",
    ):
        assert _hygiene_texts(entity_text) == [entity_text], entity_text


# ── E. B6: glued qualifiers veto the role cue; the CRF exact span wins ─────


def test_patient_gender_qualifier_is_skipped_not_taken_as_a_name():
    # md03/lf17: ผู้ป่วยหญิง is a ward register word plus a gender qualifier,
    # not "a patient named หญิง". The first cut made หญิง/ชาย VETO the cue,
    # which silenced it outright — and where the CRF carries no PERSON span
    # the whole name then shipped unmasked (2026-08-04 review). The qualifier
    # is stepped over instead, so the cue still claims the person and the
    # boundary this case is about is still right.
    for text, expected in (
        ("ผู้ป่วยหญิง รัตนา แสงวิเชียร อายุ 52 ปี มาพบแพทย์ตามนัด", "รัตนา แสงวิเชียร"),
        ("ผู้ป่วยชาย สมบูรณ์ ทรงศิริ เข้ารับการตรวจตามนัด", "สมบูรณ์ ทรงศิริ"),
    ):
        names = _ctx_names(text)
        assert expected in names, (text, names)
        assert not any(n.startswith(("หญิง", "ชาย")) for n in names), (text, names)


def test_spaced_patient_cue_still_collects_the_name():
    # The veto is for GLUED qualifiers only — the labeled-person form keeps
    # detecting (recall control from the finding).
    assert "สมบูรณ์ ทรงศิริ" in _ctx_names("ผู้ป่วย สมบูรณ์ ทรงศิริ เลขประจำตัวผู้ป่วย 445102")


def test_md03_crf_exact_span_wins_after_the_veto():
    # md03 verbatim: the cue's "หญิง รัตนา" (0.88) used to evict the CRF's
    # exact "รัตนา แสงวิเชียร" (0.85) and the surname shipped unmasked.
    text = (
        "สรุปเวชระเบียนผู้ป่วยใน ผู้ป่วยหญิง รัตนา แสงวิเชียร อายุ 52 ปี "
        "เกิด 21 มกราคม 2517 เข้ารับการรักษาด้วยอาการเจ็บแน่นหน้าอก ญาติที่ติดต่อได้ 0855517204"
    )
    names = _tb_names(text)
    assert "รัตนา แสงวิเชียร" in names, names
    assert not any(n.startswith("หญิง") for n in names), names


def test_emergency_contact_case_compound_owns_the_name():
    # lf11: ผู้ติดต่อกรณีฉุกเฉิน is one fixed form phrase. กรณี vetoes the
    # short cue (no more "กรณีฉุกเฉิน กาญจนา"), and the compound cue itself
    # introduces the name so the row keeps a NAME claim (recall control).
    text = "ผู้ติดต่อกรณีฉุกเฉิน กาญจนา ณ สงขลา ความสัมพันธ์ ภรรยา โทรศัพท์ 0864433221"
    names = _ctx_names(text)
    assert not any(n.startswith("กรณี") for n in names), names
    assert any("กาญจนา" in n for n in names), names


def test_contact_cue_prose_continuations_still_yield_nothing():
    for text in (
        "ผู้ติดต่อหลัก ฝ่ายบัญชี อาคาร 2",
        "กรณีฉุกเฉินติดต่อญาติผู้ป่วยได้ที่ 086-559-2217",
    ):
        assert _ctx_names(text) == set(), (text, _ctx_names(text))


# ── F. B4: dedupe is score-first, but eviction never reduces coverage ──────


def _entity(start: int, end: int, score: float, data_type: str = "NAME") -> Entity:
    return Entity(
        entity_id=f"e{start}-{end}-{score}",
        redact_type="TB",
        data_type=data_type,
        span=(start, end),
        score=score,
        original_text="x" * (end - start),
    )


def test_dedupe_same_span_keeps_the_higher_score():
    kept = tbd._deduplicate([_entity(0, 10, 0.85), _entity(0, 10, 0.88)])
    assert [(e.span, e.score) for e in kept] == [((0, 10), 0.88)]


def test_dedupe_drops_a_nested_lower_score_span():
    kept = tbd._deduplicate([_entity(2, 10, 0.85), _entity(0, 20, 0.9)])
    assert [e.span for e in kept] == [(0, 20)]


def test_dedupe_eviction_never_reduces_coverage():
    # LATENT-1 class, unit form: a narrow high-score cue span over person 1
    # overlapping a wide lower-score CRF span covering persons 1+2. Plain
    # score-first eviction would unmask person 2 — the wide span is kept too.
    kept = tbd._deduplicate([_entity(0, 12, 0.88), _entity(0, 30, 0.85)])
    spans = [e.span for e in kept]
    assert (0, 12) in spans and (0, 30) in spans, spans


GUARANTOR_TWO_PERSON_TEXT = "สัญญากู้ยืมเงินระบุ ผู้ค้ำประกัน ไพโรจน์ สุขสมบูรณ์ เพ็ญศรี ทองอินทร์ ร่วมกันรับผิดชอบ"


def _name_covered(text: str, value: str, ents: list[Entity]) -> bool:
    lo = text.index(value)
    hi = lo + len(value)
    cur = lo
    for s, e in sorted(
        e.span for e in ents if e.data_type == "NAME" and e.span[0] < hi and e.span[1] > lo
    ):
        if s > cur:
            return False
        cur = max(cur, e)
    return cur >= hi


def test_second_person_in_a_wide_crf_span_stays_covered():
    # LATENT-1, real path (verified raw tags): the CRF emits ONE PERSON span
    # over both guarantors while the ผู้ค้ำประกัน cue emits only person 1 at
    # a higher score. Whatever wins dedupe, both people must stay masked.
    ents = tbd.detect_tb(GUARANTOR_TWO_PERSON_TEXT)
    for value in ("ไพโรจน์ สุขสมบูรณ์", "เพ็ญศรี ทองอินทร์"):
        assert _name_covered(GUARANTOR_TWO_PERSON_TEXT, value, ents), (value, ents)


def test_second_person_stays_covered_through_detect_all():
    from pii_redactor.detectors.aggregate import detect_all

    ents = detect_all(GUARANTOR_TWO_PERSON_TEXT)
    for value in ("ไพโรจน์ สุขสมบูรณ์", "เพ็ญศรี ทองอินทร์"):
        assert _name_covered(GUARANTOR_TWO_PERSON_TEXT, value, ents), (value, ents)


def test_single_person_role_span_ends_exactly_at_the_name():
    # B4-win rows (fn09/md02/...): with the head trim and score-first dedupe
    # the exact-boundary candidate is what detect_tb finally returns — the
    # role word is out of the span, the full name is in it.
    names = _tb_names("ผู้ค้ำประกัน ดารณี สินสมบัติ ลงนามต่อหน้าพยานครบถ้วน")
    assert "ดารณี สินสมบัติ" in names, names
    assert not any("ผู้ค้ำประกัน" in n for n in names), names
