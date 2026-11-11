"""The real model: imported only after the manifest and every artifact have verified.

Loads with `local_files_only=True`, `trust_remote_code=False` and `use_safetensors=True`, offline,
on CPU, once per process. Returns the model's softmax over the manifest labels, uncalibrated.
"""

import math
from importlib import metadata
from pathlib import Path
from typing import Protocol

from kavach_sms_worker.manifest import Manifest


class ModelLoadError(Exception):
    """Loading failed; the message is a fixed code, never library text."""


class Classifier(Protocol):
    def classify(self, text: str) -> tuple[list[float], bool]:
        """(probabilities in manifest label order, whether the input was truncated)."""
        ...


def runtime_mismatches(manifest: Manifest) -> list[str]:
    """Installed package versions that differ from the manifest's approved runtime."""
    problems = []
    for package, expected in sorted(manifest.packages.items()):
        try:
            installed = metadata.version(package)
        except metadata.PackageNotFoundError:
            problems.append(f"{package}: not installed")
            continue
        if installed != expected:
            problems.append(f"{package}: version differs")
    return problems


class TransformersClassifier:
    def __init__(self, manifest: Manifest, directory: Path, threads: int) -> None:
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        torch.set_num_threads(threads)
        self._torch = torch
        self.max_tokens = manifest.max_tokens
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
        self.model.to("cpu")
        self.model.eval()
        loaded = tuple(self.model.config.id2label[i] for i in range(len(manifest.labels)))
        if loaded != manifest.labels:
            raise ModelLoadError("label_map_mismatch")
        self.label_count = len(manifest.labels)

    def classify(self, text: str) -> tuple[list[float], bool]:
        full_length = len(self.tokenizer(text, truncation=False)["input_ids"])
        batch = self.tokenizer(
            text, truncation=True, max_length=self.max_tokens, return_tensors="pt"
        )
        with self._torch.inference_mode():
            logits = self.model(**batch).logits
        probabilities = self._torch.softmax(logits, dim=-1)[0].tolist()
        del batch, logits
        if len(probabilities) != self.label_count or not all(
            math.isfinite(p) for p in probabilities
        ):
            raise ModelLoadError("invalid_output")
        return probabilities, full_length > self.max_tokens


def load_classifier(manifest: Manifest, directory: Path, threads: int) -> Classifier:
    try:
        return TransformersClassifier(manifest, directory, threads)
    except ModelLoadError:
        raise
    except Exception:  # any library failure is reported by a fixed code only
        raise ModelLoadError("model_load_failed") from None
