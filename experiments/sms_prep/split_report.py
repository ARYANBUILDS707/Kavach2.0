"""Distribution, coverage, giant-cluster and leakage report for a split version, plus the
acceptance checks a proposed split must pass before it may be adopted.

The checks are fixed here, before any result is seen, and use only label-free text statistics
and the provisional labels. No model, no score and no test-set performance enters them, so
choosing or accepting a split cannot tune anything to the held-out data.
"""

from collections import Counter, defaultdict

from dataset_governance.fingerprints import simulator_overlap
from sms_prep.clusters import ClusterInfo
from sms_prep.pairs import UniqueText, leakage_profile
from sms_prep.records import Record
from sms_prep.splits import DEFAULT_PROPORTIONS, SPLITS, Assignment

SIZE_BUCKETS = ((1, 1), (2, 4), (5, 19), (20, 99), (100, 999), (1000, 10**9))
GIANT_SHARE = 0.15  # a cluster bigger than the test share of its stratum cannot be spread
MIN_TEST_CELL = 30
SMALL_STRATA = ("imc:hey mum/dad",)  # known too small for a usable test cell (54 unique texts)

# Acceptance thresholds, fixed in advance.
MAX_STRATUM_DEVIATION = 0.02
MAX_RECORD_LOSS_VS_PREVIOUS = 0.03
MAX_GIANT_SHARE_OF_STRATUM = DEFAULT_PROPORTIONS["train"]


def share(part: float, whole: float) -> float | None:
    return round(part / whole, 4) if whole else None


def size_distribution(infos: list[ClusterInfo]) -> list[dict]:
    eligible = [i for i in infos if i.candidate_records]
    total = sum(i.candidate_records for i in eligible)
    rows = []
    for low, high in SIZE_BUCKETS:
        members = [i for i in eligible if low <= i.candidate_records <= high]
        label = str(low) if low == high else f"{low}-{high}" if high < 10**9 else f"{low}+"
        rows.append({
            "records_per_cluster": label,
            "clusters": len(members),
            "share_of_records": share(sum(i.candidate_records for i in members), total),
        })  # fmt: skip
    return rows


def stratum_totals(infos: list[ClusterInfo], cluster_split: dict[str, str]) -> dict[str, dict]:
    totals: dict[str, dict] = defaultdict(lambda: {"unique_texts": 0, "records": 0})
    for info in infos:
        if info.cluster_id in cluster_split:
            totals[info.stratum]["unique_texts"] += info.unique_texts
            totals[info.stratum]["records"] += info.candidate_records
    return totals


def largest_clusters(
    infos: list[ClusterInfo], cluster_split: dict[str, str], top: int = 10
) -> list[dict]:
    totals = stratum_totals(infos, cluster_split)
    ranked = sorted(
        (i for i in infos if i.cluster_id in cluster_split),
        key=lambda i: (-i.candidate_records, i.cluster_id),
    )
    return [
        {
            "rank": n,
            "stratum": i.stratum,
            "records": i.candidate_records,
            "unique_texts": i.unique_texts,
            "share_of_stratum_records": share(i.candidate_records, totals[i.stratum]["records"]),
            "share_of_stratum_unique_texts": share(
                i.unique_texts, totals[i.stratum]["unique_texts"]
            ),
            "split": cluster_split[i.cluster_id],
            "label_keys_mixed": i.label_key_mixed,
        }
        for n, i in enumerate(ranked[:top], 1)
    ]


def giant_clusters(infos: list[ClusterInfo], cluster_split: dict[str, str]) -> list[dict]:
    """Clusters holding more of their stratum than the test share: they decide which campaigns
    a split can contain."""
    totals = stratum_totals(infos, cluster_split)
    giants = []
    for i in infos:
        if i.cluster_id not in cluster_split:
            continue
        portion = i.unique_texts / max(1, totals[i.stratum]["unique_texts"])
        if portion >= GIANT_SHARE:
            giants.append({
                "stratum": i.stratum,
                "records": i.candidate_records,
                "unique_texts": i.unique_texts,
                "share_of_stratum_unique_texts": round(portion, 4),
                "share_of_stratum_records": share(
                    i.candidate_records, totals[i.stratum]["records"]
                ),
                "split": cluster_split[i.cluster_id],
            })  # fmt: skip
    return sorted(giants, key=lambda g: -g["share_of_stratum_unique_texts"])


