"""OCR-tolerant name shapes (gov-form OCR gap, F3).

Two OCR artefacts defeat every name-recall booster in the pipeline, and both
were reproduced against real PaddleOCR output in the M6-P0 investigation:

a. The form's ``ชื่อ`` label lands on its OWN line, so the line-start label cue
   (``_LINE_NAME_LABEL_RE``) — whose delimiter class was ``[ \\t:：]+`` — vouched
   for nothing.  Reproduced ภ.ง.ด.91 degraded text::

       ...\\nชื่อ\\nพิมพ์ใจ แสนดี\\nชื่อ\\nกิตติ พรดี\\n...

b. OCR deletes the space INSIDE a Thai name (``สมชาย ใจดี`` → ``สมชายใจดี``),
   and every fallback shape required a space or two token groups.  A glued run
   is admitted narrowly: 4–25 Thai characters, no digits, at least two
   tokenizer tokens (a real Thai name is not one dictionary word — ``ความเห็น``,
   ``จดทะเบียนสมรส`` and ``ขอแสดงความนับถือ`` all are), and no form-noun,
   organisation-lead or document-compound token.

Every value here is synthetic.
"""

from __future__ import annotations

import uuid

import pii_redactor.detectors.tb_detector as tbd
from pii_redactor.detectors.name_context import (
    detect_name_context,
    detect_parallel_record_names,
)
from pii_redactor.models import Entity


def _names(text):
    return [e.original_text for e in detect_name_context(text) if e.data_type == "NAME"]


def _entity(data_type, text, start, end):
    return Entity(
        entity_id=str(uuid.uuid4()),
        redact_type="FP" if data_type == "THAI_ID" else "TB",
        data_type=data_type,
        span=(start, end),
        score=0.95,
        original_text=text[start:end],
    )


# ---------------------------------------------------------------------------
# a. newline as a delimiter for the bare ชื่อ / ชื่อ-นามสกุล line label
# ---------------------------------------------------------------------------

# Verbatim shape of the reproduced ภ.ง.ด.91 "degraded" OCR text: the label and
# its value are on separate physical lines (M6-P0 mechanism 3).
PND91_DEGRADED_LABEL_LINES = "วันเดือนปีเกิด\n\nชื่อ\nพิมพ์ใจ แสนดี\nชื่อ\nกิตติ พรดี\n"


def test_line_label_newline_delimiter_recovers_following_line_name():
    names = _names(PND91_DEGRADED_LABEL_LINES)
    assert any("พิมพ์ใจ" in n and "แสนดี" in n for n in names), names


def test_line_label_newline_delimiter_recovers_every_labelled_line():
    names = _names(PND91_DEGRADED_LABEL_LINES)
    assert any("กิตติ" in n and "พรดี" in n for n in names), names


def test_line_label_newline_spans_slice_back_to_the_source_text():
    text = PND91_DEGRADED_LABEL_LINES
    for e in detect_name_context(text):
        assert text[e.span[0] : e.span[1]] == e.original_text


def test_line_label_newline_does_not_fire_on_chue_banchi():
    # "ชื่อบัญชี" (account name) is not the word ชื่อ: the label must still end
    # at a delimiter, so a Thai letter right after it cancels the cue.
    assert _names("ชื่อบัญชี\nกรุงเทพ") == []


def test_line_label_newline_does_not_fire_on_other_chue_compounds():
    assert _names("ชื่อบริษัท\nรุ่งเรือง จำกัด") == []
    assert _names("ชื่อไฟล์\nreport.pdf") == []
    assert _names("รายชื่อ\nสมชาย ใจดี") == []


def test_line_label_newline_does_not_fire_on_a_following_label_line():
    # Reproduced ภ.ง.ด.91 "print_like" order puts two bare labels back to back;
    # ชื่อ is a _NOT_NAME token, so the second one vouches for nothing.
    assert _names("กิตติ พรดี\nพิมพ์ใจ แสนดี\nชื่อ\nชื่อ\n(ให้ระบุ)") == []


def test_line_label_inline_delimiter_still_works():
    # Regression: the pre-existing inline form of the same cue is untouched.
    assert any("พิมพ์ใจ" in n for n in _names("ชื่อ พิมพ์ใจ แสนดี"))
    assert any("พิมพ์ใจ" in n for n in _names("ชื่อ-นามสกุล: พิมพ์ใจ แสนดี"))


