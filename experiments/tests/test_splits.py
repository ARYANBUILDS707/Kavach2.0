"""Leakage-safe splitting: deterministic, group-atomic, stratified, and guarded."""

import json
import random
from datetime import UTC, datetime

import pytest
from helpers import fixture_clusters, gibberish, record

from dataset_governance.fingerprints import normalize_text
from sms_prep.cluster import near_duplicate_pairs, shingle_ids
from sms_prep.clusters import assign_clusters, build_cluster_infos
from sms_prep.splits import (
    DEFAULT_PROPORTIONS,
    FINAL_EVALUATION,
    SPLITS,
    HeldOutGuard,
    assign_splits,
    eligible,
    read_assignments,
    record_assignments,
    write_assignments,
)


def test_only_ok_clusters_with_a_usable_label_are_split() -> None:
    _, _, infos = fixture_clusters()
    split = assign_splits(infos)
    assert split and all((i.cluster_id in split) == eligible(i) for i in infos)


def test_reference_only_clusters_are_never_split() -> None:
    rng = random.Random(8)
    records = [
        record("mishra_soni_2022", "mishra", 0, "ham", gibberish(rng, 80), role="reference",
               provisional="benign"),
        record("uci_sms_spam_collection", "uci", 0, "ham", gibberish(rng, 80)),
    ]  # fmt: skip
    infos = build_cluster_infos(records, assign_clusters(records, 0.7))
    (lone,) = [i for i in infos if i.status == "reference_only"]
    assert lone.candidate_records == 0 and lone.cluster_id not in assign_splits(infos)


def test_conflicting_labels_in_one_cluster_are_excluded() -> None:
    rng = random.Random(4)
    shared = gibberish(rng, 80)
    records = [
        record("uci_sms_spam_collection", "uci", 0, "ham", shared),
        record("imc25_smishing_reports", "imc", 0, "spam", shared, provisional="spam"),
        record("uci_sms_spam_collection", "uci", 1, "ham", gibberish(rng, 80)),
    ]
    infos = build_cluster_infos(records, assign_clusters(records, 0.7))
    conflict = [i for i in infos if i.status == "conflict_class"]
    assert len(conflict) == 1 and not eligible(conflict[0])
    assert conflict[0].cluster_id not in assign_splits(infos)


def test_assignment_is_deterministic_and_independent_of_input_order() -> None:
    _, _, infos = fixture_clusters()
    first = assign_splits(infos, seed=11)
    shuffled = infos[:]
    random.Random(3).shuffle(shuffled)
    assert assign_splits(shuffled, seed=11) == first
    assert assign_splits(infos, seed=12) != first


def test_every_record_of_a_cluster_shares_one_split_and_reference_records_are_never_split() -> None:
    records, _, infos = fixture_clusters()
    cluster_split = assign_splits(infos)
    rows = record_assignments(records, infos, cluster_split)
    by_cluster: dict[str, set[str]] = {}
    for row in rows:
        by_cluster.setdefault(row.cluster_id, set()).add(row.split)
    assert all(len(s) == 1 for s in by_cluster.values())
    reference = {r.record_id for r in records if r.role == "reference"}
    assert reference and not reference & {row.record_id for row in rows}


def test_strata_keep_the_target_proportions() -> None:
    _, _, infos = fixture_clusters()
    cluster_split = assign_splits(infos)
    weight: dict[str, dict[str, int]] = {}
    for info in infos:
        if info.cluster_id in cluster_split:
            weight.setdefault(info.stratum, dict.fromkeys(SPLITS, 0))[
                cluster_split[info.cluster_id]
            ] += info.unique_texts
    for stratum in ("imc:banking", "uci:ham", "imc:delivery"):
        total = sum(weight[stratum].values())
        for split in SPLITS:
            assert abs(weight[stratum][split] / total - DEFAULT_PROPORTIONS[split]) < 0.06, stratum