def distribution(rows: list[Assignment], records: list[Record], infos, cluster_split) -> dict:
    by_id = {r.record_id: r for r in records}
    strata: dict[str, dict[str, dict[str, int]]] = defaultdict(
        lambda: {s: {"records": 0, "unique_texts": 0, "clusters": 0} for s in SPLITS}
    )
    for info in infos:
        split = cluster_split.get(info.cluster_id)
        if split:
            strata[info.stratum][split]["unique_texts"] += info.unique_texts
            strata[info.stratum][split]["clusters"] += 1
    for row in rows:
        strata[row.stratum][row.split]["records"] += 1
    label = {s: Counter() for s in SPLITS}
    source = {s: Counter() for s in SPLITS}
    for row in rows:
        record = by_id[row.record_id]
        label[row.split][record.provisional] += 1
        source[row.split][record.source] += 1
    table = {}
    max_dev = 0.0
    for stratum, cells in sorted(strata.items()):
        total = sum(c["unique_texts"] for c in cells.values())
        deviation = {
            s: round(cells[s]["unique_texts"] / total - DEFAULT_PROPORTIONS[s], 4) for s in SPLITS
        }
        max_dev = max(max_dev, *(abs(d) for d in deviation.values()))
        table[stratum] = {
            "by_split": cells,
            "deviation_from_target": deviation,
            "test_cell_below_minimum": cells["test"]["unique_texts"] < MIN_TEST_CELL,
            "missing_from": [s for s in SPLITS if cells[s]["clusters"] == 0],
        }

    def shares(counter_by_split: dict[str, Counter]) -> dict:
        return {
            s: {k: share(v, sum(c.values())) for k, v in sorted(c.items())}
            for s, c in counter_by_split.items()
        }

    return {
        "strata": table,
        "largest_stratum_deviation": round(max_dev, 4),
        "provisional_label_share_by_split": shares(label),
        "source_share_by_split": shares(source),
        "records_by_split": {s: sum(label[s].values()) for s in SPLITS},
    }


def contamination(rows: list[Assignment], records: list[Record]) -> dict:
    by_id = {r.record_id: r for r in records}
    from dataset_governance.fingerprints import text_fingerprint

    cluster_splits, text_splits = defaultdict(set), defaultdict(set)
    templates = defaultdict(set)
    for row in rows:
        record = by_id[row.record_id]
        cluster_splits[row.cluster_id].add(row.split)
        text_splits[text_fingerprint(record.text)].add(row.split)
        if record.origin == "synthetic":
            templates[record.group].add(row.split)
    return {
        "clusters_in_more_than_one_split": sum(len(s) > 1 for s in cluster_splits.values()),
        "texts_in_more_than_one_split": sum(len(s) > 1 for s in text_splits.values()),
        "synthetic_template_families_in_more_than_one_split": sum(
            len(s) > 1 for s in templates.values()
        ),
        "simulator_fixture_matches": simulator_overlap([by_id[r.record_id].text for r in rows]),
    }


def compare(previous: list[Assignment], current: list[Assignment]) -> dict:
    old = {r.record_id: r.split for r in previous}
    new = {r.record_id: r.split for r in current}
    common = set(old) & set(new)
    moved = Counter(f"{old[i]}->{new[i]}" for i in common if old[i] != new[i])
    return {
        "previous_assigned_records": len(old),
        "assigned_records": len(new),
        "records_lost_vs_previous": len(set(old) - set(new)),
        "share_lost_vs_previous": share(len(set(old) - set(new)), len(old)),
        "records_that_change_split": sum(moved.values()),
        "share_that_change_split": share(sum(moved.values()), len(common)),
        "changes_by_direction": dict(sorted(moved.items())),
    }


