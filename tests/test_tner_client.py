"""The AI for Thai TNER engine: the promise the proposal made in writing.

The submitted proposal ticks "uses at least one AI for Thai API" and names
TNER. Until now `_ENGINE_CONFIG` registered a `tner` slot that resolved to
`NER(engine="tner")` -- an engine PyThaiNLP does not have -- so selecting it
raised a raw library error instead of doing anything. That is the single
easiest commitment for a judge to check.

PROVENANCE NOTE: the live wire shape pinned below (POST, `Apikey` header, form
field `text`, response with parallel `words`, `POS`, and `tags` lists) was
verified on 2026-07-22. The decoder retains compatibility with the older
published `aift` SDK's `[word, pos]` pairs. These tests pin both shapes and the
compact live label vocabulary so a provider change cannot silently collapse
detection recall.
"""

import pytest

from pii_redactor.detectors import tner_client
from pii_redactor.detectors.ner_failure import NERFailureError
from pii_redactor.detectors.tb_detector import LABEL_MAP, _bio_to_spans
from pii_redactor.detectors.tner_client import (
    TnerEngine,
    TnerIncompleteError,
    TnerServiceError,
    TnerUnavailableError,
)

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


class _MalformedJsonResponse(_FakeResponse):
    def json(self):
        raise ValueError("synthetic response body must not escape")


def _product_traceback_locals(error):
    frames = []
    traceback = error.__traceback__
    while traceback is not None:
        if traceback.tb_frame.f_globals.get("__name__") == tner_client.__name__:
            frames.append(dict(traceback.tb_frame.f_locals))
        traceback = traceback.tb_next
    return frames


def test_tag_returns_word_tag_pairs_like_pythainlp(monkeypatch):
    """The decoder downstream expects PyThaiNLP's exact output shape.

    `_bio_to_spans` consumes [(word, "B-PERSON"), ...]. Returning the raw API
    payload instead would fail somewhere deep in span decoding, so the client's
    whole job is this translation.
    """
    payload = {
        "POS": [
            ["นาย", "NCMN"],
            ["สมชาย", "NPRP"],
            ["ใจดี", "NPRP"],
            ["อยู่", "VACT"],
            ["กรุงเทพ", "NPRP"],
        ],
        "tags": ["B-PERSON", "I-PERSON", "I-PERSON", "O", "O"],
    }
    monkeypatch.setattr(tner_client.httpx, "post", lambda *a, **k: _FakeResponse(payload))

    tagged = TnerEngine(api_key="k").tag(SAMPLE)

    assert tagged == [
        ("นาย", "B-PERSON"),
        ("สมชาย", "I-PERSON"),
        ("ใจดี", "I-PERSON"),
        ("อยู่", "O"),
        ("กรุงเทพ", "O"),
    ]


def test_live_parallel_words_field_is_used_instead_of_pos_tags(monkeypatch):
    """The live service returns POS tags and words in separate lists."""
    payload = {
        "words": ["นาย", "สมชาย", " ", "ใจดี", " ", "อยู่", "กรุงเทพ"],
        "POS": ["TTL", "NR", " ", "NR", " ", "VACT", "NR"],
        "tags": ["B-TTL", "B-PER", " ", "I-PER", " ", "O", "B-LOC"],
    }
    monkeypatch.setattr(tner_client.httpx, "post", lambda *a, **k: _FakeResponse(payload))

    tagged = TnerEngine(api_key="k").tag(SAMPLE)

    assert tagged == [
        ("นาย", "B-TTL"),
        ("สมชาย", "B-PER"),
        (" ", " "),
        ("ใจดี", "I-PER"),
        (" ", " "),
        ("อยู่", "O"),
        ("กรุงเทพ", "B-LOC"),
    ]


@pytest.mark.parametrize(
    ("text", "payload", "expected"),
    [
        (
            "นาย สมชาย",
            {
                "POS": [["นาย", "TTL"], ["สมชาย", "NR"]],
                "tags": ["B-PER", "I-PER"],
            },
            [("นาย สมชาย", 0, len("นาย สมชาย"), "PER")],
        ),
        (
            "สมชาย ใจดี",
            {
                "words": ["สมชาย", " ", "ใจดี"],
                "POS": ["NR", " ", "NR"],
                "tags": ["B-PER", " ", "I-PER"],
            },
            [("สมชาย ใจดี", 0, len("สมชาย ใจดี"), "PER")],
        ),
    ],
)
def test_tner_entity_spans_preserve_internal_source_whitespace(
    monkeypatch,
    text,
    payload,
    expected,
):
    monkeypatch.setattr(tner_client.httpx, "post", lambda *a, **k: _FakeResponse(payload))

    tagged = TnerEngine(api_key="k").tag(text)

    assert _bio_to_spans(tagged, text) == expected


