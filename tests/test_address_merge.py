"""ADDRESS span merging and the negative-slice junk guards.

Gold v4 measured ADDRESS entity precision at 0.220 — but 175 of the 183
unmatched ADDRESS predictions were fragments INSIDE real gold addresses (the
FP patterns emit house-no/moo/soi/admin-area as separate spans), and only 8
were hallucinations. The fix is therefore span coalescing, not pattern
removal. The anti-merge cases came out of an adversarial review: two
parties' addresses on one line, clause changes, and flattened tables must NOT
merge, because a merged span becomes one pseudonym and — on the PDF path —
every word of it becomes a document-wide redaction fragment.
"""

from __future__ import annotations

from pii_redactor.detectors.aggregate import detect_all, merge_address_spans
from pii_redactor.detectors.fp_detector import detect_fp


def _spans_of(ents, dtype):
    return [(e.span, e.original_text) for e in ents if e.data_type == dtype]


def _addr_texts(text):
    return [t for _, t in _spans_of(detect_all(text), "ADDRESS")]


# ── merging ────────────────────────────────────────────────────────────────


def test_full_address_chain_merges_into_one_span():
    text = "ที่อยู่ 45/12 หมู่ 3 ตำบลบางพระ อำเภอศรีราชา จังหวัดชลบุรี 20110 โทร 081-234-5678"
    addrs = _addr_texts(text)
    assert len(addrs) == 1, addrs
    assert addrs[0].startswith("45/12")
    assert addrs[0].endswith("20110")


def test_building_name_bridge_merges():
    # The uncaptured building name between fragments carries an address
    # structure word (อาคาร), so the chain may bridge across it.
    text = "ที่อยู่ 199 อาคารทัวร์ไทย ถนนพหลโยธิน แขวงจอมพล เขตจตุจักร กรุงเทพมหานคร 10900"
    addrs = _addr_texts(text)
    assert len(addrs) == 1, addrs
    assert "อาคารทัวร์ไทย" in addrs[0]


def test_two_parties_addresses_do_not_merge():
    text = "ผู้ซื้อ อยู่บ้านเลขที่ 12 ซอยพัฒนา 3 ผู้ขาย อยู่บ้านเลขที่ 99 ซอยเจริญ 7"
    addrs = _addr_texts(text)
    assert len(addrs) >= 2, addrs
    assert not any("ผู้ขาย" in a for a in addrs), addrs


def test_no_merge_across_newline_or_tab():
    for sep in ("\n", "\t"):
        text = f"บ้านเลขที่ 12 ซอยพัฒนา 3{sep}บ้านเลขที่ 99 ซอยเจริญ 7"
        addrs = _addr_texts(text)
        assert len(addrs) >= 2, (sep, addrs)


def test_no_merge_across_an_intervening_entity():
    # A NAME sitting between two address fragments splits the chain — merging
    # across it would create overlapping spans after dedupe promised none.
    text = "บ้านเลขที่ 12 ซอยพัฒนา 3 นายสมชาย ใจดี ตำบลบางพระ อำเภอศรีราชา"
    ents = detect_all(text)
    addr_spans = [s for s, _ in _spans_of(ents, "ADDRESS")]
    name_spans = [e.span for e in ents if e.data_type == "NAME"]
    if name_spans:  # CRF-dependent; only assert the invariant when a name won
        for a in addr_spans:
            for n in name_spans:
                assert a[1] <= n[0] or n[1] <= a[0], (a, n)


def test_output_stays_sorted_and_non_overlapping():
    text = "ที่อยู่ 45/12 หมู่ 3 ตำบลบางพระ อำเภอศรีราชา จังหวัดชลบุรี 20110 และบัตร 1101700230708"
    ents = detect_all(text)
    for a, b in zip(ents, ents[1:]):
        assert a.span[0] <= b.span[0]
        assert a.span[1] <= b.span[0], (a.span, b.span)


def test_merged_entity_fields_are_coherent():
    text = "ที่อยู่ 45/12 หมู่ 3 ตำบลบางพระ อำเภอศรีราชา จังหวัดชลบุรี 20110"
    ents = [e for e in detect_all(text) if e.data_type == "ADDRESS"]
    assert len(ents) == 1
    e = ents[0]
    assert e.original_text == text[e.span[0] : e.span[1]]
    # A merged address goes to the Thai-text surrogate generator; the generic
    # FP fallback would replace Thai script with ASCII gibberish.
    assert e.redact_type == "TB"


def test_merge_helper_is_idempotent():
    text = "ที่อยู่ 45/12 หมู่ 3 ตำบลบางพระ อำเภอศรีราชา จังหวัดชลบุรี 20110"
    once = detect_all(text)
    again = merge_address_spans(text, once)
    assert [(e.span, e.data_type) for e in again] == [(e.span, e.data_type) for e in once]


# ── negative-slice junk guards (fp_detector) ───────────────────────────────


def test_order_number_with_be_year_is_not_an_address():
    # "คำสั่งที่ 27/2569" — N/<Buddhist year> after a bare เลขที่ is a document
    # number. An explicit house or address label keeps the old behavior.
    assert not any(
        e.data_type == "ADDRESS" for e in detect_fp("ตามคำสั่งที่กล่าวอ้าง เลขที่ 27/2569 ลงวันที่ 8 กรกฎาคม")
    )
    assert any(e.data_type == "ADDRESS" for e in detect_fp("ที่อยู่ 27/2569 ถนนสุขุมวิท"))
    assert any(e.data_type == "ADDRESS" for e in detect_fp("บ้านเลขที่ 27/2569"))


def test_government_document_codes_are_not_plates():
    # "ที่ ศธ 0521/ว 118" — ministry abbreviation + number is a document
    # reference; the slash and the blocklist both say so.
    ents = detect_fp("หนังสือที่ ศธ 0521/ว 118 ลงวันที่ 12 มิถุนายน 2569")
    assert not any(e.data_type == "VEHICLE_PLATE" for e in ents)


def test_plate_cue_overrides_the_ministry_blocklist():
    # กค is a ministry code AND a legitimate plate prefix; the cue decides.
    ents = detect_fp("ทะเบียนรถ กค 0409 กรุงเทพมหานคร")
    assert any(e.data_type == "VEHICLE_PLATE" for e in ents)


def test_plain_uncued_plate_still_detected():
    ents = detect_fp("รถเก๋งสีดำ ขก 4471 ขับผ่านไปทางทิศเหนือ")
    assert any(e.data_type == "VEHICLE_PLATE" for e in ents)


def test_partially_separated_10_digit_is_not_a_bank_account_without_cue():
    # "2569-004512" — a year-prefixed document number. Not Thai bank format
    # (xxx-x-xxxxx-x fully separated, xxxxxxx-xxx, or bare), so without a bank
    # cue it is an honest ID_NUMBER — still masked, no fabricated account.
    ents = detect_fp("ใบเสร็จรับเงินเลขที่ 2569-004512 ออกโดยฝ่ายการเงิน")
    types = {e.data_type for e in ents if "2569-004512" in e.original_text}
    assert "BANK_ACCOUNT" not in types
    assert "ID_NUMBER" in types


def test_partially_separated_with_bank_cue_stays_bank():
    ents = detect_fp("โอนเข้าบัญชี 2569-004512 ธนาคารตัวอย่าง")
    assert any(e.data_type == "BANK_ACCOUNT" for e in ents)


def test_fully_separated_bank_format_still_detected():
    ents = detect_fp("เลขที่บัญชี 123-4-56789-0 สาขาสีลม")
    assert any(e.data_type == "BANK_ACCOUNT" for e in ents)
