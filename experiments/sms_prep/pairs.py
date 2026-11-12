"""Cross-split near-duplicate review and a no-write dry run of stricter grouping (M4.2 review).

The frozen split groups texts at Jaccard 0.7. Pairs between 0.6 and 0.7 can still cross splits;
this module measures them without exposing held-out text:

- reports are aggregates (counts, quartiles, class names); no message text, ever;
- the only readable output is `masked_sample`, which draws exclusively from the train and
  validation splits, masks digits and truncates, and refuses the test split by construction;
- `recluster_dry_run` shows what a stricter threshold would change, and writes nothing. Creating
  a new split version is a separate, explicit decision.

Similarity measures are descriptive. A hand check showed they separate templated campaign
variants from generic wording only weakly, so none is used as a classifier here.
"""

import difflib
import random
import re
from collections import Counter, defaultdict
from dataclasses import dataclass

from dataset_governance.fingerprints import normalize_text
from sms_prep.cluster import near_duplicate_pairs, shingle_ids
from sms_prep.clusters import assign_clusters, build_cluster_infos
from sms_prep.records import Record
from sms_prep.splits import SPLITS, Assignment, assign_splits, record_assignments

READABLE_SPLITS = ("train", "validation")  # the test split is never shown
SIMILARITY_BANDS = ((0.0, 0.70), (0.70, 0.80), (0.80, 0.90), (0.90, 1.01))
MASKED_CHARS = 150
LEAKAGE_LEVELS = (0.4, 0.5, 0.6, 0.7)  # similarity levels reported in the leakage profile


@dataclass(frozen=True)
class UniqueText:
    text: str  # normalized (matching form); never reported
    record_id: str  # representative record
    split: str
    stratum: str
    dataset: str


@dataclass(frozen=True)
class Pair:
    a: int
    b: int
    jaccard: float
    word_trigram: float
    sequence_ratio: float
    length_ratio: float


def unique_texts(records: list[Record], rows: list[Assignment]) -> list[UniqueText]:
    """One entry per normalized text of the assigned records (a text has one split)."""
    by_id = {r.record_id: r for r in records}
    found: dict[str, UniqueText] = {}
    for a in rows:
        text = normalize_text(by_id[a.record_id].text)
        current = found.get(text)
        if current is None or a.record_id < current.record_id:
            found[text] = UniqueText(text, a.record_id, a.split, a.stratum, a.dataset)
    return [found[t] for t in sorted(found)]


def word_trigrams(text: str) -> frozenset[tuple[str, ...]]:
    words = text.split()
    if len(words) < 3:
        return frozenset([tuple(words)])
    return frozenset(zip(words, words[1:], words[2:], strict=False))


def describe(items: list[UniqueText], a: int, b: int, jaccard: float) -> Pair:
    ta, tb = items[a].text, items[b].text
    wa, wb = word_trigrams(ta), word_trigrams(tb)
    return Pair(
        a, b, jaccard,
        len(wa & wb) / max(1, len(wa | wb)),
        difflib.SequenceMatcher(None, ta, tb, autojunk=False).ratio(),
        min(len(ta), len(tb)) / max(1, max(len(ta), len(tb))),
    )  # fmt: skip


def cross_split_pairs(items: list[UniqueText], threshold: float) -> tuple[list[Pair], int]:
    """Pairs at or above `threshold` whose texts sit in different splits, and the total."""
    sets = [shingle_ids(i.text) for i in items]
    pairs = near_duplicate_pairs(sets, threshold)
    crossing = []
    for a, b in pairs:
        if items[a].split != items[b].split:
            jaccard = len(sets[a] & sets[b]) / len(sets[a] | sets[b])
            crossing.append(describe(items, a, b, jaccard))
    return crossing, len(pairs)


def quartiles(values: list[float]) -> list[float]:
    ordered = sorted(values)
    if not ordered:
        return []
    return [round(ordered[int(p * (len(ordered) - 1))], 3) for p in (0, 0.25, 0.5, 0.75, 1)]


