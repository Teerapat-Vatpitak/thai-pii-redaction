"""Engine selection for tb_detector's NER (AIGUARD_NER_ENGINE env var)."""

import builtins

import pytest

from pii_redactor.detectors import tb_detector


class _FakeNER:
    def __init__(self, engine):
        self.engine = engine


def _reset(monkeypatch):
    monkeypatch.setattr(tb_detector, "_ner_cache", {})


# --- Tier 1: always runs, no transformers required -------------------------


def test_default_engine_is_thainer_when_env_unset(monkeypatch):
    monkeypatch.delenv("AIGUARD_NER_ENGINE", raising=False)
    _reset(monkeypatch)
    monkeypatch.setattr(tb_detector, "NER", _FakeNER)
    ner = tb_detector._get_ner()
    assert ner.engine == "thainer"


def test_unknown_engine_raises_value_error(monkeypatch):
    monkeypatch.setenv("AIGUARD_NER_ENGINE", "bogus")
    _reset(monkeypatch)
    with pytest.raises(ValueError, match="bogus"):
        tb_detector._get_ner()


def test_wangchanberta_without_transformers_raises(monkeypatch):
    monkeypatch.setenv("AIGUARD_NER_ENGINE", "wangchanberta")
    _reset(monkeypatch)
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "transformers":
            raise ImportError("mocked missing dependency")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(tb_detector.NEREngineUnavailableError, match="requirements-ml.txt"):
        tb_detector._get_ner()


# --- Tier 2: requires transformers installed --------------------------------


def test_wangchanberta_maps_to_thainer_v2_engine(monkeypatch):
    pytest.importorskip("transformers")
    monkeypatch.setenv("AIGUARD_NER_ENGINE", "wangchanberta")
    _reset(monkeypatch)
    monkeypatch.setattr(tb_detector, "NER", _FakeNER)
    ner = tb_detector._get_ner()
    assert ner.engine == "thainer-v2"


def test_wangchanberta_real_engine_detects_person(monkeypatch):
    pytest.importorskip("transformers")
    monkeypatch.setenv("AIGUARD_NER_ENGINE", "wangchanberta")
    _reset(monkeypatch)
    ner = tb_detector._get_ner()
    tagged = ner.tag("นายสมชาย ใจดี อาศัยอยู่ที่กรุงเทพมหานคร")
    labels = {tag.split("-", 1)[1] for _, tag in tagged if tag != "O"}
    assert "PERSON" in labels


def test_engine_is_cached_after_first_load(monkeypatch):
    monkeypatch.delenv("AIGUARD_NER_ENGINE", raising=False)
    _reset(monkeypatch)
    calls = {"n": 0}

    class _CountingNER:
        def __init__(self, engine):
            calls["n"] += 1
            self.engine = engine

    monkeypatch.setattr(tb_detector, "NER", _CountingNER)
    first = tb_detector._get_ner()
    second = tb_detector._get_ner()
    assert first is second
    assert calls["n"] == 1


def test_union_without_transformers_raises(monkeypatch):
    monkeypatch.setenv("AIGUARD_NER_ENGINE", "union")
    _reset(monkeypatch)
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "transformers":
            raise ImportError("mocked missing dependency")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    from pii_redactor.detectors.tb_detector import detect_tb

    with pytest.raises(tb_detector.NEREngineUnavailableError, match="requirements-ml.txt"):
        detect_tb("นายสมชาย ใจดี อยู่กรุงเทพมหานคร")


def test_union_runs_both_engines_and_merges(monkeypatch):
    pytest.importorskip("transformers")
    _reset(monkeypatch)
    from pii_redactor.detectors.tb_detector import detect_tb

    # Name (title-cued, so it is caught regardless of engine) and a clearly
    # separate address -- disjoint spans, so dedup never drops one for the other.
    text = "นายวิชัย ประสงค์ดี อยู่บ้านเลขที่ 45/12 หมู่ 3 ตำบลบางพระ อำเภอศรีราชา จังหวัดชลบุรี"

    monkeypatch.setenv("AIGUARD_NER_ENGINE", "thainer")
    crf_types = {e.data_type for e in detect_tb(text)}
    monkeypatch.setenv("AIGUARD_NER_ENGINE", "union")
    uni_types = {e.data_type for e in detect_tb(text)}

    # Union mode ran and produced a person + a location.
    assert "NAME" in uni_types
    assert "ADDRESS" in uni_types
    # Union keeps everything CRF alone found (superset; entities are disjoint so
    # no cross-engine overlap can drop a type).
    assert crf_types <= uni_types


def test_tner_is_a_known_engine_but_never_the_default(monkeypatch):
    """The proposal names TNER as a supplementary engine while also claiming
    detection runs offline in-container. Both hold only if tner is opt-in."""
    from pii_redactor.detectors import tb_detector

    assert "tner" in tb_detector._ENGINE_CONFIG
    monkeypatch.delenv("AIGUARD_NER_ENGINE", raising=False)
    assert tb_detector._resolve_engine_name() == "thainer"


def test_tner_without_credentials_fails_loudly(monkeypatch):
    """Never silently fall back to the offline engine — a caller who asked for
    TNER and got CRF would believe they had recall they do not have."""
    from pii_redactor.detectors.tb_detector import NEREngineUnavailableError, _load_ner

    monkeypatch.delenv("AIFORTHAI_API_KEY", raising=False)
    with pytest.raises(NEREngineUnavailableError):
        _load_ner("tner")
