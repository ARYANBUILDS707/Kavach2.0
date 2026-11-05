"""Local CPU inference for a verified pretrained candidate.

Loading rules:
- the files must verify against the pinned record first, with no stray file beside them;
- `config.json` must not name custom code (`auto_map`) and its label map must equal the pinned
  one, both checked before torch or transformers is imported;
- transformers runs offline (no Hub calls, no telemetry), `trust_remote_code=False`,
  `use_safetensors=True`, from the local directory only.

If any rule fails, the classifier is unavailable and every prediction carries null scores, never
a zero. Scores are the model's softmax outputs: uncalibrated, and not a KAVACH-validated
probability of phishing.
"""

import json
import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from pretrained.candidates import Candidate
from pretrained.fetch import DEFAULT_MODEL_ROOT, model_dir, verify

MAX_INPUT_CHARS = 2000  # bounded input; longer SMS bodies are cut before tokenizing
OFFLINE_ENV = {
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "HF_HUB_DISABLE_TELEMETRY": "1",
    "TOKENIZERS_PARALLELISM": "false",
}


class ModelUnavailable(Exception):
    """The model cannot be used; the reason is safe to show (no text, no paths)."""


class Classifier(Protocol):
    labels: tuple[str, ...]

    def probabilities(self, texts: Sequence[str]) -> list[list[float]]: ...


@dataclass(frozen=True)
class Prediction:
    status: Literal["ok", "unavailable"]
    label: str | None
    fraud_score: float | None  # sum of the candidate's fraud-label probabilities
    unwanted_score: float | None  # fraud + spam
    probabilities: dict[str, float] | None
    reason: str | None = None


def check_config(candidate: Candidate, directory: Path) -> None:
    try:
        config = json.loads((directory / "config.json").read_text())
    except (OSError, ValueError):
        raise ModelUnavailable("config.json is missing or unreadable") from None
    if "auto_map" in config or config.get("trust_remote_code"):
        raise ModelUnavailable("config.json asks for custom code; refused")
    id2label = config.get("id2label") or {}
    found = tuple(id2label.get(str(i)) for i in range(len(id2label)))
    if found != candidate.labels:
        raise ModelUnavailable("config.json label map differs from the pinned record")


def prepare_input(text: str) -> str:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Each message must be non-empty text")
    return text[:MAX_INPUT_CHARS]


class TransformersClassifier:
    """The real model. Heavy imports happen here only, after every check has passed."""

    def __init__(self, candidate: Candidate, directory: Path) -> None:
        os.environ.update(OFFLINE_ENV)
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        self._torch = torch
        self.labels = candidate.labels
        self.max_tokens = candidate.max_tokens
        self.tokenizer = AutoTokenizer.from_pretrained(
            directory, local_files_only=True, trust_remote_code=False
        )
        self.model = AutoModelForSequenceClassification.from_pretrained(
            directory,
            local_files_only=True,
            trust_remote_code=False,
            use_safetensors=True,
            dtype=torch.float32,
        )
        self.model.eval()
        loaded = tuple(self.model.config.id2label[i] for i in range(len(self.labels)))
        if loaded != self.labels:
            raise ModelUnavailable("loaded label map differs from the pinned record")

    def probabilities(self, texts: Sequence[str]) -> list[list[float]]:
        batch = self.tokenizer(
            list(texts),
            truncation=True,
            max_length=self.max_tokens,
            padding=True,
            return_tensors="pt",
        )
        with self._torch.inference_mode():
            logits = self.model(**batch).logits
        return self._torch.softmax(logits, dim=-1).tolist()


def load_classifier(candidate: Candidate, root: Path = DEFAULT_MODEL_ROOT) -> Classifier:
    directory = model_dir(candidate, root)
    problems = verify(candidate, root)
    if problems:
        raise ModelUnavailable(f"model files do not verify ({len(problems)} problem(s))")
    check_config(candidate, directory)
    try:
        return TransformersClassifier(candidate, directory)
    except ModelUnavailable:
        raise
    except Exception as error:  # a load failure is "unavailable", reported by type only
        raise ModelUnavailable(f"model failed to load ({type(error).__name__})") from None


def unavailable(reason: str) -> Prediction:
    return Prediction("unavailable", None, None, None, None, reason)


def predict(
    classifier: Classifier | None,
    candidate: Candidate,
    texts: Sequence[str],
    unavailable_reason: str = "model unavailable",
) -> list[Prediction]:
    if classifier is None:
        return [unavailable(unavailable_reason) for _ in texts]
    prepared = [prepare_input(t) for t in texts]
    rows = classifier.probabilities(prepared)
    if len(rows) != len(prepared) or any(len(r) != len(candidate.labels) for r in rows):
        raise ModelUnavailable("the model returned an unexpected output shape")
    results = []
    for row in rows:
        probs = dict(zip(candidate.labels, row, strict=True))
        fraud = sum(probs[label] for label in candidate.fraud_labels)
        spam = sum(probs[label] for label in candidate.spam_labels)
        results.append(
            Prediction(
                "ok",
                max(probs, key=probs.__getitem__),
                round(fraud, 6),
                round(fraud + spam, 6),
                {k: round(v, 6) for k, v in probs.items()},
            )
        )
    return results
