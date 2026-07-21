"""Client for the AI for Thai TNER service (opt-in NER engine).

Wire shape per the published `aift` SDK: POST to `/tner` with an `Apikey`
header and the text as a form field, answering with a `POS` list of
`[word, pos_tag]` pairs and a parallel `tags` list of BIO labels. It is
translated here into PyThaiNLP's `(word, tag)` shape so `_bio_to_spans` can
decode it unchanged.

NOT VERIFIED AGAINST THE LIVE SERVICE. The shape above comes from the SDK, not
from a call — no API key exists on the development machine. Every deviation
from it raises `TnerServiceError` rather than returning a partial result,
because the failure mode that matters here is silent: an unrecognised payload
decoded as "no entities found" is indistinguishable from a clean document on a
service whose entire purpose is not missing PII.

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
            # A short tag list would silently drop the tail of the document.
            raise TnerServiceError(f"TNER returned {len(pos)} words but {len(tags)} tags")

        words: list[str] = []
        for item in pos:
            if isinstance(item, (list, tuple)) and item:
                words.append(str(item[0]))
            elif isinstance(item, str):
                words.append(item)
            else:
                raise TnerServiceError(f"unexpected TNER POS entry: {type(item).__name__}")

        return [(word, str(tag)) for word, tag in zip(words, tags)]
