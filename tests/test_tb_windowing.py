"""Stride-chunk NER windowing: ~1.2x chars tagged instead of ~7x, offsets exact."""

import pytest

import pii_redactor.detectors.tb_detector as tbd


class SpyNER:
    """Counts every character handed to .tag(); finds no entities."""

    def __init__(self):
        self.chars_tagged = 0
        self.calls = 0

    def tag(self, chunk):
        self.chars_tagged += len(chunk)
        self.calls += 1
        return [(chunk, "O")]


class NameNER:
    """Tags every occurrence of 'สมชาย' in the chunk as PERSON."""

    def tag(self, chunk):
        out = []
        pos = 0
        while True:
            i = chunk.find("สมชาย", pos)
            if i < 0:
                out.append((chunk[pos:], "O"))
                break
            if i > pos:
                out.append((chunk[pos:i], "O"))
            out.append(("สมชาย", "B-PERSON"))
            pos = i + len("สมชาย")
        return [(w, t) for (w, t) in out if w]


class IsolatedLineNER:
    """Recognizes one name only when the model sees that line by itself."""

    target = "สมชาย ใจดี"

    def __init__(self):
        self.calls = []

    def tag(self, chunk):
        self.calls.append(chunk)
        if chunk == self.target:
            return [(chunk, "B-PERSON")]
        return [(chunk, "O")]


class GreedyIsolatedNER:
    """Returns a name for each isolated line."""

    def __init__(self):
        self.calls = []

    def tag(self, chunk):
        self.calls.append(chunk)
        return [(chunk, "O" if "\n" in chunk else "B-PERSON")]


class ContextOrganizationNER(IsolatedLineNER):
    """Returns an organization in the full text."""

    def tag(self, chunk):
        self.calls.append(chunk)
        if "\n" not in chunk:
            return [(chunk, "B-PERSON")]
        before, target, after = chunk.partition(self.target)
        out = []
        if before:
            out.append((before, "O"))
        out.append((target, "B-ORGANIZATION"))
        if after:
            out.append((after, "O"))
        return out


class PartialNameExpansionNER(IsolatedLineNER):
    """Returns a short name in context and a full name alone."""

    def tag(self, chunk):
        self.calls.append(chunk)
        if chunk == self.target:
            return [(chunk, "B-PERSON")]
        if "\n" not in chunk:
            return [(chunk, "O")]
        out = []
        pos = 0
        while True:
            start = chunk.find(self.target, pos)
            if start < 0:
                if pos < len(chunk):
                    out.append((chunk[pos:], "O"))
                break
            if start > pos:
                out.append((chunk[pos:start], "O"))
            given_name = "สมชาย"
            out.append((given_name, "B-PERSON"))
            pos = start + len(given_name)
        return out


class NonCoveringIsolatedNameNER(IsolatedLineNER):
    """Returns a full name in context and a short name alone."""

    def tag(self, chunk):
        self.calls.append(chunk)
        if chunk == self.target:
            return [("สมชาย", "B-PERSON"), (" ใจดี", "O")]
        if "\n" not in chunk:
            return [(chunk, "O")]
        before, target, after = chunk.partition(self.target)
        out = []
        if before:
            out.append((before, "O"))
        out.append((target, "B-PERSON"))
        if after:
            out.append((after, "O"))
        return out


class LeftExpandingNameNER:
    """Adds a cue before the name when the line is alone."""

    def __init__(self, line, name):
        self.line = line
        self.name = name
        self.calls = []

    def tag(self, chunk):
        self.calls.append(chunk)
        if chunk == self.line:
            return [(chunk, "B-PERSON")]
        if "\n" not in chunk:
            return [(chunk, "O")]
        before, line, after = chunk.partition(self.line)
        prefix, name, _ = line.partition(self.name)
        out = []
        if before:
            out.append((before, "O"))
        if prefix:
            out.append((prefix, "O"))
        out.append((name, "B-PERSON"))
        if after:
            out.append((after, "O"))
        return out


def _with_engine(monkeypatch, engine):
    monkeypatch.setitem(tbd._ner_cache, "thainer", engine)
    monkeypatch.setenv("AIGUARD_NER_ENGINE", "thainer")


def test_chars_tagged_is_near_linear(monkeypatch):
    spy = SpyNER()
    _with_engine(monkeypatch, spy)
    # ~30 sentences of ~40 chars -> old sliding window tagged ~7x
    text = " ".join(f"ประโยคทดสอบหมายเลข {i} มีความยาวประมาณนี้ครับ" for i in range(30))
    tbd.detect_tb(text)
    assert spy.chars_tagged <= 1.5 * len(text), (
        f"tagged {spy.chars_tagged} chars for a {len(text)}-char text "
        f"(> 1.5x — stride chunking is not in effect)"
    )