def test_live_words_and_tag_counts_must_agree(monkeypatch):
    payload = {
        "words": ["นาย"],
        "POS": ["TTL", "NR"],
        "tags": ["B-TTL", "B-PER"],
    }
    monkeypatch.setattr(tner_client.httpx, "post", lambda *a, **k: _FakeResponse(payload))

    with pytest.raises(TnerServiceError):
        TnerEngine(api_key="k").tag(SAMPLE)


def test_a_missing_api_key_is_refused_at_construction():
    """Fail where the cause is, not on the first request."""
    with pytest.raises(TnerUnavailableError) as excinfo:
        TnerEngine(api_key="")
    assert excinfo.value.code == "ner_unavailable"
    assert excinfo.value.category == "configuration"
    assert excinfo.value.retryable is False
    assert excinfo.value.count == 0


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

    with pytest.raises(TnerUnavailableError) as excinfo:
        TnerEngine(api_key="k").tag(SAMPLE)
    assert excinfo.value.category == "network"
    assert excinfo.value.retryable is True


def test_a_local_post_failure_is_a_nonretryable_dependency_error(monkeypatch):
    def _boom(*_args, **_kwargs):
        raise RuntimeError("synthetic local client defect")

    monkeypatch.setattr(tner_client.httpx, "post", _boom)

    with pytest.raises(TnerUnavailableError) as excinfo:
        TnerEngine(api_key="k").tag(SAMPLE)

    assert excinfo.value.category == "dependency"
    assert excinfo.value.retryable is False
    assert "synthetic local client defect" not in str(excinfo.value)


def test_an_unexpected_payload_shape_is_refused_rather_than_guessed(monkeypatch):
    """If the API changes shape, say so instead of silently detecting nothing.

    Returning [] on an unrecognised payload would look exactly like "this text
    contains no names" -- a silent recall collapse on a service whose whole
    purpose is not missing PII.
    """
    monkeypatch.setattr(
        tner_client.httpx, "post", lambda *a, **k: _FakeResponse({"unexpected": "shape"})
    )

    with pytest.raises(TnerIncompleteError) as excinfo:
        TnerEngine(api_key="k").tag(SAMPLE)
    assert excinfo.value.code == "ner_incomplete"
    assert excinfo.value.category == "upstream"
    assert excinfo.value.retryable is False
    assert excinfo.value.count == 1


def test_word_and_tag_counts_must_agree(monkeypatch):
    """A truncated tag list would silently drop the tail of the document."""
    payload = {"POS": [["นาย", "NCMN"], ["สมชาย", "NPRP"]], "tags": ["B-PERSON"]}
    monkeypatch.setattr(tner_client.httpx, "post", lambda *a, **k: _FakeResponse(payload))

    with pytest.raises(TnerIncompleteError):
        TnerEngine(api_key="k").tag(SAMPLE)


def test_response_words_must_align_to_the_requested_chunk(monkeypatch):
    payload = {
        "words": ["นาย", "ข้อความที่ไม่ได้ส่ง"],
        "POS": ["TTL", "NCMN"],
        "tags": ["B-TTL", "O"],
    }
    monkeypatch.setattr(tner_client.httpx, "post", lambda *a, **k: _FakeResponse(payload))

    with pytest.raises(TnerIncompleteError):
        TnerEngine(api_key="k").tag(SAMPLE)


def test_well_shaped_truncated_tail_is_incomplete(monkeypatch):
    payload = {
        "words": ["นาย", "สมชาย"],
        "POS": ["TTL", "NR"],
        "tags": ["B-TTL", "B-PER"],
    }
    monkeypatch.setattr(tner_client.httpx, "post", lambda *a, **k: _FakeResponse(payload))

    with pytest.raises(TnerIncompleteError):
        TnerEngine(api_key="k").tag(SAMPLE)