# ---------------------------------------------------------------------------
# b-i. glued Thai run after a direct cue (ข้าพเจ้า / ผู้เสียหาย)
# ---------------------------------------------------------------------------


def test_glued_name_after_direct_cue_is_detected():
    # Reproduced คร.1 OCR text: "ข้าพเจ้า สมชาย ใจดี" lost BOTH spaces.
    assert _names("ข้าพเจ้าสมชายใจดี") == ["สมชายใจดี"]


def test_glued_name_after_direct_cue_in_context():
    text = "คำร้องที่ 5\nข้าพเจ้าสมชายใจดี\nเลขประจำตัวประชาชน\n1312271505581\n"
    names = _names(text)
    assert "สมชายใจดี" in names, names
    for e in detect_name_context(text):
        assert text[e.span[0] : e.span[1]] == e.original_text


def test_glued_name_after_other_direct_cue():
    assert _names("ผู้เสียหายมาลีรักดี") == ["มาลีรักดี"]


def test_glued_run_veto_still_blocks_the_letter_closing():
    # The exact false positive the space veto was added for: the standard
    # closing of a Thai official letter is ONE dictionary token.
    assert _names("ข้าพเจ้าขอแสดงความนับถือ") == []


def test_glued_run_veto_still_blocks_document_label_prose():
    assert _names("ข้าพเจ้ามีเลขบัตรประชาชน 1101700230708") == []
    assert _names("ข้าพเจ้ายินยอมให้ดำเนินการ") == []
    assert _names("ข้าพเจ้าขอยื่นคำร้องเพื่อจดทะเบียนสมรส") == []


def test_glued_run_veto_blocks_organisation_and_form_compounds():
    assert _names("ข้าพเจ้าสำนักงานเขต") == []
    assert _names("ข้าพเจ้าโรงพยาบาลกรุงเทพ") == []
    assert _names("ข้าพเจ้าวันเดือนปีเกิด") == []


def test_glued_run_stop_set_does_not_eat_names_sharing_a_form_noun_prefix():
    # tb_detector's compound rule is documented to preserve the real given
    # names เลขา / ใบเฟิร์น / ประกาศิต / นิคม; the token stop set here must not
    # take them back (newmm splits ใบเฟิร์นสวยงาม as ใบ|เฟิร์น|สวยงาม).
    assert _names("ข้าพเจ้าใบเฟิร์นสวยงาม") == ["ใบเฟิร์นสวยงาม"]
    assert _names("ข้าพเจ้าเลขาสุขใจ") == ["เลขาสุขใจ"]
    assert _names("ข้าพเจ้านิคมแก้วมณี") == ["นิคมแก้วมณี"]


def test_spaced_name_after_direct_cue_still_detected():
    # Regression: the ordinary (spaced) shape this pass has always handled.
    assert any("วิชัย" in n and "ประสงค์ดี" in n for n in _names("ข้าพเจ้า วิชัย ประสงค์ดี"))


def test_existing_token_pass_negatives_unchanged():
    # The "นายก"/"คุณภาพ" trap family must stay silent.
    assert _names("นายกรัฐมนตรีแถลงข่าววันนี้") == []
    assert _names("คุณภาพของงานดีมาก") == []
    assert _names("ชื่อไฟล์ report.pdf") == []


# ---------------------------------------------------------------------------
# b-ii. glued run admitted by the isolated-line CRF retry shape gate
# ---------------------------------------------------------------------------


class LineOnlyNER:
    """Silent on a multi-line chunk, tags a single target line as PERSON.

    Mirrors the reproduced CRF behaviour (a name the model recognises alone is
    lost in a noisy multi-field form context) without the degenerate-span
    shape, so only the isolated-line retry can recover the name here.
    """

    def __init__(self, target_line):
        self.target_line = target_line
        self.calls = []

    def tag(self, chunk):
        self.calls.append(chunk)
        if chunk == self.target_line:
            return [(chunk, "B-PERSON")]
        return [(chunk, "O")]


def _with_engine(monkeypatch, engine):
    monkeypatch.setitem(tbd._ner_cache, "thainer", engine)
    monkeypatch.setenv("AIGUARD_NER_ENGINE", "thainer")


