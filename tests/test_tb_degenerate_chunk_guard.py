"""Degenerate whole-chunk NER span guard (gov-form OCR gap, F1).

On sufficiently noisy OCR text the thainer CRF can return a SINGLE span
covering nearly an entire chunk instead of abstaining. When that span's label
isn't in LABEL_MAP the whole chunk silently contributes zero entities --
including any real name the model would tag correctly in isolation. These
tests pin the guard: detect that degenerate shape, discard the span, and
re-tag the chunk's core one physical line at a time so a clean line's PII
survives a noisy neighbour.
"""

import logging

import pii_redactor.detectors.tb_detector as tbd

# Reproduced คร.1 (family registration form) print-quality OCR text from the
# Track A gov-form investigation (M6-P0). Synthetic -- no real personal data.
KHOR_ROR_1_OCR_TEXT = (
    "SYNTHETIC TEST INPUT · NOREAL PERSONAL DATA\n2\nคำร้องที่.\n"
    "คร.1\nร\n\n(ส่ำหรับเจ้าหน้าที่)\n"
    "คำร้องขอจดทะเบียนและบันทึกทะเบียนครอบครัว\n"
    "q\nc\nเขียนที่.\ns\n*+ +-** **++ * +\nJ1 t๑*+**±+r\nวันที่.\n"
    ".พ.ศ.\n.เดือน.\n.**….…*.*\n+…+.*+*+**+\n**F+-TR\n"
    "ข้าพเจ้าสมชายใจดี\n13122+1506581\n"
    "เลขประจำตัวประชาชน\n1312271505581\n"
    "และ...มาลีรักดี\nL\nขอยื่นคำร้องเพื่อ\n"
    "เลขประจำตัวประชาชน\n49516$7747108\n4951607747108\n"
    "จดทะเบียนการหย่า\nจดทะเบียนสมรส\n"
    "จดทะเบียนรับบุตรบุญธรรม\n"
    "จดทะเบียนรับรองบุตร\nLBEUOBMLUUNn\n"
    "จดทะเบียนเลิกรับบุตรบุญธรรม\nCUNOEUMNMAMSUUM\n"
    "OU\n6P\n(aEn) MLSUUNOENLBUOIMeEM\n5\n.±:*::±:±.\n(ลงชื่อ)..\n(ลงชื่อ).\n"
    "..ผูร้อง\n...ผูร้อง\n(\n)\n(\n(สำหรับเจ้าหน้าที่)\n"
    "a\nความเห็น\n..เจ้าหน้าที่\n(ลงชื่อ)..\nคำสั้ง\n"
    "(ลงชื่อ)..\n.นายทะเบียน\n(\n1"
)


def _with_engine(monkeypatch, engine):
    monkeypatch.setitem(tbd._ner_cache, "thainer", engine)
    monkeypatch.setenv("AIGUARD_NER_ENGINE", "thainer")


class DegenerateWholeChunkNER:
    """Simulates the reproduced OCR mechanism directly: tagging the whole
    (multi-line) chunk in one call returns a single degenerate span; tagging
    an individual physical line returns whatever real entity that line
    carries (only ``target_line`` carries one here)."""

    def __init__(self, target_line, whole_label="LAW"):
        self.target_line = target_line
        self.whole_label = whole_label
        self.calls = []

    def tag(self, chunk):
        self.calls.append(chunk)
        if "\n" not in chunk:
            if chunk == self.target_line:
                return [(chunk, "B-PERSON")]
            return [(chunk, "O")]
        return [(chunk, f"B-{self.whole_label}")]


