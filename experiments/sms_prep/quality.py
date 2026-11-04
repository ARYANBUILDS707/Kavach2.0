"""Data-quality, leakage and contamination report (aggregates only; never message text).

Everything here is a count, a share, a hash or a record ID. The report also states plainly what
grouped splitting does not fix: source and era confounding. The source-shortcut section only
assesses whether such a test is feasible with the available data; it trains nothing.
"""

import statistics
from collections import Counter, defaultdict

from dataset_governance.fingerprints import normalize_text, simulator_overlap, text_fingerprint
from sms_prep.cluster import near_duplicate_pairs, shingle_ids
from sms_prep.clusters import ClusterInfo
from sms_prep.normalize import (
    DATETIME_TOKEN,
    ENTITY,
    PHONE_TOKEN,
    URL_TOKEN,
    feature_normalize,
)
from sms_prep.records import Record
from sms_prep.splits import SPLITS, Assignment

MIN_CELL = 30  # fewer test records than this is reported as insufficient


def share(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


def dedup_section(records: list[Record], infos: list[ClusterInfo]) -> dict:
    by_dataset = defaultdict(list)
    for r in records:
        by_dataset[r.dataset].append(r)
    datasets = {}
    fingerprints = {}
    for name, rows in sorted(by_dataset.items()):
        texts = [r.text for r in rows]
        normalized = Counter(normalize_text(t) for t in texts)
        fingerprints[name] = set(normalized)
        datasets[name] = {
            "rows": len(rows),
            "unique_normalized_texts": len(normalized),
            "exact_duplicate_rows": sum(c - 1 for c in Counter(texts).values()),
            "normalized_duplicate_rows": sum(c - 1 for c in normalized.values()),
        }
    overlap = {}
    names = sorted(fingerprints)
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            overlap[f"{a} & {b}"] = len(fingerprints[a] & fingerprints[b])
    sizes = [len(i.record_ids) for i in infos]
    spanning = [i for i in infos if len(set(i.sources)) > 1 or (i.reference_members and i.sources)]
    return {
        "per_dataset": datasets,
        "shared_unique_texts_between_datasets": overlap,
        "clusters": {
            "total": len(infos),
            "largest": max(sizes) if sizes else 0,
            "singletons": sum(s == 1 for s in sizes),
            "spanning_sources_or_reference": len(spanning),
        },
    }


def label_section(infos: list[ClusterInfo]) -> dict:
    status = Counter(i.status for i in infos)
    return {
        "cluster_status": dict(status),
        "conflict_class_clusters": status.get("conflict_class", 0),
        "mixed_label_key_clusters": sum(i.label_key_mixed for i in infos),
        "eligible_clusters_by_stratum": dict(
            sorted(Counter(i.stratum for i in infos if i.status == "ok").items())
        ),
    }


def split_section(
    infos: list[ClusterInfo], cluster_split: dict[str, str], proportions: dict[str, float]
) -> dict:
    cells: dict[str, dict[str, dict[str, int]]] = defaultdict(
        lambda: {s: {"clusters": 0, "unique_texts": 0} for s in SPLITS}
    )
    for info in infos:
        split = cluster_split.get(info.cluster_id)
        if split:
            cells[info.stratum][split]["clusters"] += 1
            cells[info.stratum][split]["unique_texts"] += info.unique_texts
    strata = {}
    max_deviation = 0.0
    missing = []
    for stratum, by_split in sorted(cells.items()):
        total = sum(c["unique_texts"] for c in by_split.values())
        deviation = {
            s: round(by_split[s]["unique_texts"] / total - proportions[s], 4) for s in SPLITS
        }
        max_deviation = max(max_deviation, max(abs(d) for d in deviation.values()))
        empty = [s for s in SPLITS if by_split[s]["clusters"] == 0]
        if empty:
            missing.append({"stratum": stratum, "empty_splits": empty})
        strata[stratum] = {
            "unique_texts": total,
            "by_split": by_split,
            "deviation_from_target": deviation,
            "insufficient_test_cell": by_split["test"]["unique_texts"] < MIN_CELL,
        }
    totals = {s: {"clusters": 0, "unique_texts": 0} for s in SPLITS}
    for by_split in cells.values():
        for s in SPLITS:
            for k in ("clusters", "unique_texts"):
                totals[s][k] += by_split[s][k]
    return {
        "totals": totals,
        "strata": strata,
        "largest_stratum_deviation": round(max_deviation, 4),
        "strata_missing_from_a_split": missing,
    }


def contamination_section(
    records: list[Record], rows: list[Assignment], infos: list[ClusterInfo]
) -> dict:
    by_id = {r.record_id: r for r in records}
    split_of_cluster = defaultdict(set)
    for a in rows:
        split_of_cluster[a.cluster_id].add(a.split)
    text_splits = defaultdict(set)
    for a in rows:
        text_splits[text_fingerprint(by_id[a.record_id].text)].add(a.split)
    split_of_text = {fp: sorted(s)[0] for fp, s in text_splits.items()}
    normalized = sorted({normalize_text(by_id[a.record_id].text) for a in rows})
    fp_of = {n: text_fingerprint(n) for n in normalized}
    shingles = [shingle_ids(n) for n in normalized]
    crossing = {}
    for threshold in (0.8, 0.7, 0.6):
        pairs = near_duplicate_pairs(shingles, threshold)
        crossing[str(threshold)] = {
            "pairs": len(pairs),
            "pairs_across_splits": sum(
                split_of_text[fp_of[normalized[a]]] != split_of_text[fp_of[normalized[b]]]
                for a, b in pairs
            ),
        }
    assigned_texts = [by_id[a.record_id].text for a in rows]
    reference_clusters = {
        i.cluster_id for i in infos if i.reference_members and i.candidate_records
    }
    return {
        "clusters_spanning_more_than_one_split": sum(len(s) > 1 for s in split_of_cluster.values()),
        "texts_in_more_than_one_split": sum(len(s) > 1 for s in text_splits.values()),
        "unique_texts_checked": len(text_splits),
        "near_duplicate_pairs_by_threshold": crossing,
        "note_on_thresholds": (
            "Clusters are built at the Jaccard threshold recorded in the split metadata, so pairs "
            "at or above it never cross splits; pairs below it can, and are reported rather "
            "than hidden."
        ),
        "simulator_fixture_matches_in_splits": simulator_overlap(assigned_texts),
        "simulator_fixture_matches_in_all_records": simulator_overlap([r.text for r in records]),
        "assigned_records_in_clusters_with_mishra_reference": dict(
            Counter(a.split for a in rows if a.cluster_id in reference_clusters)
        ),
    }


def source_section(records: list[Record], rows: list[Assignment]) -> dict:
    by_id = {r.record_id: r for r in records}
    table: dict[str, Counter] = {s: Counter() for s in SPLITS}
    for a in rows:
        table[a.split][a.dataset] += 1
    concentration = {}
    for split, counts in table.items():
        total = sum(counts.values())
        concentration[split] = {d: share(c, total) for d, c in sorted(counts.items())}
    artifacts: dict[str, dict] = {}
    groups: dict[str, list[Record]] = defaultdict(list)
    for a in rows:
        groups[a.stratum].append(by_id[a.record_id])
    for stratum, rs in sorted(groups.items()):
        normalized = [feature_normalize(r.text) for r in rs]

        def fraction(flags: list[bool], total: int = len(rs)) -> float | None:
            return share(sum(flags), total)

        upper = [
            sum(c.isupper() for c in r.text) > 0.5 * max(1, sum(c.isalpha() for c in r.text))
            for r in rs
        ]
        artifacts[stratum] = {
            "records": len(rs),
            "median_chars": statistics.median(len(r.text) for r in rs),
            "share_with_url": fraction([URL_TOKEN in n for n in normalized]),
            "share_with_raw_entity_placeholder": fraction(
                [bool(ENTITY.search(r.text)) for r in rs]
            ),
            "share_with_phone_token": fraction([PHONE_TOKEN in n for n in normalized]),
            "share_with_datetime_token": fraction([DATETIME_TOKEN in n for n in normalized]),
            "share_non_ascii": fraction([any(ord(c) > 127 for c in r.text) for r in rs]),
            "share_mostly_uppercase": fraction(upper),
        }
    return {
        "records_by_split_and_dataset": {s: dict(c) for s, c in table.items()},
        "share_by_split_and_dataset": concentration,
        "descriptive_artifacts_by_stratum": artifacts,
    }


def shortcut_feasibility(infos: list[ClusterInfo], cluster_split: dict[str, str]) -> dict:
    """Which labels have two or more *collected* sources with enough held-out data to ask
    whether text alone reveals the source? Assessment only; nothing is trained."""
    cell: dict[str, dict[str, Counter]] = defaultdict(lambda: defaultdict(Counter))
    for info in infos:
        split = cluster_split.get(info.cluster_id)
        if split and info.origin == "collected":
            cell[info.provisional][info.source][split] += info.unique_texts
    verdicts = {}
    for label, by_source in sorted(cell.items()):
        usable = {
            s: dict(c) for s, c in by_source.items()
            if c["validation"] >= MIN_CELL and c["test"] >= MIN_CELL
        }  # fmt: skip
        verdicts[label] = {
            "sources": {s: dict(c) for s, c in sorted(by_source.items())},
            "feasible": len(usable) >= 2,
            "sources_with_enough_held_out_data": sorted(usable),
        }
    return {
        "minimum_cell": MIN_CELL,
        "by_provisional_label": verdicts,
        "conclusion": (
            "A within-label source probe is possible only where two collected sources share a "
            "label. In this data that is spam (UCI vs IMC). Benign comes from UCI alone (plus "
            "synthetic, which is not collected) and phishing candidates from IMC alone, so the "
            "decisive boundary cannot be probed: source and era are perfectly confounded with "
            "the label there. Grouped splitting does not change that."
        ),
    }


def cluster_threshold_sensitivity(records: list[Record], assign) -> dict:
    out = {}
    for threshold in (0.6, 0.7, 0.8):
        ids = assign(records, threshold)
        out[str(threshold)] = len(set(ids.values()))
    return {"cluster_count_by_threshold": out}