def test_synthetic_template_families_never_cross_splits() -> None:
    records, _, infos = fixture_clusters()
    rows = record_assignments(records, infos, assign_splits(infos))
    by_record = {r.record_id: r for r in records}
    templates: dict[str, set[str]] = {}
    for row in rows:
        if row.origin == "synthetic":
            templates.setdefault(by_record[row.record_id].group, set()).add(row.split)
    assert templates and all(len(s) == 1 for s in templates.values())
    assert {row.origin for row in rows} == {"collected", "synthetic"}


def test_no_near_duplicate_pair_crosses_splits_at_the_clustering_threshold() -> None:
    records, _, infos = fixture_clusters()
    rows = record_assignments(records, infos, assign_splits(infos))
    by_id = {r.record_id: r for r in records}
    split_of_text = {}
    for row in rows:
        split_of_text.setdefault(normalize_text(by_id[row.record_id].text), set()).add(row.split)
    texts = sorted(split_of_text)
    assert all(len(s) == 1 for s in split_of_text.values())
    for a, b in near_duplicate_pairs([shingle_ids(t) for t in texts], 0.7):
        assert split_of_text[texts[a]] == split_of_text[texts[b]]


def test_invalid_proportions_are_rejected() -> None:
    _, _, infos = fixture_clusters()
    for bad in ({"train": 0.5, "validation": 0.2, "test": 0.2}, {"train": 1.0}):
        with pytest.raises(ValueError):
            assign_splits(infos, proportions=bad)


# --- the held-out guard ---------------------------------------------------------------------


@pytest.fixture
def guard(tmp_path):
    records, _, infos = fixture_clusters()
    rows = record_assignments(records, infos, assign_splits(infos))
    path = tmp_path / "assignments.jsonl"
    sha = write_assignments(path, rows)
    clock = lambda: datetime(2026, 11, 5, 12, 0, tzinfo=UTC)  # noqa: E731
    return HeldOutGuard(path, sha, tmp_path / "test_access.log", clock), rows, tmp_path


def test_training_and_tuning_cannot_read_the_test_split(guard) -> None:
    g, rows, _ = guard
    for purpose in ("training", "tuning", "validation", "threshold_selection", "anything"):
        with pytest.raises(PermissionError):
            g.record_ids("test", purpose, model_version="m1")
    with pytest.raises(PermissionError):
        g.record_ids("train", "tuning")
    with pytest.raises(PermissionError):
        g.record_ids("validation", FINAL_EVALUATION)
    assert set(g.record_ids("train", "training")) == {
        r.record_id for r in rows if r.split == "train"
    }
    assert g.record_ids("validation", "tuning")


def test_a_final_evaluation_needs_a_model_version_and_is_logged_without_text(guard) -> None:
    g, rows, tmp = guard
    with pytest.raises(PermissionError, match="model version"):
        g.record_ids("test", FINAL_EVALUATION)
    ids = g.record_ids("test", FINAL_EVALUATION, model_version="baseline-1")
    assert len(ids) == sum(r.split == "test" for r in rows)
    (entry,) = [json.loads(x) for x in (tmp / "test_access.log").read_text().splitlines()]
    assert entry["purpose"] == FINAL_EVALUATION and entry["model_version"] == "baseline-1"
    assert entry["records"] == len(ids) and set(entry) == {
        "at",
        "purpose",
        "model_version",
        "split_sha256",
        "records",
    }


def test_a_modified_split_file_is_refused(tmp_path) -> None:
    records, _, infos = fixture_clusters()
    rows = record_assignments(records, infos, assign_splits(infos))
    path = tmp_path / "a.jsonl"
    sha = write_assignments(path, rows)
    path.write_text(path.read_text().replace('"test"', '"train"', 1))
    with pytest.raises(PermissionError, match="differs from the frozen split metadata"):
        HeldOutGuard(path, sha, tmp_path / "log")


def test_assignment_files_round_trip(tmp_path) -> None:
    records, _, infos = fixture_clusters()
    rows = record_assignments(records, infos, assign_splits(infos))
    path = tmp_path / "a.jsonl"
    sha = write_assignments(path, rows)
    assert read_assignments(path) == rows and write_assignments(path, rows) == sha
