"""Stride-chunk NER windowing: ~1.2x chars tagged instead of ~7x, offsets exact."""
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
    assert text[e.span[0]:e.span[1]] == e.original_text


def test_short_text_single_chunk(monkeypatch):
    spy = SpyNER()
    _with_engine(monkeypatch, spy)
    tbd.detect_tb("ประโยคเดียวสั้นๆ")
    assert spy.calls == 1
