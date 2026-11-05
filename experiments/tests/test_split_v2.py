"""Split v2: created beside v1 without touching it, deterministic, checked by fixed acceptance
rules, and read through the same held-out guard."""

import hashlib
import json
from pathlib import Path

import pytest
from helpers import fixture_records

from sms_prep import cli, split_report
from sms_prep.clusters import assign_clusters, build_cluster_infos, write_clusters
from sms_prep.records import write_records
from sms_prep.split_versions import VERSIONS
from sms_prep.splits import (
    FINAL_EVALUATION,
    HeldOutGuard,
    assign_splits,
    record_assignments,
    write_assignments,
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def v1_store(tmp_path):
    """A small data directory holding a v1 split exactly as `build` lays it out."""
    data, meta_dir, reports = tmp_path / "data", tmp_path / "manifests", tmp_path / "reports"
    records = fixture_records()
    work = data / "work"
    records_sha = write_records(work / "records.jsonl", records)
    infos = build_cluster_infos(records, assign_clusters(records, VERSIONS[1].threshold))
    write_clusters(work / "clusters.jsonl", infos)
    rows = record_assignments(records, infos, assign_splits(infos))
    assignments_sha = write_assignments(work / "assignments.jsonl", rows)
    meta_dir.mkdir()
    (meta_dir / VERSIONS[1].meta_name).write_text(json.dumps({
        "split_version": 1, "assignments_sha256": assignments_sha,
        "inputs": {"records_sha256": records_sha}, "manifest": {"version": 2, "sha256": "0" * 64},
    }))  # fmt: skip
    args = ["--data-dir", str(data), "--meta-dir", str(meta_dir), "--reports-dir", str(reports)]
    return data, meta_dir, reports, args


def test_the_registry_keeps_v1_where_it_was_and_v2_apart() -> None:
    v1, v2 = VERSIONS[1], VERSIONS[2]
    assert (v1.threshold, v1.work_subdir, v1.meta_name) == (0.7, "", "sms_split.v1.meta.json")
    assert (v2.threshold, v2.work_subdir) == (0.4, "split_v2")
    assert v1.assignments(Path("d")) == Path("d/work/assignments.jsonl")
    assert v2.assignments(Path("d")) == Path("d/work/split_v2/assignments.jsonl")
    assert (
        len({v.meta_name for v in VERSIONS.values()})
        == len({v.report_name for v in VERSIONS.values()})
        == 2
    )


def test_v2_is_created_beside_v1_without_touching_it(v1_store) -> None:
    data, meta_dir, reports, args = v1_store
    before = {p: sha(p) for p in (data / "work").iterdir()} | {
        meta_dir / VERSIONS[1].meta_name: sha(meta_dir / VERSIONS[1].meta_name)
    }
    code = cli.main(["split", "--version", "2", *args])
    assert code in (0, 4)  # 4 = created, but some acceptance check failed on the tiny fixture
    assert {p: sha(p) for p in before} == before
    meta = json.loads((meta_dir / "sms_split.v2.meta.json").read_text())
    assert meta["split_version"] == 2 and meta["cluster_jaccard_threshold"] == 0.4
    assert meta["status"] in ("proposed", "proposed_failed_checks")
    assert meta["v1_preserved"]["assignments_sha256"] == before[data / "work" / "assignments.jsonl"]
    assert meta["assignments_sha256"] == sha(VERSIONS[2].assignments(data))
    registry = json.loads((meta_dir / "sms_splits.json").read_text())
    assert [v["version"] for v in registry["versions"]] == [1, 2]
    report = json.loads((reports / VERSIONS[2].report_name).read_text())
    assert report["contamination"]["clusters_in_more_than_one_split"] == 0
    assert report["leakage_profile"]["cross_split_pairs_at_least"]["0.4"] == 0
    assert meta["checks_passed"] == report["all_checks_passed"] == (code == 0)


def test_v2_creation_is_deterministic(v1_store) -> None:
    data, _, _, args = v1_store
    cli.main(["split", "--version", "2", *args])
    first = sha(VERSIONS[2].assignments(data))
    cli.main(["split", "--version", "2", *args])
    assert sha(VERSIONS[2].assignments(data)) == first


def test_the_report_holds_no_message_text(v1_store) -> None:
    data, _, reports, args = v1_store
    cli.main(["split", "--version", "2", *args])
    blob = (reports / VERSIONS[2].report_name).read_text()
    assert not any(r.text[:25] in blob for r in fixture_records())


@pytest.mark.parametrize("version", ["1", "9"])
def test_only_registered_versions_above_one_can_be_created(v1_store, version: str) -> None:
    _, _, _, args = v1_store
    assert cli.main(["split", "--version", version, *args]) == 1


def test_a_changed_record_store_or_v1_file_is_refused(v1_store, capsys) -> None:
    data, _, _, args = v1_store
    v1 = data / "work" / "assignments.jsonl"
    original = v1.read_bytes()
    v1.write_bytes(original + b"\n")
    assert cli.main(["split", "--version", "2", *args]) == 1
    assert "no longer matches its frozen metadata" in capsys.readouterr().err
    v1.write_bytes(original)
    records = data / "work" / "records.jsonl"
    records.write_bytes(records.read_bytes() + b"\n")
    assert cli.main(["split", "--version", "2", *args]) == 1
    assert "record store differs" in capsys.readouterr().err
    assert not VERSIONS[2].assignments(data).exists()


def test_the_held_out_guard_reads_v2_like_v1(v1_store) -> None:
    data, meta_dir, _, args = v1_store
    cli.main(["split", "--version", "2", *args])
    meta = json.loads((meta_dir / "sms_split.v2.meta.json").read_text())
    guard = HeldOutGuard(VERSIONS[2].assignments(data), meta["assignments_sha256"], data / "log")
    with pytest.raises(PermissionError):
        guard.record_ids("test", "tuning", model_version="m")
    assert guard.record_ids("test", FINAL_EVALUATION, model_version="m")


def base_inputs():
    dist = {
        "strata": {"imc:banking": {"missing_from": [], "test_cell_below_minimum": False}},
        "largest_stratum_deviation": 0.01,
    }
    contam = {
        "clusters_in_more_than_one_split": 0,
        "texts_in_more_than_one_split": 0,
        "synthetic_template_families_in_more_than_one_split": 0,
        "simulator_fixture_matches": 0,
    }
    leak = {"cross_split_pairs_at_least": {"0.4": 0}}
    comparison = {"records_lost_vs_previous": 10, "share_lost_vs_previous": 0.01}
    return dist, contam, leak, comparison, []


def test_all_checks_pass_on_clean_inputs() -> None:
    results = split_report.checks(*base_inputs(), 0.4)
    assert all(r["passed"] for r in results) and len(results) == 9


# (part of the inputs, key, bad value, words of the one check that must fail)
VIOLATIONS = [
    ("contam", "clusters_in_more_than_one_split", 1, "no cluster or text"),
    ("leak", "0.4", 3, "cross-split pair"),
    ("contam", "synthetic_template_families_in_more_than_one_split", 1, "synthetic"),
    ("contam", "simulator_fixture_matches", 1, "simulator"),
    ("banking", "missing_from", ["test"], "every stratum"),
    ("banking", "test_cell_below_minimum", True, "test cells"),
    ("dist", "largest_stratum_deviation", 0.05, "deviation"),
    ("comparison", "share_lost_vs_previous", 0.2, "records lost"),
    ("giants", "share_of_stratum_unique_texts", 0.8, "train share"),
]


@pytest.mark.parametrize(("part", "key", "value", "failing"), VIOLATIONS)
def test_each_check_fails_on_its_own_violation(part, key, value, failing: str) -> None:
    dist, contam, leak, comparison, giants = base_inputs()
    targets = {
        "dist": dist,
        "contam": contam,
        "leak": leak["cross_split_pairs_at_least"],
        "banking": dist["strata"]["imc:banking"],
        "comparison": comparison,
    }
    if part == "giants":
        giants.append({key: value})
    else:
        targets[part][key] = value
    results = split_report.checks(dist, contam, leak, comparison, giants, 0.4)
    failed = [r["check"] for r in results if not r["passed"]]
    assert len(failed) == 1 and failing in failed[0]


def test_small_strata_are_exempt_only_from_the_test_cell_minimum() -> None:
    dist, contam, leak, comparison, giants = base_inputs()
    dist["strata"]["imc:hey mum/dad"] = {"missing_from": [], "test_cell_below_minimum": True}
    assert all(
        r["passed"] for r in split_report.checks(dist, contam, leak, comparison, giants, 0.4)
    )
    dist["strata"]["imc:hey mum/dad"]["missing_from"] = ["test"]
    assert not all(
        r["passed"] for r in split_report.checks(dist, contam, leak, comparison, giants, 0.4)
    )
