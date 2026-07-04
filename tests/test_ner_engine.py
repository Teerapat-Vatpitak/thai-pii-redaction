"""Engine selection for tb_detector's NER (AIGUARD_NER_ENGINE env var)."""
import builtins

import pytest

from pii_redactor.detectors import tb_detector


class _FakeNER:
    def __init__(self, engine):
        self.engine = engine


def _reset(monkeypatch):
    monkeypatch.setattr(tb_detector, "_ner", None)


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
