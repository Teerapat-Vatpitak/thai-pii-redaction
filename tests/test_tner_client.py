"""The AI for Thai TNER engine: the promise the proposal made in writing.

The submitted proposal ticks "uses at least one AI for Thai API" and names
TNER. Until now `_ENGINE_CONFIG` registered a `tner` slot that resolved to
`NER(engine="tner")` -- an engine PyThaiNLP does not have -- so selecting it
raised a raw library error instead of doing anything. That is the single
easiest commitment for a judge to check.

PROVENANCE NOTE: the wire shape pinned below (POST, `Apikey` header, form
field `text`, response `{"POS": [[word, pos], ...], "tags": [...]}`) is taken
from the published `aift` SDK, NOT from a live call -- the team has no API key
on this machine. These tests therefore prove the client handles that shape and
fails loudly on everything else; they do NOT prove the shape is current. Run
one real call before relying on it.
"""

import pytest

from pii_redactor.detectors import tner_client
from pii_redactor.detectors.tner_client import TnerEngine, TnerServiceError

SAMPLE = "นายสมชาย ใจดี อยู่กรุงเทพ"


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_tag_returns_word_tag_pairs_like_pythainlp(monkeypatch):
    """The decoder downstream expects PyThaiNLP's exact output shape.

    `_bio_to_spans` consumes [(word, "B-PERSON"), ...]. Returning the raw API
    payload instead would fail somewhere deep in span decoding, so the client's
    whole job is this translation.
    """
    payload = {
        "POS": [["นาย", "NCMN"], ["สมชาย", "NPRP"], ["ใจดี", "NPRP"]],
        "tags": ["B-PERSON", "I-PERSON", "I-PERSON"],
    }
    monkeypatch.setattr(tner_client.httpx, "post", lambda *a, **k: _FakeResponse(payload))

    tagged = TnerEngine(api_key="k").tag(SAMPLE)

    assert tagged == [("นาย", "B-PERSON"), ("สมชาย", "I-PERSON"), ("ใจดี", "I-PERSON")]


def test_a_missing_api_key_is_refused_at_construction():
    """Fail where the cause is, not on the first request."""
    with pytest.raises(TnerServiceError):
        TnerEngine(api_key="")


def test_a_transport_failure_becomes_a_named_error(monkeypatch):
    """A network error must not surface as a bare httpx exception.

    This engine is the only network-dependent path in the system, and the
    caller (`_load_ner`) already has a vocabulary for "this engine is not
    usable". Leaking the transport's own exception type through would make the
    platform return a 500 with no actionable message.
    """

    def _boom(*_args, **_kwargs):
        raise tner_client.httpx.ConnectError("no route to host")

    monkeypatch.setattr(tner_client.httpx, "post", _boom)

    with pytest.raises(TnerServiceError):
        TnerEngine(api_key="k").tag(SAMPLE)


def test_an_unexpected_payload_shape_is_refused_rather_than_guessed(monkeypatch):
    """If the API changes shape, say so instead of silently detecting nothing.

    Returning [] on an unrecognised payload would look exactly like "this text
    contains no names" -- a silent recall collapse on a service whose whole
    purpose is not missing PII.
    """
    monkeypatch.setattr(
        tner_client.httpx, "post", lambda *a, **k: _FakeResponse({"unexpected": "shape"})
    )

    with pytest.raises(TnerServiceError):
        TnerEngine(api_key="k").tag(SAMPLE)


def test_word_and_tag_counts_must_agree(monkeypatch):
    """A truncated tag list would silently drop the tail of the document."""
    payload = {"POS": [["นาย", "NCMN"], ["สมชาย", "NPRP"]], "tags": ["B-PERSON"]}
    monkeypatch.setattr(tner_client.httpx, "post", lambda *a, **k: _FakeResponse(payload))

    with pytest.raises(TnerServiceError):
        TnerEngine(api_key="k").tag(SAMPLE)