def summarize(items: list[UniqueText], pairs: list[Pair], total_pairs: int) -> dict:
    """Aggregate view of cross-split pairs: no text, no record IDs."""
    touched: dict[str, set[int]] = defaultdict(set)
    for p in pairs:
        for index in (p.a, p.b):
            touched[items[index].split].add(index)
    per_split = Counter(i.split for i in items)
    test_by_stratum = Counter(i.stratum for i in items if i.split == "test")
    test_touched = Counter(items[i].stratum for i in touched["test"])
    return {
        "pairs_at_threshold": total_pairs,
        "pairs_across_splits": len(pairs),
        "by_split_pair": dict(
            Counter("/".join(sorted((items[p.a].split, items[p.b].split))) for p in pairs)
        ),  # fmt: skip
        "within_one_stratum": sum(items[p.a].stratum == items[p.b].stratum for p in pairs),
        "across_strata": sum(items[p.a].stratum != items[p.b].stratum for p in pairs),
        "by_dataset_pair": dict(
            Counter("/".join(sorted((items[p.a].dataset, items[p.b].dataset))) for p in pairs)
        ),  # fmt: skip
        "by_stratum_pair": dict(
            Counter(
                "/".join(sorted((items[p.a].stratum, items[p.b].stratum))) for p in pairs
            ).most_common(12)
        ),  # fmt: skip
        "similarity_quartiles_min_q1_median_q3_max": {
            "char_5gram_jaccard": quartiles([p.jaccard for p in pairs]),
            "word_trigram_jaccard": quartiles([p.word_trigram for p in pairs]),
            "sequence_ratio": quartiles([p.sequence_ratio for p in pairs]),
            "length_ratio": quartiles([p.length_ratio for p in pairs]),
        },
        "test_texts_in_a_cross_split_pair": {
            "count": len(touched["test"]),
            "of": per_split["test"],
            "share": round(len(touched["test"]) / max(1, per_split["test"]), 4),
            "by_stratum": {
                s: {"count": test_touched[s], "of": n, "share": round(test_touched[s] / n, 4)}
                for s, n in sorted(test_by_stratum.items())
            },
        },
    }


def leakage_profile(
    items: list[UniqueText], crossing: list[Pair], levels: tuple[float, ...] = LEAKAGE_LEVELS
) -> dict:
    """How much of each split has a close neighbour in another split, by similarity level.

    `crossing` must hold the cross-split pairs at the lowest level. For every validation and test
    text the best similarity to any *train* text is taken; the shares are label-free and need no
    model. They also size the "novel campaign" slice (texts with no neighbour at a level).
    """
    best: dict[int, float] = {}
    for p in crossing:
        for mine, other in ((p.a, p.b), (p.b, p.a)):
            if items[mine].split in ("validation", "test") and items[other].split == "train":
                best[mine] = max(best.get(mine, 0.0), p.jaccard)
    profile: dict = {"cross_split_pairs_at_least": {}}
    for level in levels:
        profile["cross_split_pairs_at_least"][str(level)] = sum(
            p.jaccard >= level for p in crossing
        )
    for split in ("validation", "test"):
        indexes = [i for i, item in enumerate(items) if item.split == split]
        banking = [i for i in indexes if items[i].stratum == "imc:banking"]
        profile[f"{split}_texts"] = len(indexes)
        profile[f"{split}_texts_with_a_train_neighbour_at_least"] = {
            str(level): round(
                sum(best.get(i, 0.0) >= level for i in indexes) / max(1, len(indexes)), 4
            )
            for level in levels
        }
        profile[f"{split}_banking_texts_with_a_train_neighbour_at_least"] = {
            str(level): round(
                sum(best.get(i, 0.0) >= level for i in banking) / max(1, len(banking)), 4
            )
            for level in levels
        }
    return profile


def masked(text: str) -> str:
    return re.sub(r"\d", "#", text.replace("\n", " "))[:MASKED_CHARS]