def test_entity_near_chunk_boundary_found_once(monkeypatch):
    _with_engine(monkeypatch, NameNER())
    # long filler so the name lands deep into a later chunk
    filler = " ".join(f"ประโยคเติมความยาวหมายเลข {i} เพื่อดันข้อความให้ยาวขึ้น" for i in range(20))
    text = filler + " ลงชื่อ สมชาย ผู้จัดการ"
    ents = [e for e in tbd.detect_tb(text) if "สมชาย" in e.original_text]
    assert len(ents) == 1
    e = ents[0]
    start = text.index("สมชาย")
    assert e.span[0] <= start < e.span[1]
    assert text[e.span[0] : e.span[1]] == e.original_text


def test_short_text_single_chunk(monkeypatch):
    spy = SpyNER()
    _with_engine(monkeypatch, spy)
    tbd.detect_tb("ประโยคเดียวสั้นๆ")
    assert spy.calls == 1


def test_default_thainer_retries_an_unclaimed_short_thai_line(monkeypatch):
    ner = IsolatedLineNER()
    _with_engine(monkeypatch, ner)
    text = "หัวข้อ แบบฟอร์ม\nสมชาย ใจดี\nเอกสาร แนบ"

    names = [e for e in tbd.detect_tb(text) if e.data_type == "NAME"]

    assert [(e.original_text, e.span) for e in names] == [
        ("สมชาย ใจดี", (text.index("สมชาย"), text.index("สมชาย") + len("สมชาย ใจดี")))
    ]
    assert ner.calls[0] == text
    assert "สมชาย ใจดี" in ner.calls[1:]


def test_isolated_line_fallback_skips_lines_already_claimed_by_an_entity(monkeypatch):
    ner = ContextOrganizationNER()
    _with_engine(monkeypatch, ner)
    text = "หัวข้อ แบบฟอร์ม\nสมชาย ใจดี\nเอกสาร แนบ"

    entities = tbd.detect_tb(text)

    assert any(e.data_type == "ORGANIZATION" and e.original_text == ner.target for e in entities)
    assert not any(e.data_type == "NAME" and e.original_text == ner.target for e in entities)
    assert ner.target not in ner.calls[1:]


def test_isolated_line_fallback_expands_and_replaces_a_partial_name(monkeypatch):
    ner = PartialNameExpansionNER()
    _with_engine(monkeypatch, ner)
    text = "หัวข้อ แบบฟอร์ม\nสมชาย ใจดี\nเอกสาร แนบ"

    names = [e for e in tbd.detect_tb(text) if e.data_type == "NAME"]

    assert [(e.original_text, e.span) for e in names] == [
        (ner.target, (text.index(ner.target), text.index(ner.target) + len(ner.target)))
    ]
    assert ner.target in ner.calls[1:]


def test_isolated_line_fallback_keeps_original_name_when_retry_does_not_cover_it(monkeypatch):
    ner = NonCoveringIsolatedNameNER()
    _with_engine(monkeypatch, ner)
    text = "หัวข้อ แบบฟอร์ม\nสมชาย ใจดี\nเอกสาร แนบ"

    names = [e for e in tbd.detect_tb(text) if e.data_type == "NAME"]

    assert [(e.original_text, e.span) for e in names] == [
        (ner.target, (text.index(ner.target), text.index(ner.target) + len(ner.target)))
    ]
    assert ner.target in ner.calls[1:]


@pytest.mark.parametrize(
    ("line", "name"),
    [
        ("ชื่อ กมล ทวีสิน", "กมล ทวีสิน"),
        ("ผู้ค้ำประกัน ดารณี สินสมบัติ", "ดารณี สินสมบัติ"),
    ],
)
def test_isolated_line_fallback_never_expands_name_left_into_a_prefix(monkeypatch, line, name):
    ner = LeftExpandingNameNER(line, name)
    _with_engine(monkeypatch, ner)
    text = f"เอกสาร แนบ\n{line}\nข้อมูล เพิ่มเติม"

    names = [e for e in tbd.detect_tb(text) if e.data_type == "NAME"]

    assert [(e.original_text, e.span) for e in names] == [
        (name, (text.index(name), text.index(name) + len(name)))
    ]
    assert line in ner.calls[1:]


@pytest.mark.parametrize(
    ("line", "name"),
    [
        ("ผู้เช่า ปณิธาน วรรณกิจ", "ปณิธาน วรรณกิจ"),
        ("ชื่อ กมล ทวีสิน", "กมล ทวีสิน"),
        ("ผู้ค้ำประกัน ดารณี สินสมบัติ", "ดารณี สินสมบัติ"),
    ],
)
def test_unoccupied_isolated_name_trims_a_general_field_or_role_prefix(line, name):
    ner = LeftExpandingNameNER(line, name)
    text = f"เอกสาร แนบ\n{line}\nข้อมูล เพิ่มเติม"

    names, superseded_ids = tbd._isolated_line_name_candidates(text, ner, [])

    assert [(e.original_text, e.span) for e in names] == [
        (name, (text.index(name), text.index(name) + len(name)))
    ]
    assert superseded_ids == set()


