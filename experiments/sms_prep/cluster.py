"""Exact and near-duplicate clustering with deterministic cluster IDs.

Texts are compared after `normalize_text`. Near duplicates are found with the prefix-filtering
set-similarity join (AllPairs): exact for Jaccard >= threshold over character 5-gram sets, and
fast because only the rarest few shingles of each text are indexed. Everything is deterministic:
shingles are hashed with CRC-32 (not Python's salted hash), ties break on stable keys, and a
cluster's ID is derived from the smallest member fingerprint, not from input order.
"""

import hashlib
import math
import zlib
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from dataset_governance.fingerprints import NEAR_DUPLICATE_JACCARD, SHINGLE_SIZE, normalize_text


def shingle_ids(normalized: str, size: int = SHINGLE_SIZE) -> frozenset[int]:
    padded = f" {normalized} "
    return frozenset(
        zlib.crc32(padded[i : i + size].encode()) for i in range(max(1, len(padded) - size + 1))
    )


def near_duplicate_pairs(
    shingle_sets: Sequence[frozenset[int]], threshold: float = NEAR_DUPLICATE_JACCARD
) -> list[tuple[int, int]]:
    """Index pairs (i < j) whose Jaccard similarity is at least `threshold`."""
    document_frequency = Counter(token for s in shingle_sets for token in s)
    ordered = [sorted(s, key=lambda t: (document_frequency[t], t)) for s in shingle_sets]
    by_size = sorted(range(len(shingle_sets)), key=lambda i: (len(ordered[i]), i))
    index: dict[int, list[int]] = defaultdict(list)
    pairs = []
    for x in by_size:
        size_x = len(ordered[x])
        if size_x == 0:
            continue
        minimum = math.ceil(threshold * size_x)
        prefix = size_x - minimum + 1
        candidates = set()
        for token in ordered[x][:prefix]:
            for y in index[token]:
                if len(ordered[y]) >= minimum:
                    candidates.add(y)
            index[token].append(x)
        for y in candidates:
            overlap = len(shingle_sets[x] & shingle_sets[y])
            if overlap / (size_x + len(shingle_sets[y]) - overlap) >= threshold:
                pairs.append((min(x, y), max(x, y)))
    return sorted(pairs)


class UnionFind:
    def __init__(self, size: int) -> None:
        self.parent = list(range(size))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


@dataclass(frozen=True)
class TextClusters:
    """Cluster assignment per input text (same order as the input)."""

    cluster_ids: list[str]
    unique_texts: int
    near_duplicate_pairs: int


def cluster_texts(
    texts: Iterable[str],
    threshold: float = NEAR_DUPLICATE_JACCARD,
    group_keys: Sequence[str | None] | None = None,
) -> TextClusters:
    """Cluster texts. Texts that share a `group_keys` entry (for example a template family)
    are always joined, whatever their similarity."""
    texts = list(texts)
    normalized = [normalize_text(t) for t in texts]
    unique = sorted(set(normalized))
    position = {n: i for i, n in enumerate(unique)}
    pairs = near_duplicate_pairs([shingle_ids(n) for n in unique], threshold)
    groups = UnionFind(len(unique))
    for a, b in pairs:
        groups.union(a, b)
    if group_keys is not None:
        first_in_group: dict[str, int] = {}
        for n, key in zip(normalized, group_keys, strict=True):
            if key is not None:
                groups.union(first_in_group.setdefault(key, position[n]), position[n])
    fingerprint = {n: hashlib.sha256(n.encode()).hexdigest() for n in unique}
    smallest: dict[int, str] = {}
    for n in unique:
        root = groups.find(position[n])
        smallest[root] = min(smallest.get(root, fingerprint[n]), fingerprint[n])
    ids = {
        n: "c" + hashlib.sha256(smallest[groups.find(position[n])].encode()).hexdigest()[:16]
        for n in unique
    }
    return TextClusters([ids[n] for n in normalized], len(unique), len(pairs))