def masked_sample(
    records: list[Record], items: list[UniqueText], pairs: list[Pair], seed: int, per_band: int
) -> list[dict]:
    """Readable pairs for a hand check: train/validation only, masked, truncated, no metrics."""
    by_id = {r.record_id: r for r in records}
    pool = [
        p for p in pairs
        if items[p.a].split in READABLE_SPLITS and items[p.b].split in READABLE_SPLITS
    ]  # fmt: skip
    rng = random.Random(seed)
    chosen = []
    for low, high in SIMILARITY_BANDS:
        band = [p for p in pool if low <= p.sequence_ratio < high]
        chosen += rng.sample(band, min(per_band, len(band)))
    rng.shuffle(chosen)
    return [
        {"pair": n, "a": masked(by_id[items[p.a].record_id].text),
         "b": masked(by_id[items[p.b].record_id].text)}
        for n, p in enumerate(chosen, 1)
    ]  # fmt: skip


def jaccard_band_sample(
    records: list[Record],
    items: list[UniqueText],
    pairs: list[Pair],
    band: tuple[float, float],
    seed: int,
    size: int,
) -> list[dict]:
    """Readable pairs whose character-Jaccard lies in `band` (train/validation only, masked).

    `pairs` must come from `cross_split_pairs` at or below the band's lower edge.
    """
    by_id = {r.record_id: r for r in records}
    pool = [
        p for p in pairs
        if band[0] <= p.jaccard < band[1]
        and items[p.a].split in READABLE_SPLITS and items[p.b].split in READABLE_SPLITS
    ]  # fmt: skip
    chosen = random.Random(seed).sample(pool, min(size, len(pool)))
    return [
        {"pair": n, "a": masked(by_id[items[p.a].record_id].text),
         "b": masked(by_id[items[p.b].record_id].text)}
        for n, p in enumerate(chosen, 1)
    ]  # fmt: skip


def recluster_dry_run(
    records: list[Record], v1_rows: list[Assignment], threshold: float, seed: int
) -> dict:
    """What clustering at `threshold` would change relative to the frozen split. Writes nothing."""
    assignment = assign_clusters(records, threshold)
    infos = build_cluster_infos(records, assignment)
    cluster_split = assign_splits(infos, seed)
    rows = record_assignments(records, infos, cluster_split)
    old = {r.record_id: r.split for r in v1_rows}
    new = {r.record_id: r.split for r in rows}
    common = sorted(set(old) & set(new))
    moved = Counter(f"{old[i]}->{new[i]}" for i in common if old[i] != new[i])
    sizes = Counter(assignment.values())
    weight: dict[str, dict[str, int]] = defaultdict(lambda: dict.fromkeys(SPLITS, 0))
    for info in infos:
        split = cluster_split.get(info.cluster_id)
        if split:
            weight[info.stratum][split] += info.unique_texts
    deviation = max(
        abs(w[s] / sum(w.values()) - p)
        for w in weight.values() for s, p in (("train", 0.70), ("validation", 0.15), ("test", 0.15))
    )  # fmt: skip
    items = unique_texts(records, rows)
    low, low_total = cross_split_pairs(items, min(LEAKAGE_LEVELS))
    profile = leakage_profile(items, low)
    return {
        "threshold": threshold,
        "clusters": len(set(assignment.values())),
        "largest_cluster_records": max(sizes.values()),
        "assigned_records": len(rows),
        "records_in_both_versions": len(common),
        "records_that_change_split": sum(moved.values()),
        "share_of_records_that_change_split": round(sum(moved.values()) / max(1, len(common)), 4),
        "changes_by_direction": dict(moved),
        "v1_test_records_that_leave_test": moved.get("test->train", 0)
        + moved.get("test->validation", 0),
        "v1_test_records_total": sum(1 for s in old.values() if s == "test"),
        "largest_stratum_deviation": round(deviation, 4),
        "pairs_at_lowest_level": low_total,
        "leakage_profile": profile,
    }
