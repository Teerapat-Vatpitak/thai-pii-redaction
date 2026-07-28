"""Adapter for a locally fine-tuned token-classification NER model.

Unlike the PyThaiNLP engines, this adapter returns CHARACTER-OFFSET spans
directly from the fast tokenizer's offset mapping — it does not fake the
word/BIO ``.tag()`` tuple stream, whose reconstruction via ``text.find``
was built for PyThaiNLP tokenizers, not subword models.

The model lives OUTSIDE the repository (weights are never committed) and is
selected explicitly via ``AIGUARD_FINETUNED_MODEL_DIR``. Long inputs are
handled with a token-window stride inside the adapter, because a 500-char
product chunk plus margins can exceed the model's window — training length
alone does not make truncation safe.

Label space (see training/): PERSON, LOCATION, ORGANIZATION, DATE,
STUDENT_ID in BIO. Structured identifiers stay owned by the regex/checksum
FP layer; ADDRESS/DATE_OF_BIRTH refinement stays with the cue-upgrade layer.
"""

from __future__ import annotations

import os

_WINDOW_TOKENS = 240
_STRIDE_TOKENS = 60


class FinetunedEngineUnavailableError(RuntimeError):
    pass


class FinetunedEngine:
    """Char-span NER over a fine-tuned HF token-classification model."""

    def __init__(self, model_dir: str | None = None) -> None:
        model_dir = model_dir or os.environ.get("AIGUARD_FINETUNED_MODEL_DIR")
        if not model_dir or not os.path.isdir(model_dir):
            raise FinetunedEngineUnavailableError(
                "AIGUARD_FINETUNED_MODEL_DIR must point at a trained model directory"
            )
        try:
            import torch  # noqa: F401
            from transformers import AutoModelForTokenClassification, AutoTokenizer
        except ImportError as exc:
            raise FinetunedEngineUnavailableError(
                "the finetuned engine needs requirements-ml.txt installed"
            ) from exc
        self._tok = AutoTokenizer.from_pretrained(model_dir)
        if not getattr(self._tok, "is_fast", False):
            raise FinetunedEngineUnavailableError(
                "the finetuned engine requires a fast tokenizer (offset mappings)"
            )
        self._model = AutoModelForTokenClassification.from_pretrained(model_dir)
        self._model.eval()
        self._id2label = {int(k): v for k, v in self._model.config.id2label.items()}

    def spans(self, text: str) -> list[tuple[int, int, str, float]]:
        """(start, end, LABEL, confidence) spans over the raw text."""
        import numpy as np
        import torch

        if not text or not text.strip():
            return []
        enc = self._tok(text, return_offsets_mapping=True, add_special_tokens=False)
        ids = enc["input_ids"]
        offsets = enc["offset_mapping"]
        if not ids:
            return []

        # token-window stride; overlapping windows vote by max confidence
        best_prob: dict[int, float] = {}
        best_label: dict[int, str] = {}
        start_tok = 0
        while start_tok < len(ids):
            window = ids[start_tok : start_tok + _WINDOW_TOKENS]
            with torch.no_grad():
                logits = self._model(
                    input_ids=torch.tensor([window]),
                    attention_mask=torch.ones(1, len(window), dtype=torch.long),
                ).logits[0]
            probs = torch.softmax(logits, dim=-1).numpy()
            for i in range(len(window)):
                tok_idx = start_tok + i
                lab_id = int(np.argmax(probs[i]))
                p = float(probs[i][lab_id])
                if p > best_prob.get(tok_idx, 0.0):
                    best_prob[tok_idx] = p
                    best_label[tok_idx] = self._id2label[lab_id]
            if start_tok + _WINDOW_TOKENS >= len(ids):
                break
            start_tok += _WINDOW_TOKENS - _STRIDE_TOKENS

        # merge BIO runs into char spans
        out: list[tuple[int, int, str, float]] = []
        cur_label = None
        cur_start = cur_end = 0
        cur_probs: list[float] = []

        def _flush():
            nonlocal cur_label
            if cur_label is not None and cur_end > cur_start:
                out.append((cur_start, cur_end, cur_label, sum(cur_probs) / max(1, len(cur_probs))))
            cur_label = None

        for tok_idx in range(len(ids)):
            lab = best_label.get(tok_idx, "O")
            o_start, o_end = offsets[tok_idx]
            if o_end <= o_start:
                continue
            if lab == "O":
                _flush()
                continue
            prefix, _, etype = lab.partition("-")
            if cur_label == etype and prefix == "I":
                cur_end = o_end
                cur_probs.append(best_prob.get(tok_idx, 0.0))
            else:
                _flush()
                cur_label = etype
                cur_start, cur_end = o_start, o_end
                cur_probs = [best_prob.get(tok_idx, 0.0)]
        _flush()
        return out