@pytest.mark.parametrize(
    ("text", "payload"),
    [
        (
            "สมชาย",
            {"words": ["สมชาย"], "POS": ["NR"], "tags": [None]},
        ),
        (
            "สมชาย",
            {"words": ["สมชาย"], "POS": ["NR"], "tags": [123]},
        ),
        (
            "สมชาย",
            {"words": ["สมชาย"], "POS": ["NR"], "tags": [""]},
        ),
        (
            "สมชาย",
            {"words": ["สมชาย"], "POS": ["NR"], "tags": ["B-"]},
        ),
        (
            "สมชาย",
            {"words": ["สมชาย"], "POS": ["NR"], "tags": ["I-PER"]},
        ),
        (
            "สมชายใจดี",
            {
                "words": ["สมชาย", "ใจดี"],
                "POS": ["NR", "NR"],
                "tags": ["B-PER", "I-LOC"],
            },
        ),
        (
            "123",
            {"POS": [[123, "NUM"]], "tags": ["O"]},
        ),
        (
            "สมชาย",
            {"words": ["สมชาย"], "POS": [None], "tags": ["B-PER"]},
        ),
        (
            "สมชาย",
            {
                "words": ["สมชาย"],
                "POS": ["NR"],
                "tags": ["B-SYNTHETIC-PII-MARKER-DO-NOT-LOG"],
            },
        ),
    ],
)
def test_malformed_token_or_bio_stream_is_incomplete(monkeypatch, text, payload):
    monkeypatch.setattr(tner_client.httpx, "post", lambda *a, **k: _FakeResponse(payload))

    with pytest.raises(TnerIncompleteError):
        TnerEngine(api_key="k").tag(text)


def test_malformed_json_is_incomplete_not_transport_unavailable(monkeypatch):
    monkeypatch.setattr(
        tner_client.httpx,
        "post",
        lambda *a, **k: _MalformedJsonResponse(None),
    )

    with pytest.raises(TnerIncompleteError) as excinfo:
        TnerEngine(api_key="k").tag(SAMPLE)

    assert excinfo.value.code == "ner_incomplete"
    assert excinfo.value.count == 1
    assert "synthetic response body" not in str(excinfo.value)


@pytest.mark.parametrize(
    ("status", "category", "retryable"),
    [(401, "configuration", False), (503, "upstream", True)],
)
def test_http_status_classification_uses_locked_metadata(monkeypatch, status, category, retryable):
    request = tner_client.httpx.Request("POST", "https://provider.invalid/tner")
    response = tner_client.httpx.Response(status, request=request)
    monkeypatch.setattr(tner_client.httpx, "post", lambda *a, **k: response)

    with pytest.raises(TnerUnavailableError) as excinfo:
        TnerEngine(api_key="synthetic-key").tag(SAMPLE)

    assert excinfo.value.category == category
    assert excinfo.value.retryable is retryable


def test_direct_tner_error_traceback_drops_input_credential_and_provider_body(monkeypatch):
    credential = "synthetic-tner-credential"
    provider_body = "synthetic-tner-provider-body"

    class SecretResponse(_MalformedJsonResponse):
        def __init__(self):
            super().__init__(None)
            self.provider_body = provider_body

    monkeypatch.setattr(tner_client.httpx, "post", lambda *a, **k: SecretResponse())

    with pytest.raises(TnerIncompleteError) as excinfo:
        TnerEngine(api_key=credential).tag(SAMPLE)

    retained = repr(_product_traceback_locals(excinfo.value))
    assert SAMPLE not in retained
    assert credential not in retained
    assert provider_body not in retained
    assert excinfo.value.__cause__ is None
    assert excinfo.value.__context__ is None


def test_tner_errors_are_value_free_shared_ner_failures():
    error = TnerUnavailableError("upstream")
    incomplete = NERFailureError("ner_incomplete", category="upstream", count=0)

    assert isinstance(error, TnerServiceError)
    assert isinstance(error, NERFailureError)
    assert str(error) == "ner_unavailable"
    assert error.args == ("ner_unavailable",)
    assert incomplete.count == 1


def test_live_tner_label_vocabulary_maps_to_public_types():
    assert LABEL_MAP["PER"] == "NAME"
    assert LABEL_MAP["LOC"] == "LOCATION"
    assert LABEL_MAP["ORG"] == "ORGANIZATION"
    assert LABEL_MAP["DTM"] == "DATE"
