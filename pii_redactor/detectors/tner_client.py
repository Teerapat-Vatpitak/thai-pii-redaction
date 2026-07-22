"""Client for the AI for Thai TNER service (opt-in NER engine).

Wire shape verified against the live service: POST to `/tner` with an `Apikey`
header and the text as a form field, answering with three parallel lists:
`words`, `POS`, and `tags`. Older versions of the published `aift` SDK exposed
`POS` as `[word, pos_tag]` pairs, so the decoder accepts that legacy shape too.
Both are translated into PyThaiNLP's `(word, tag)` shape so `_bio_to_spans` can
decode them unchanged.

Verified against the live service on 2026-07-22. The live BIO vocabulary uses
compact labels such as PER, LOC, ORG, and DTM; `tb_detector.LABEL_MAP`
translates those labels into AI Guard's public types. Every payload-shape
deviation raises `TnerServiceError` rather than
returning a partial result, because an unrecognised response decoded as "no
entities found" is indistinguishable from a clean document.

This engine sends text to a third party, so it is opt-in only
(`AIGUARD_NER_ENGINE=tner`) and never the default — the offline claim the
proposal makes holds precisely because of that.
"""

from __future__ import annotations

import httpx

_DEFAULT_URL = "https://api.aiforthai.in.th/tner"
_DEFAULT_TIMEOUT = 15.0
# The SDK stamps this so the platform can attribute traffic; harmless, and
# sending it keeps us indistinguishable from a normal SDK client.
_CLIENT_LIB = "aiguard-python"


class TnerServiceError(RuntimeError):
    """The TNER engine could not produce a usable tagging.

    Deliberately one type for credentials, transport and payload problems: the
    caller's decision is the same in all three cases (this engine is unusable
    right now), and the message carries the distinction for a human.
    """


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
            raise TnerServiceError(
                "AI for Thai TNER needs an API key; set AIFORTHAI_API_KEY. "
                "Get one at https://aiforthai.in.th/"
            )
        self._api_key = api_key
        self._url = url
        self._timeout = timeout

    def tag(self, text: str) -> list[tuple[str, str]]:
        """Return [(word, BIO tag), ...] for `text`, or raise TnerServiceError."""
        if not text or not text.strip():
            return []

        try:
            response = httpx.post(
                self._url,
                headers={"Apikey": self._api_key, "X-lib": _CLIENT_LIB},
                data={"text": text},
                timeout=self._timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except TnerServiceError:
            raise
        except Exception as exc:  # transport, HTTP status, malformed JSON
            raise TnerServiceError(f"TNER request failed: {exc}") from exc

        return self._decode(payload)

    @staticmethod
    def _decode(payload: object) -> list[tuple[str, str]]:
        if not isinstance(payload, dict) or "POS" not in payload or "tags" not in payload:
            raise TnerServiceError(
                f"unexpected TNER payload shape: {sorted(payload)[:5] if isinstance(payload, dict) else type(payload).__name__}"
            )

        pos = payload["POS"]
        tags = payload["tags"]
        if not isinstance(pos, list) or not isinstance(tags, list):
            raise TnerServiceError("TNER payload fields POS/tags must both be lists")
        if len(pos) != len(tags):
            # Any unequal parallel field indicates a truncated response.
            raise TnerServiceError(f"TNER returned {len(pos)} POS tags but {len(tags)} BIO tags")

        words_field = payload.get("words")
        words: list[str] = []
        if words_field is not None:
            if not isinstance(words_field, list):
                raise TnerServiceError("TNER payload field words must be a list")
            if len(words_field) != len(tags):
                raise TnerServiceError(
                    f"TNER returned {len(words_field)} words but {len(tags)} BIO tags"
                )
            for item in words_field:
                if not isinstance(item, str):
                    raise TnerServiceError(f"unexpected TNER words entry: {type(item).__name__}")
                words.append(item)
        else:
            # Backward compatibility with the published SDK's older POS-pair
            # representation. A bare POS string such as "NR" is never a word.
            for item in pos:
                if isinstance(item, (list, tuple)) and item:
                    words.append(str(item[0]))
                else:
                    raise TnerServiceError(
                        "TNER payload has no words list and POS entries are not word/POS pairs"
                    )

        return [(word, str(tag)) for word, tag in zip(words, tags)]