def test_degenerate_chunk_unmapped_label_falls_back_to_line_by_line(monkeypatch):
    """Single span, label not in LABEL_MAP, covering the whole chunk ->
    discarded and re-tagged line-by-line.

    The name line is GLUED (no internal space, as in the real OCR corpus)
    rather than "สมชาย ใจดี" -- a spaced name would also be recovered by the
    pre-existing, unrelated isolated-short-line retry (`_ISOLATED_NAME_LINE_RE`
    requires a space), which would make this test pass even without the new
    guard and defeat it as a regression test.
    """
    ner = DegenerateWholeChunkNER(target_line="สมชายใจดี")
    _with_engine(monkeypatch, ner)
    text = "หัวข้อ แบบฟอร์ม\nสมชายใจดี\nเอกสาร แนบ"

    names = [e for e in tbd.detect_tb(text) if e.data_type == "NAME"]

    start = text.index("สมชายใจดี")
    assert [(e.original_text, e.span) for e in names] == [
        ("สมชายใจดี", (start, start + len("สมชายใจดี")))
    ]
    # first call is the whole-chunk attempt; the fallback re-tags every
    # non-blank physical line individually.
    assert ner.calls[0] == text
    assert "สมชายใจดี" in ner.calls[1:]


def test_degenerate_chunk_none_mapped_label_falls_back_to_line_by_line(monkeypatch):
    """LABEL_MAP maps several labels (TIME, MONEY, PERCENT, FACILITY, PRODUCT)
    explicitly to None -- those keys ARE present 'in' LABEL_MAP, so a naive
    `label not in LABEL_MAP` check would miss them and never trigger the
    fallback for this shape, even though _finalize_tb_candidate rejects a
    None-mapped label exactly like a missing one. A single degenerate span
    labeled MONEY, covering the whole (2-line, so it does NOT cross >=3
    lines) chunk core must still trigger the line-by-line fallback."""
    ner = DegenerateWholeChunkNER(target_line="สมชายใจดี", whole_label="MONEY")
    _with_engine(monkeypatch, ner)
    text = "หัวข้อ แบบฟอร์ม\nสมชายใจดี"

    names = [e for e in tbd.detect_tb(text) if e.data_type == "NAME"]

    start = text.index("สมชายใจดี")
    assert [(e.original_text, e.span) for e in names] == [
        ("สมชายใจดี", (start, start + len("สมชายใจดี")))
    ]
    assert ner.calls[0] == text
    assert "สมชายใจดี" in ner.calls[1:]


def test_degenerate_chunk_mapped_label_crossing_lines_falls_back(monkeypatch):
    """Single span, label IS in LABEL_MAP, but the span crosses >=3 lines ->
    still treated as degenerate (a real NAME/DATE/etc never spans that much
    of a multi-field form)."""
    ner = DegenerateWholeChunkNER(target_line="สมชาย ใจดี", whole_label="PERSON")
    _with_engine(monkeypatch, ner)
    text = "บรรทัดหนึ่ง\nบรรทัดสอง\nสมชาย ใจดี\nบรรทัดสี่"

    names = [e for e in tbd.detect_tb(text) if e.data_type == "NAME"]

    start = text.index("สมชาย ใจดี")
    assert [(e.original_text, e.span) for e in names] == [
        ("สมชาย ใจดี", (start, start + len("สมชาย ใจดี")))
    ]
    assert ner.calls[0] == text
    assert "สมชาย ใจดี" in ner.calls[1:]


def test_ordinary_chunk_single_mapped_span_within_one_line_untouched(monkeypatch):
    """Single span, mapped label, does NOT cross >=3 lines -> normal path,
    no line-by-line re-tagging call is issued."""
    ner = DegenerateWholeChunkNER(target_line="สมชาย ใจดี", whole_label="PERSON")
    _with_engine(monkeypatch, ner)
    text = "สมชาย ใจดี"  # single line: the whole-chunk call IS the per-line shape

    names = [e for e in tbd.detect_tb(text) if e.data_type == "NAME"]

    assert [(e.original_text, e.span) for e in names] == [("สมชาย ใจดี", (0, len(text)))]
    # only the one whole-chunk call was made; no fallback re-tagging.
    assert ner.calls == [text]