def checks(
    dist: dict, contam: dict, leak: dict, comparison: dict, giants: list[dict], threshold: float
) -> list[dict]:
    """The fixed acceptance checks. A proposed split is adoptable only if every check passes."""
    strata = dist["strata"]
    usable = {s: v for s, v in strata.items() if s not in SMALL_STRATA}
    giant_max = max((g["share_of_stratum_unique_texts"] for g in giants), default=0.0)
    split_clusters = contam["clusters_in_more_than_one_split"]
    split_texts = contam["texts_in_more_than_one_split"]
    crossing = leak["cross_split_pairs_at_least"][str(threshold)]
    families = contam["synthetic_template_families_in_more_than_one_split"]
    fixtures = contam["simulator_fixture_matches"]
    missing = [
        f"{s} missing from {v['missing_from']}" for s, v in strata.items() if v["missing_from"]
    ]
    small = [s for s, v in usable.items() if v["test_cell_below_minimum"]]
    deviation = dist["largest_stratum_deviation"]
    lost, lost_share = comparison["records_lost_vs_previous"], comparison["share_lost_vs_previous"]
    exempt = ", ".join(SMALL_STRATA)
    results = [
        ("no cluster or text in more than one split", split_clusters == 0 and split_texts == 0,
         f"{split_clusters} clusters, {split_texts} texts"),
        (f"no cross-split pair at Jaccard >= {threshold}", crossing == 0, f"{crossing} pairs"),
        ("synthetic template families stay whole", families == 0, f"{families} families split"),
        ("no simulator fixture text", fixtures == 0, f"{fixtures} matches"),
        ("every stratum is present in every split", not missing,
         ", ".join(missing) or "all present"),
        (f"test cells hold at least {MIN_TEST_CELL} unique texts (except {exempt})", not small,
         ", ".join(small) or "all large enough"),
        (f"largest stratum deviation from 70/15/15 <= {MAX_STRATUM_DEVIATION}",
         deviation <= MAX_STRATUM_DEVIATION, str(deviation)),
        (f"records lost to label conflicts <= {MAX_RECORD_LOSS_VS_PREVIOUS:.0%} of the prior split",
         (lost_share or 0) <= MAX_RECORD_LOSS_VS_PREVIOUS, f"{lost} records ({lost_share})"),
        (f"no cluster exceeds the train share ({MAX_GIANT_SHARE_OF_STRATUM:.0%}) of its stratum",
         giant_max <= MAX_GIANT_SHARE_OF_STRATUM, f"largest share {giant_max}"),
    ]  # fmt: skip
    return [{"check": c, "passed": bool(p), "detail": d} for c, p, d in results]


def build_report(
    records: list[Record],
    infos: list[ClusterInfo],
    cluster_split: dict[str, str],
    rows: list[Assignment],
    previous_rows: list[Assignment],
    items: list[UniqueText],
    crossing_lowest,
    levels: tuple[float, ...],
    threshold: float,
) -> dict:
    dist = distribution(rows, records, infos, cluster_split)
    contam = contamination(rows, records)
    leak = leakage_profile(items, crossing_lowest, levels)
    comparison = compare(previous_rows, rows)
    giants = giant_clusters(infos, cluster_split)
    results = checks(dist, contam, leak, comparison, giants, threshold)
    eligible = [i for i in infos if i.cluster_id in cluster_split]
    return {
        "clusters": {
            "total": len(infos),
            "assigned": len(eligible),
            "excluded_label_conflict": sum(i.status == "conflict_class" for i in infos),
            "reference_only": sum(i.status == "reference_only" for i in infos),
            "size_distribution": size_distribution(infos),
            "largest": largest_clusters(infos, cluster_split),
            "giants": giants,
        },
        "distribution": dist,
        "contamination": contam,
        "leakage_profile": leak,
        "comparison_with_previous_version": comparison,
        "checks": results,
        "all_checks_passed": all(r["passed"] for r in results),
    }
