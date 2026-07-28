"""Integration contract of the opt-in fine-tuned engine path.

No trained model is required: a fake adapter drives the seams — the
model-as-verifier name-cue policy, the STUDENT_ID relabel past FP-first
dedupe, and the fail-loud behavior when the engine is selected but absent.
"""

from __future__ import annotations

import pytest

from pii_redactor.detectors import tb_detector
from pii_redactor.detectors.aggregate import detect_all
from pii_redactor.models import Entity


class _FakeEngine:
    def __init__(self, spans):
        self._spans = spans

    def spans(self, text):
        return self._spans


@pytest.fixture()
def finetuned_env(monkeypatch):
    monkeypatch.setenv("AIGUARD_NER_ENGINE", "finetuned")

    def install(spans):
        monkeypatch.setitem(tb_detector._finetuned_cache, "engine", _FakeEngine(spans))

    yield install
    tb_detector._finetuned_cache.pop("engine", None)


def test_selected_but_absent_engine_fails_loud(monkeypatch):
    monkeypatch.setenv("AIGUARD_NER_ENGINE", "finetuned")
    monkeypatch.delenv("AIGUARD_FINETUNED_MODEL_DIR", raising=False)
    tb_detector._finetuned_cache.pop("engine", None)
    from pii_redactor.detectors.finetuned_engine import FinetunedEngineUnavailableError

    with pytest.raises(FinetunedEngineUnavailableError):
        tb_detector.detect_tb("นายสมชาย ใจดี")


def test_model_spans_map_with_hygiene_and_upgrades(finetuned_env):
    text = "ผู้ป่วย สมบูรณ์ ทรงศิริ นัดวันที่ 12 มีนาคม 2569 ที่ตำบลบางพระ"
    name_lo = text.index("สมบูรณ์")
    date_lo = text.index("12 มีนาคม")
    loc_lo = text.index("บางพระ")
    finetuned_env(
        [
            (name_lo, name_lo + len("สมบูรณ์ ทรงศิริ"), "PERSON", 0.97),
            (date_lo, date_lo + len("12 มีนาคม 2569"), "DATE", 0.95),
            (loc_lo, loc_lo + len("บางพระ"), "LOCATION", 0.9),
        ]
    )
    ents = {e.data_type: e for e in tb_detector.detect_tb(text)}
    assert ents["NAME"].original_text == "สมบูรณ์ ทรงศิริ"
    assert "DATE" in ents
    # ตำบล cue upgrades the LOCATION span to ADDRESS
    assert ents["ADDRESS"].original_text == "บางพระ"


def test_extended_cue_needs_model_agreement(finetuned_env):
    # Role cue with NO model PERSON span -> the extended pass is dropped.
    text = "ผู้ติดต่อสำนักงาน ประสานจัดส่ง เอกสารทั่วไป"
    finetuned_env([])
    assert not [e for e in tb_detector.detect_tb(text) if e.data_type == "NAME"]

    # Same cue WITH a model span overlapping -> the fuller cue span survives.
    text2 = "ผู้ติดต่อ มานพ ดีเลิศ เบอร์ภายใน 1234"
    lo = text2.index("มานพ")
    finetuned_env([(lo, lo + len("มานพ"), "PERSON", 0.9)])
    names = [e.original_text for e in tb_detector.detect_tb(text2) if e.data_type == "NAME"]
    assert any("ดีเลิศ" in n for n in names), names


def test_strong_cues_survive_without_model(finetuned_env):
    finetuned_env([])
    text = "ผมชื่อ บุญชัย รักเรียน ครับ"
    names = [e.original_text for e in tb_detector.detect_tb(text) if e.data_type == "NAME"]
    assert any("บุญชัย" in n for n in names), names


def test_student_id_relabel_past_fp_dedupe(finetuned_env):
    # A cue-free 8-digit run: FP calls it ID_NUMBER; the model knows better.
    text = "อ้างอิง 66019901 ตามระบบ"
    lo = text.index("66019901")
    finetuned_env([(lo, lo + 8, "STUDENT_ID", 0.96)])
    ents = detect_all(text)
    types = {e.data_type for e in ents if e.span == (lo, lo + 8)}
    assert types == {"STUDENT_ID"}, types


def test_relabel_is_noop_for_crf(monkeypatch):
    monkeypatch.delenv("AIGUARD_NER_ENGINE", raising=False)
    text = "อ้างอิง 66019901 ตามระบบ"
    ents = detect_all(text)
    assert not [e for e in ents if e.data_type == "STUDENT_ID"]


def test_relabel_helper_contract():
    from pii_redactor.detectors.aggregate import _relabel_student_ids

    tb = [Entity("x", "TB", "STUDENT_ID", (5, 13), 0.9, "66019901")]
    kept = [Entity("y", "FP", "ID_NUMBER", (5, 13), 0.8, "66019901")]
    out = _relabel_student_ids(tb, kept)
    assert out[0].data_type == "STUDENT_ID"
    assert out[0].redact_type == "FP"  # provenance of the kept span is unchanged
