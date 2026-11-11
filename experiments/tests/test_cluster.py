"""Clustering: the prefix-filter join must equal brute force, and cluster IDs must not depend
on input order."""

import random

import pytest
from helpers import gibberish

from sms_prep.cluster import UnionFind, cluster_texts, near_duplicate_pairs, shingle_ids


def planted_texts(seed: int = 5) -> list[str]:
    rng = random.Random(seed)
    base = [gibberish(rng, 80) for _ in range(60)]
    texts = list(base)
    for text in base[:20]:
        texts.append(text + " ok")  # near-duplicate
        texts.append(text[:-8] + "changed")  # near-duplicate
    for text in base[20:30]:
        texts.append(text[: len(text) // 2] + gibberish(rng, 40))  # borderline
    return texts


@pytest.mark.parametrize("threshold", [0.6, 0.7, 0.8, 0.9])
def test_prefix_filter_join_equals_brute_force(threshold: float) -> None:
    sets = [shingle_ids(t) for t in planted_texts()]
    brute = sorted(
        (i, j)
        for i in range(len(sets))
        for j in range(i + 1, len(sets))
        if len(sets[i] & sets[j]) / len(sets[i] | sets[j]) >= threshold
    )
    assert near_duplicate_pairs(sets, threshold) == brute
    assert brute  # the fixture really contains near-duplicates


def test_cluster_ids_do_not_depend_on_input_order() -> None:
    texts = planted_texts()
    shuffled = texts[:]
    random.Random(1).shuffle(shuffled)
    first = dict(zip(texts, cluster_texts(texts).cluster_ids, strict=True))
    second = dict(zip(shuffled, cluster_texts(shuffled).cluster_ids, strict=True))
    assert first == second


def test_exact_and_near_duplicates_share_a_cluster_and_unrelated_texts_do_not() -> None:
    rng = random.Random(9)
    a, b = gibberish(rng, 90), gibberish(rng, 90)
    result = cluster_texts([a, a, a + " ok", b, shouted(a)])
    ids = result.cluster_ids
    assert ids[0] == ids[1] == ids[2] == ids[4] and ids[3] != ids[0]
    assert result.unique_texts == 3


def shouted(text: str) -> str:  # same text after matching normalization
    return text.upper() + "  "


def test_threshold_is_monotonic() -> None:
    texts = planted_texts()
    counts = [len(set(cluster_texts(texts, t).cluster_ids)) for t in (0.6, 0.7, 0.8, 0.9)]
    assert counts == sorted(counts)


def test_group_keys_join_unrelated_texts() -> None:
    rng = random.Random(2)
    texts = [gibberish(rng, 80) for _ in range(6)]
    plain = cluster_texts(texts).cluster_ids
    assert len(set(plain)) == 6
    grouped = cluster_texts(texts, group_keys=["t1", "t1", "t2", "t2", None, "t1"]).cluster_ids
    assert grouped[0] == grouped[1] == grouped[5]
    assert grouped[2] == grouped[3] and grouped[0] != grouped[2] and grouped[4] not in grouped[:4]


def test_empty_and_tiny_inputs_are_safe() -> None:
    assert cluster_texts([]).cluster_ids == []
    result = cluster_texts(["", "a", "a"])
    assert result.cluster_ids[1] == result.cluster_ids[2]


def test_union_find_keeps_the_smallest_root() -> None:
    groups = UnionFind(5)
    groups.union(3, 1)
    groups.union(4, 3)
    assert {groups.find(i) for i in (1, 3, 4)} == {1}