class TwoSpanNER:
    """Returns two spans in a single tag() call -- one real NAME, one
    unmapped label -- so a multi-entity chunk is never mistaken for the
    single-degenerate-span shape."""

    def __init__(self):
        self.calls = []

    def tag(self, chunk):
        self.calls.append(chunk)
        return [
            ("สมชาย ใจดี", "B-PERSON"),
            (" ทำงานที่ ", "O"),
            ("บริษัทลึกลับ", "B-LAW"),
        ]


def test_ordinary_chunk_multiple_spans_untouched(monkeypatch):
    """Multi-entity chunk (one span happens to carry an unmapped label) is
    processed normally: the mapped span survives, the unmapped one is
    dropped as always, and no fallback re-tagging call is issued."""
    ner = TwoSpanNER()
    _with_engine(monkeypatch, ner)
    text = "สมชาย ใจดี ทำงานที่ บริษัทลึกลับ"

    entities = tbd.detect_tb(text)

    names = [e for e in entities if e.data_type == "NAME"]
    assert [(e.original_text, e.span) for e in names] == [("สมชาย ใจดี", (0, len("สมชาย ใจดี")))]
    assert not any(e.original_text == "บริษัทลึกลับ" for e in entities)
    assert ner.calls == [text]


def test_degenerate_chunk_line_retag_offsets_map_to_original_text(monkeypatch):
    """Offset correctness: when the degenerate chunk is not at the start of
    the document, the recovered entity's span must still slice the ORIGINAL
    text (not the chunk-local or line-local text) to the expected string.

    Glued name line, same reasoning as the unmapped-label test above: a
    spaced name would also be recovered by the pre-existing isolated-line
    retry regardless of this guard.
    """
    ner = DegenerateWholeChunkNER(target_line="สมชายใจดี")
    _with_engine(monkeypatch, ner)
    filler = " ".join(f"ประโยคเติมความยาวหมายเลข {i} เพื่อดันข้อความให้ยาวขึ้น" for i in range(20))
    text = filler + "\nหัวข้อฟอร์ม\nสมชายใจดี\nท้ายเอกสาร"

    names = [e for e in tbd.detect_tb(text) if e.data_type == "NAME"]

    start = text.index("สมชายใจดี")
    assert len(names) == 1
    e = names[0]
    assert e.span == (start, start + len("สมชายใจดี"))
    assert text[e.span[0] : e.span[1]] == e.original_text == "สมชายใจดี"


def test_degenerate_chunk_logs_label_and_length_only_no_text(monkeypatch, caplog):
    """The warning must name the unmapped label and the chunk length, and
    must NOT embed any text content (PII-free logs, per project invariant)."""
    ner = DegenerateWholeChunkNER(target_line="สมชาย ใจดี", whole_label="LAW")
    _with_engine(monkeypatch, ner)
    text = "หัวข้อ แบบฟอร์ม\nสมชาย ใจดี\nเอกสาร แนบ"

    with caplog.at_level(logging.WARNING, logger="pii_redactor.detectors.tb_detector"):
        tbd.detect_tb(text)

    degenerate_records = [r for r in caplog.records if "Degenerate whole-chunk" in r.message]
    assert len(degenerate_records) == 1
    message = degenerate_records[0].message
    assert "LAW" in message
    assert str(len(text)) in message
    assert "สมชาย" not in message
    assert text not in message


def test_detect_tb_on_reproduced_gov_form_ocr_text_recovers_names():
    """End-to-end regression on the reproduced คร.1 OCR text (real thainer
    CRF, no monkeypatching): before the guard this yielded zero NAME
    entities anywhere in the document (both names lived in chunks where a
    single degenerate LAW span consumed the whole chunk); after the guard,
    both names are tagged NAME."""
    entities = tbd.detect_tb(KHOR_ROR_1_OCR_TEXT)

    names = [e for e in entities if e.data_type == "NAME"]
    name_texts = {e.original_text for e in names}
    assert any("สมชายใจดี" in t for t in name_texts)
    assert any("มาลีรักดี" in t for t in name_texts)
    for e in names:
        assert KHOR_ROR_1_OCR_TEXT[e.span[0] : e.span[1]] == e.original_text