@pytest.mark.parametrize(
    "line",
    [
        "ผู้เช่า ต้องชำระ ค่าเช่า",
        "ชื่อ สถานประกอบการ ให้ครบถ้วน",
        "ผู้ป่วยใน ห้องพิเศษ",
    ],
)
def test_unoccupied_isolated_prefix_lines_reject_semantic_non_names(line):
    ner = LeftExpandingNameNER(line, "")
    text = f"เอกสาร แนบ\n{line}\nข้อมูล เพิ่มเติม"

    names, superseded_ids = tbd._isolated_line_name_candidates(text, ner, [])

    assert names == []
    assert superseded_ids == set()


def test_isolated_line_fallback_rejects_non_name_line_shapes(monkeypatch):
    ner = GreedyIsolatedNER()
    _with_engine(monkeypatch, ner)
    eligible = "สมชาย ใจดี"
    rejected = [
        "หัวข้อ",
        "หนึ่ง สอง สาม สี่ ห้า",
        "สมชาย 1234",
        "Somchai Jaidee",
        "สมชาย-ใจดี",
    ]
    text = "\n".join([eligible, *rejected])

    names = [e.original_text for e in tbd.detect_tb(text) if e.data_type == "NAME"]

    assert names == [eligible]
    assert eligible in ner.calls[1:]
    assert all(line not in ner.calls[1:] for line in rejected)


def test_isolated_line_fallback_has_a_hard_call_cap(monkeypatch):
    ner = GreedyIsolatedNER()
    _with_engine(monkeypatch, ner)
    text = "\n".join(["สมชาย ใจดี"] * (tbd._ISOLATED_NAME_MAX_LINES + 5))

    names = [e for e in tbd.detect_tb(text) if e.data_type == "NAME"]

    assert ner.calls[0] == text
    assert len(ner.calls) == 1 + tbd._ISOLATED_NAME_MAX_LINES
    assert len(names) == tbd._ISOLATED_NAME_MAX_LINES


def test_partial_name_expansion_respects_the_hard_call_cap(monkeypatch):
    ner = PartialNameExpansionNER()
    _with_engine(monkeypatch, ner)
    line_count = tbd._ISOLATED_NAME_MAX_LINES + 5
    text = "\n".join([ner.target] * line_count)

    names = [e for e in tbd.detect_tb(text) if e.data_type == "NAME"]

    assert len(ner.calls) == 1 + tbd._ISOLATED_NAME_MAX_LINES
    assert sum(e.original_text == ner.target for e in names) == tbd._ISOLATED_NAME_MAX_LINES
    assert sum(e.original_text == "สมชาย" for e in names) == 5


@pytest.mark.parametrize("engine_name", ["wangchanberta", "tner"])
def test_isolated_line_fallback_never_adds_calls_for_other_single_engines(monkeypatch, engine_name):
    ner = GreedyIsolatedNER()
    monkeypatch.setitem(tbd._ner_cache, engine_name, ner)
    monkeypatch.setenv("AIGUARD_NER_ENGINE", engine_name)

    entities = tbd.detect_tb("หัวข้อ แบบฟอร์ม\nสมชาย ใจดี\nเอกสาร แนบ")

    assert ner.calls == ["หัวข้อ แบบฟอร์ม\nสมชาย ใจดี\nเอกสาร แนบ"]
    assert not any(e.data_type == "NAME" for e in entities)


def test_isolated_line_fallback_never_adds_calls_for_union(monkeypatch):
    thainer = GreedyIsolatedNER()
    wangchanberta = GreedyIsolatedNER()
    monkeypatch.setitem(tbd._ner_cache, "thainer", thainer)
    monkeypatch.setitem(tbd._ner_cache, "wangchanberta", wangchanberta)
    monkeypatch.setenv("AIGUARD_NER_ENGINE", "union")
    text = "หัวข้อ แบบฟอร์ม\nสมชาย ใจดี\nเอกสาร แนบ"

    entities = tbd.detect_tb(text)

    assert thainer.calls == [text]
    assert wangchanberta.calls == [text]
    assert not any(e.data_type == "NAME" for e in entities)


def test_isolated_line_fallback_never_runs_for_finetuned(monkeypatch):
    calls = []
    monkeypatch.setenv("AIGUARD_NER_ENGINE", "finetuned")
    monkeypatch.setattr(tbd, "_detect_tb_finetuned", lambda text: calls.append(text) or [])
    text = "หัวข้อ แบบฟอร์ม\nสมชาย ใจดี\nเอกสาร แนบ"

    assert tbd.detect_tb(text) == []
    assert calls == [text]
