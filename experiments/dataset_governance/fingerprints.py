"""Text normalization and fingerprints for duplicate, contamination and fixture checks.

Normalization is deliberately aggressive: two messages that differ only in case, digits, URLs,
punctuation or Unicode form count as the same text. It is for matching only; the training
pipeline's feature preprocessing is a separate, documented step (docs/M4_EVALUATION_PLAN.md).
"""

import hashlib
import re
import unicodedata
from collections.abc import Iterable

URL = re.compile(r"https?://\S+|www\.\S+|<url>", re.IGNORECASE)
DIGITS = re.compile(r"\d+")
NON_WORD = re.compile(r"\W+")
SHINGLE_SIZE = 5
NEAR_DUPLICATE_JACCARD = 0.8


def normalize_text(text: str) -> str:
    """NFKC, lower-case, URLs -> `<url>` (placeholders included), digit runs -> `0`."""
    text = unicodedata.normalize("NFKC", text).lower()
    text = URL.sub(" url ", text)
    text = DIGITS.sub("0", text)
    return NON_WORD.sub(" ", text).strip()


def text_fingerprint(text: str) -> str:
    return hashlib.sha256(normalize_text(text).encode()).hexdigest()


def shingles(normalized: str, size: int = SHINGLE_SIZE) -> frozenset[str]:
    padded = f" {normalized} "
    return frozenset(padded[i : i + size] for i in range(max(1, len(padded) - size + 1)))


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    return len(a & b) / len(a | b) if a | b else 1.0


def simulator_fingerprints() -> frozenset[str]:
    """Fingerprints of every SMS text in the packaged simulator catalog (S01-S12).

    Those texts are demonstration fixtures. They must never appear in training, validation
    or held-out data (docs/DATASET_GOVERNANCE.md), so the dataset pipeline checks against this.
    """
    from kavach.simulator.catalog import ConflictStep, SubmitStep, load_catalog

    fingerprints = set()
    for scenario in load_catalog().scenarios:
        for step in scenario.steps:
            if isinstance(step, SubmitStep | ConflictStep) and step.text is not None:
                fingerprints.add(text_fingerprint(step.text))
    return frozenset(fingerprints)


def simulator_overlap(texts: Iterable[str]) -> int:
    """How many of `texts` equal a simulator fixture after normalization (must be 0)."""
    fixtures = simulator_fingerprints()
    return sum(text_fingerprint(text) in fixtures for text in texts)
