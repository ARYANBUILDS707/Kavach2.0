"""Cross-split pair review: aggregate-only reports, a readable sample that can never contain
test text, a label-free leakage profile, and a dry run that writes nothing."""

import json
import random

from helpers import fixture_clusters, fixture_records, gibberish, record

from sms_prep import pairs as P
from sms_prep.clusters import assign_clusters, build_cluster_infos
from sms_prep.splits import Assignment, assign_splits, record_assignments


def planted():
    """Records where near-duplicates were deliberately put in different splits."""
    rng = random.Random(3)
    bases = [gibberish(rng, 90) for _ in range(6)]
    records, rows = [], []
    layout = [("train", "test"), ("train", "validation"), ("validation", "test"),
              ("train", "train"), ("train", "test"), ("validation", "validation")]  # fmt: skip
    n = 0
    for base, (first, second) in zip(bases, layout, strict=True):
        for text, split in ((base, first), (base + " ok", second)):
            rec = record("imc25_smishing_reports", "imc", n, "banking", f"{text} 12345")
            records.append(rec)
            rows.append(
                Assignment(rec.record_id, f"c{n}", split, "imc:banking", rec.dataset, "collected")
            )
            n += 1
    for _ in range(10):  # unrelated filler in every split
        for split in ("train", "validation", "test"):
            rec = record("uci_sms_spam_collection", "uci", n, "ham", gibberish(rng, 90))
            records.append(rec)
            rows.append(
                Assignment(rec.record_id, f"c{n}", split, "uci:ham", rec.dataset, "collected")
            )
            n += 1
    return records, rows


def test_cross_split_pairs_are_found_and_counted_without_text() -> None:
    records, rows = planted()
    items = P.unique_texts(records, rows)
    crossing, total = P.cross_split_pairs(items, 0.6)
    assert total == 6 and len(crossing) == 4  # two pairs sit inside one split
    summary = P.summarize(items, crossing, total)
    assert summary["by_split_pair"] == {
        "test/train": 2,
        "train/validation": 1,
        "test/validation": 1,
    }
    assert summary["within_one_stratum"] == 4 and summary["across_strata"] == 0
    blob = json.dumps(summary)
    assert not any(r.text[:20] in blob for r in records) and "record_id" not in blob
    exposure = summary["test_texts_in_a_cross_split_pair"]
    assert (
        exposure["count"] == 3
        and exposure["of"] == 13
        and exposure["by_stratum"]["imc:banking"]["count"] == 3
    )


def test_the_readable_sample_never_contains_a_test_text_and_masks_digits() -> None:
    records, rows = planted()
    items = P.unique_texts(records, rows)
    crossing, _ = P.cross_split_pairs(items, 0.6)
    sample = P.masked_sample(records, items, crossing, seed=1, per_band=10)
    assert len(sample) == 1  # only the train/validation pair is readable
    shown = json.dumps(sample)
    test_texts = [r.text for r, a in zip(records, rows, strict=True) if a.split == "test"]
    assert not any(t[:30] in shown for t in test_texts)
    assert "12345" not in shown and "#####" in shown
    assert all(
        len(v) <= P.MASKED_CHARS for entry in sample for k, v in entry.items() if k != "pair"
    )


def test_the_sampler_is_deterministic_and_respects_the_band_size() -> None:
    records, rows = planted()
    items = P.unique_texts(records, rows)
    crossing, _ = P.cross_split_pairs(items, 0.6)
    assert P.masked_sample(records, items, crossing, 7, 3) == P.masked_sample(
        records, items, crossing, 7, 3
    )
    assert P.masked_sample(records, items, crossing, 7, 0) == []


def test_the_band_sampler_is_banded_readable_only_and_deterministic() -> None:
    records, rows = planted()
    items = P.unique_texts(records, rows)
    crossing, _ = P.cross_split_pairs(items, 0.4)
    first = P.jaccard_band_sample(records, items, crossing, (0.4, 1.01), seed=2, size=10)
    assert first == P.jaccard_band_sample(records, items, crossing, (0.4, 1.01), seed=2, size=10)
    assert len(first) == 1  # the only train/validation pair
    assert P.jaccard_band_sample(records, items, crossing, (0.4, 0.5), seed=2, size=10) == []
    test_texts = [r.text for r, a in zip(records, rows, strict=True) if a.split == "test"]
    assert not any(t[:30] in json.dumps(first) for t in test_texts)


def test_the_leakage_profile_is_label_free_and_levelled() -> None:
    records, rows = planted()
    items = P.unique_texts(records, rows)
    crossing, _ = P.cross_split_pairs(items, 0.4)
    profile = P.leakage_profile(items, crossing)
    assert profile["test_texts"] == 13
    at_least = profile["test_texts_with_a_train_neighbour_at_least"]
    assert at_least["0.4"] >= at_least["0.5"] >= at_least["0.6"] >= at_least["0.7"]
    assert at_least["0.7"] == round(2 / 13, 4)  # the two train/test pairs are near-identical
    assert profile["cross_split_pairs_at_least"]["0.4"] == len(crossing)
    assert "label" not in json.dumps(profile)


def test_the_dry_run_changes_nothing_on_disk_and_reports_the_difference(
    tmp_path, monkeypatch
) -> None:
    records, _, infos = fixture_clusters()
    v1 = record_assignments(records, infos, assign_splits(infos, seed=21))
    monkeypatch.chdir(tmp_path)
    before = sorted(p.name for p in tmp_path.rglob("*"))
    result = P.recluster_dry_run(records, v1, 0.5, seed=21)
    assert sorted(p.name for p in tmp_path.rglob("*")) == before == []
    assert result["threshold"] == 0.5 and result["clusters"] <= len(
        set(assign_clusters(records, 0.7).values())
    )
    assert result["records_in_both_versions"] > 0
    assert 0.0 <= result["share_of_records_that_change_split"] <= 1.0
    assert result["leakage_profile"]["cross_split_pairs_at_least"]["0.5"] == 0
    assert not any(r.text[:20] in json.dumps(result) for r in records)


def test_a_stricter_threshold_never_leaves_more_cross_split_pairs() -> None:
    records = fixture_records()
    infos = build_cluster_infos(records, assign_clusters(records, 0.7))
    v1 = record_assignments(records, infos, assign_splits(infos, seed=21))
    loose = P.recluster_dry_run(records, v1, 0.7, seed=21)["leakage_profile"][
        "cross_split_pairs_at_least"
    ]
    strict = P.recluster_dry_run(records, v1, 0.4, seed=21)["leakage_profile"][
        "cross_split_pairs_at_least"
    ]
    assert all(strict[k] <= loose[k] for k in loose)
    assert strict["0.4"] == 0