def test_isolated_line_retry_admits_a_glued_name_line(monkeypatch):
    ner = LineOnlyNER(target_line="สมชายใจดี")
    _with_engine(monkeypatch, ner)
    text = "คำร้องขอจดทะเบียน\nสมชายใจดี\nเอกสาร แนบ"

    names = [e for e in tbd.detect_tb(text) if e.data_type == "NAME"]

    start = text.index("สมชายใจดี")
    assert [(e.original_text, e.span) for e in names] == [
        ("สมชายใจดี", (start, start + len("สมชายใจดี")))
    ]
    assert "สมชายใจดี" in ner.calls[1:]


def test_isolated_line_retry_shape_gate_rejects_single_dictionary_words(monkeypatch):
    # Form nouns/verbs that are ONE dictionary token must never reach the
    # engine as retry candidates — they would spend the 8-line budget and
    # invite a hallucinated PERSON on a header.
    ner = LineOnlyNER(target_line="__never__")
    _with_engine(monkeypatch, ner)
    text = "จดทะเบียนสมรส\nความเห็น\nนายทะเบียน\nสำนักงานเขต\nหมายเหตุ"

    tbd.detect_tb(text)

    assert ner.calls[1:] == [], ner.calls


def test_isolated_line_retry_still_admits_the_spaced_shape(monkeypatch):
    # Regression: the pre-existing two-word shape keeps its retry.
    ner = LineOnlyNER(target_line="กิตติ พรดี")
    _with_engine(monkeypatch, ner)
    text = "หัวข้อ แบบฟอร์ม\nกิตติ พรดี\nท้าย เอกสาร"

    names = [e for e in tbd.detect_tb(text) if e.data_type == "NAME"]

    assert [e.original_text for e in names] == ["กิตติ พรดี"]


# ---------------------------------------------------------------------------
# b-iii. single co-applicant match when the document carries >=2 THAI_IDs
# ---------------------------------------------------------------------------

# Reproduced คร.1 shape: OCR turns the co-applicant's leading marker into
# "และ..." and the name loses its internal space. The document carries exactly
# ONE such line, so the pre-existing "repeated" requirement rejected it.
KHOR_ROR_1_CO_APPLICANT = (
    "ข้าพเจ้าสมชายใจดี\nเลขประจำตัวประชาชน\n1312271505581\n"
    "และ...มาลีรักดี\nเลขประจำตัวประชาชน\n4951607747108\n"
)


def _khor_ror_1_seed_entities():
    text = KHOR_ROR_1_CO_APPLICANT
    name_start = text.index("สมชายใจดี")
    id1 = text.index("1312271505581")
    id2 = text.index("4951607747108")
    return [
        _entity("NAME", text, name_start, name_start + len("สมชายใจดี")),
        _entity("THAI_ID", text, id1, id1 + 13),
        _entity("THAI_ID", text, id2, id2 + 13),
    ]


def test_single_co_applicant_match_recovered_with_two_thai_ids():
    text = KHOR_ROR_1_CO_APPLICANT
    recovered = detect_parallel_record_names(text, _khor_ror_1_seed_entities())

    assert [e.original_text for e in recovered] == ["มาลีรักดี"]
    for e in recovered:
        assert text[e.span[0] : e.span[1]] == e.original_text


def test_single_co_applicant_match_needs_two_thai_ids():
    text = KHOR_ROR_1_CO_APPLICANT
    entities = [e for e in _khor_ror_1_seed_entities() if e.data_type != "THAI_ID"]
    id1 = text.index("1312271505581")
    entities.append(_entity("THAI_ID", text, id1, id1 + 13))

    assert detect_parallel_record_names(text, entities) == []


def test_single_co_applicant_match_needs_a_name_seed():
    text = KHOR_ROR_1_CO_APPLICANT
    entities = [e for e in _khor_ror_1_seed_entities() if e.data_type != "NAME"]

    assert detect_parallel_record_names(text, entities) == []


def test_single_co_applicant_stop_prefix_still_rejected():
    text = (
        "ข้าพเจ้าสมชายใจดี\nเลขประจำตัวประชาชน\n1312271505581\n"
        "และ...เอกสารแนบ\nเลขประจำตัวประชาชน\n4951607747108\n"
    )
    name_start = text.index("สมชายใจดี")
    id1 = text.index("1312271505581")
    id2 = text.index("4951607747108")
    entities = [
        _entity("NAME", text, name_start, name_start + len("สมชายใจดี")),
        _entity("THAI_ID", text, id1, id1 + 13),
        _entity("THAI_ID", text, id2, id2 + 13),
    ]

    assert detect_parallel_record_names(text, entities) == []
