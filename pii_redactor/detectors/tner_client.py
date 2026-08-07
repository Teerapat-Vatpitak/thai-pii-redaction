"""Client for the AI for Thai TNER service (opt-in NER engine).

Wire shape verified against the live service: POST to `/tner` with an `Apikey`
header and the text as a form field, answering with three parallel lists:
`words`, `POS`, and `tags`. Older versions of the published `aift` SDK exposed
`POS` as `[word, pos_tag]` pairs, so the decoder accepts that legacy shape too.
Both are translated into PyThaiNLP's `(word, tag)` shape so `_bio_to_spans` can
decode them unchanged.

Verified against the live service on 2026-07-22. The live BIO vocabulary uses
compact labels such as PER, LOC, ORG, and DTM; `tb_detector.LABEL_MAP`
translates those labels into AI Guard's public types. Every failed request or
incomplete token stream raises a value-free `TnerServiceError` subtype rather
than returning a partial result, because a truncated response decoded as "no
entities found" is indistinguishable from a clean document.

This engine sends text to a third party, so it is opt-in only
(`AIGUARD_NER_ENGINE=tner`) and never the default — the offline claim the
proposal makes holds precisely because of that.
"""

from __future__ import annotations

import httpx

from pii_redactor.detectors.ner_failure import NERFailureError, ner_failure_metadata
from pii_redactor.safe_errors import discard_exception_graph

_DEFAULT_URL = "https://api.aiforthai.in.th/tner"
_DEFAULT_TIMEOUT = 15.0
# The SDK stamps this so the platform can attribute traffic; harmless, and
# sending it keeps us indistinguishable from a normal SDK client.
_CLIENT_LIB = "aiguard-python"
# TNER uses the Thai LST20 labels. Long-form aliases remain accepted for the
# older published SDK shape already supported by this adapter. Anything else
# is a response-contract change and must fail closed.
_TNER_LABELS = frozenset(
    {
        "BRN",
        "DES",
        "DTM",
        "LOC",
        "MEA",
        "NUM",
        "ORG",
        "PER",
        "TRM",
        "TTL",
        "DATE",
        "FACILITY",
        "GPE",
        "LOCATION",
        "MONEY",
        "ORGANIZATION",
        "PERCENT",
        "PERSON",
        "PRODUCT",
        "TIME",
    }
)


class TnerServiceError(NERFailureError):
    """Base class for a value-free TNER tagging failure."""


class TnerUnavailableError(TnerServiceError):
    """TNER could not be called because its dependency or service is unavailable."""

    def __init__(self, category: str, *, count: int = 1) -> None:
        super().__init__("ner_unavailable", category=category, count=count)


class TnerIncompleteError(TnerServiceError):
    """TNER returned a response that cannot cover the requested chunk."""

    def __init__(self, *, count: int = 1) -> None:
        super().__init__("ner_incomplete", category="upstream", count=count)


class TnerEngine:
    """Minimal stand-in for `pythainlp.tag.NamedEntityTagger` backed by TNER."""

    def __init__(
        self,
        api_key: str,
        *,
        url: str = _DEFAULT_URL,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        if not api_key:
            raise TnerUnavailableError("configuration", count=0)
        self._api_key = api_key
        self._url = url
        self._timeout = timeout

    def tag(self, text: str) -> list[tuple[str, str]]:
        """Return [(word, BIO tag), ...] for `text`, or raise TnerServiceError."""
        if not text or not text.strip():
            return []

        failure: tuple[str, str, int] | None = None
        try:
            return self._tag_impl(text)
        except NERFailureError as error:
            failure = ner_failure_metadata(error)
            discard_exception_graph(error)
        except Exception as error:
            discard_exception_graph(error)
            failure = ("ner_unavailable", "dependency", 1)

        text = ""
        code, category, count = failure
        failure = None
        self = None
        if code == "ner_incomplete":
            raise TnerIncompleteError(count=count) from None
        raise TnerUnavailableError(category, count=count) from None

    def _tag_impl(self, text: str) -> list[tuple[str, str]]:
        try:
            response = httpx.post(
                self._url,
                headers={"Apikey": self._api_key, "X-lib": _CLIENT_LIB},
                data={"text": text},
                timeout=self._timeout,
            )
        except httpx.TransportError as error:
            discard_exception_graph(error)
            raise TnerUnavailableError("network") from None
        except Exception as error:
            discard_exception_graph(error)
            raise TnerUnavailableError("dependency") from None

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            status = error.response.status_code
            category = "configuration" if status in {401, 403} else "upstream"
            discard_exception_graph(error)
            raise TnerUnavailableError(category) from None
        except Exception as error:
            discard_exception_graph(error)
            raise TnerUnavailableError("dependency") from None

        try:
            payload = response.json()
        except Exception as error:
            discard_exception_graph(error)
            raise TnerIncompleteError() from None

        try:
            tagged = self._decode(payload)
            self._validate_alignment(tagged, text)
            return tagged
        except TnerServiceError:
            raise
        except Exception as error:
            discard_exception_graph(error)
            raise TnerIncompleteError() from None

    @staticmethod
    def _decode(payload: object) -> list[tuple[str, str]]:
        if not isinstance(payload, dict) or "POS" not in payload or "tags" not in payload:
            raise TnerIncompleteError()

        pos = payload["POS"]
        tags = payload["tags"]
        if not isinstance(pos, list) or not isinstance(tags, list):
            raise TnerIncompleteError()
        if len(pos) != len(tags):
            # Any unequal parallel field indicates a truncated response.
            raise TnerIncompleteError()
        if any(not isinstance(tag, str) for tag in tags):
            raise TnerIncompleteError()

        words_field = payload.get("words")
        words: list[str] = []
        if words_field is not None:
            if not isinstance(words_field, list):
                raise TnerIncompleteError()
            if len(words_field) != len(tags):
                raise TnerIncompleteError()
            if any(not isinstance(item, str) for item in pos):
                raise TnerIncompleteError()
            for item in words_field:
                if not isinstance(item, str):
                    raise TnerIncompleteError()
                words.append(item)
        else:
            # Backward compatibility with the published SDK's older POS-pair
            # representation. A bare POS string such as "NR" is never a word.
            for item in pos:
                if (
                    not isinstance(item, (list, tuple))
                    or len(item) < 2
                    or not isinstance(item[0], str)
                    or not isinstance(item[1], str)
                ):
                    raise TnerIncompleteError()
                words.append(item[0])

        return list(zip(words, tags))

    @staticmethod
    def _validate_alignment(tagged: list[tuple[str, str]], text: str) -> None:
        """Require complete source coverage and one legal BIO stream."""

        position = 0
        active_label: str | None = None
        for word, tag in tagged:
            if not word:
                raise TnerIncompleteError()
            index = text.find(word, position)
            if index < 0 or text[position:index].strip():
                raise TnerIncompleteError()
            position = index + len(word)

            if not word.strip():
                if not tag.strip():
                    continue
                if tag == "O":
                    active_label = None
                    continue
                raise TnerIncompleteError()

            if tag == "O":
                active_label = None
                continue
            if tag.startswith("B-"):
                label = tag[2:]
                if label not in _TNER_LABELS:
                    raise TnerIncompleteError()
                active_label = label
                continue
            if tag.startswith("I-"):
                label = tag[2:]
                if label not in _TNER_LABELS or active_label != label:
                    raise TnerIncompleteError()
                continue
            raise TnerIncompleteError()

        if text[position:].strip():
            raise TnerIncompleteError()
