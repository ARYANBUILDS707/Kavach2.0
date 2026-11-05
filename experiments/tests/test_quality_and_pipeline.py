"""The data-quality report is aggregate-only and detects leaks; the whole chain is deterministic
and independent of input order; the CLI refuses to clobber review sheets or build from nothing."""

import json
import random

import pytest
from helpers import fixture_clusters, fixture_records, record

from dataset_governance.fingerprints import simulator_texts
from sms_prep import cli, quality, review
from sms_prep.clusters import ClusterInfo, assign_clusters, build_cluster_infos
from sms_prep.splits import (
    DEFAULT_PROPORTIONS,
    Assignment,
    assign_splits,
    record_assignments,
    write_assignments,
)


def report_for(records, infos):
    cluster_split = assign_splits(infos)
    rows = record_assignments(records, infos, cluster_split)
    return cluster_split, rows, {
        "dedup": quality.dedup_section(records, infos),
        "labels": quality.label_section(infos),
        "splits": quality.split_section(infos, cluster_split, DEFAULT_PROPORTIONS),
        "contamination": quality.contamination_section(records, rows, infos),
        "source": quality.source_section(records, rows),
        "shortcut": quality.shortcut_feasibility(infos, cluster_split),
    }  # fmt: skip


def test_the_report_contains_no_message_text() -> None:
    records, _, infos = fixture_clusters()
    _, _, report = report_for(records, infos)
    blob = json.dumps(report, default=str)
    assert '"text"' not in blob
    for r in records:
        assert r.text not in blob
    # Even a short distinctive fixture string must not appear.
    assert not any(r.text[:25] in blob for r in records)


def test_a_clean_split_shows_no_leakage_and_balanced_strata() -> None:
    records, _, infos = fixture_clusters()
    _, _, report = report_for(records, infos)
    contamination = report["contamination"]
    assert contamination["clusters_spanning_more_than_one_split"] == 0
    assert contamination["texts_in_more_than_one_split"] == 0
    assert contamination["near_duplicate_pairs_by_threshold"]["0.7"]["pairs_across_splits"] == 0
    assert contamination["simulator_fixture_matches_in_all_records"] == 0
    assert report["splits"]["largest_stratum_deviation"] < 0.06
    assert report["splits"]["strata_missing_from_a_split"] == []


def test_the_report_detects_leaks_when_a_cluster_member_is_moved_across_splits() -> None:
    records, _, infos = fixture_clusters()
    rows = record_assignments(records, infos, assign_splits(infos))
    sizes: dict[str, int] = {}
    for r in rows:
        sizes[r.cluster_id] = sizes.get(r.cluster_id, 0) + 1
    target = next(r for r in rows if sizes[r.cluster_id] >= 2)  # a planted duplicate group
    other = next(s for s in ("train", "validation", "test") if s != target.split)
    leaky = [
        Assignment(r.record_id, r.cluster_id, other if r.record_id == target.record_id else r.split,
                   r.stratum, r.dataset, r.origin)
        for r in rows
    ]  # fmt: skip
    found = quality.contamination_section(records, leaky, infos)
    assert found["clusters_spanning_more_than_one_split"] == 1
    assert found["texts_in_more_than_one_split"] >= 0
    clean = quality.contamination_section(records, rows, infos)
    assert clean["clusters_spanning_more_than_one_split"] == 0


def test_a_simulator_fixture_in_the_data_is_reported() -> None:
    records, _, _ = fixture_clusters()
    fixture_text = sorted(simulator_texts())[0]
    planted = [*records, record("imc25_smishing_reports", "imc", 99999, "banking", fixture_text)]
    infos = build_cluster_infos(planted, assign_clusters(planted, 0.7))
    _, _, report = report_for(planted, infos)
    assert report["contamination"]["simulator_fixture_matches_in_splits"] == 1
    assert report["contamination"]["simulator_fixture_matches_in_all_records"] == 1


def info(source: str, label: str, provisional: str, unique: int, name: str, origin="collected"):
    return ClusterInfo(
        name, (name,), 1, unique, 0, (source,), source, label, provisional, origin, "ok", False
    )


def test_source_shortcut_feasibility_needs_two_collected_sources_per_label() -> None:
    infos = [
        info("imc", "spam", "spam", 40, "a"), info("uci", "spam", "spam", 35, "b"),
        info("uci", "ham", "benign", 80, "c"),
        info("synthetic", "synthetic_benign", "benign", 80, "d", "synthetic"),
        info("imc", "banking", "needs_review", 90, "e"),
    ]  # fmt: skip
    split = {
        "a": "validation",
        "b": "validation",
        "c": "validation",
        "d": "validation",
        "e": "validation",
    }
    # Put the same weight in test so both held-out cells are populated.
    infos += [
        info(i.source, i.label_key, i.provisional, i.unique_texts, i.cluster_id + "t", i.origin)
        for i in infos
    ]
    split |= {i.cluster_id: "test" for i in infos if i.cluster_id.endswith("t")}
    result = quality.shortcut_feasibility(infos, split)["by_provisional_label"]
    assert result["spam"]["feasible"] is True
    assert result["benign"]["feasible"] is False  # UCI alone; synthetic is not collected
    assert result["needs_review"]["feasible"] is False  # IMC alone
    assert "uci" in result["benign"]["sources"] and "synthetic" not in result["benign"]["sources"]


def test_small_test_cells_are_flagged() -> None:
    infos = [info("imc", "hey mum/dad", "needs_review", 10, f"x{i}") for i in range(5)]
    section = quality.split_section(
        infos,
        {i.cluster_id: "train" for i in infos[:3]} | {infos[3].cluster_id: "test"},
        DEFAULT_PROPORTIONS,
    )
    assert section["strata"]["imc:hey mum/dad"]["insufficient_test_cell"] is True


# --- the whole chain ---------------------------------------------------------------------------


def chain(records):
    infos = build_cluster_infos(records, assign_clusters(records, 0.7))
    rows = record_assignments(records, infos, assign_splits(infos, seed=21))
    return {r.record_id: (r.cluster_id, r.split) for r in rows}


def test_the_chain_is_deterministic_and_independent_of_record_order(tmp_path) -> None:
    records = fixture_records()
    first = chain(records)
    shuffled = records[:]
    random.Random(8).shuffle(shuffled)
    assert chain(shuffled) == first == chain(records)


def test_assignment_file_hash_is_reproducible(tmp_path) -> None:
    hashes = []
    for name in ("a", "b"):
        records = fixture_records()
        infos = build_cluster_infos(records, assign_clusters(records, 0.7))
        rows = record_assignments(records, infos, assign_splits(infos, seed=21))
        hashes.append(write_assignments(tmp_path / name, rows))
    assert hashes[0] == hashes[1]


# --- CLI safety ----------------------------------------------------------------------------------


def test_an_existing_bundle_is_never_overwritten_even_with_annotations(tmp_path) -> None:
    records, _, infos = fixture_clusters()
    directory = tmp_path / "review"
    cli.ensure_bundle(directory, records, infos, 5, 100)
    sheet = directory / "review_A.csv"
    sheet.write_text(sheet.read_text() + "human work in progress\n")
    saved = sheet.read_text()
    cli.ensure_bundle(directory, records, infos, 5, 100)
    assert sheet.read_text() == saved
    with pytest.raises(cli.BuildError, match="different items"):
        cli.ensure_bundle(directory, records, infos, 6, 100)
    assert sheet.read_text() == saved


def test_audit_reports_blocked_with_a_nonzero_exit(tmp_path) -> None:
    records, _, infos = fixture_clusters()
    cli.ensure_bundle(tmp_path / "review", records, infos, 5, 100)
    reports = tmp_path / "reports"
    code = cli.main(["audit", "--data-dir", str(tmp_path), "--reports-dir", str(reports)])
    assert code == 3
    status = json.loads((reports / "label_audit_status.json").read_text())
    assert status["label_approval"] == "BLOCKED" and status["promoted_to_phishing"] == []


def test_build_refuses_to_start_without_verified_raw_files(tmp_path, capsys) -> None:
    code = cli.main(["build", "--data-dir", str(tmp_path), "--reports-dir", str(tmp_path / "r"),
                     "--meta-dir", str(tmp_path / "m")])  # fmt: skip
    assert code == 1 and "Stopped" in capsys.readouterr().err
    assert not (tmp_path / "r").exists() and not (tmp_path / "m").exists()


def test_cli_output_never_contains_message_text(tmp_path, capsys) -> None:
    records, _, infos = fixture_clusters()
    cli.ensure_bundle(tmp_path / "review", records, infos, 5, 100)
    cli.main(["audit", "--data-dir", str(tmp_path), "--reports-dir", str(tmp_path / "r")])
    out = capsys.readouterr().out
    assert not any(r.text[:25] in out for r in records) and "BLOCKED" in out
    assert review.GATE_MINIMUM == 0.95


def test_a_new_rubric_replaces_the_old_one_only_before_any_annotation(
    tmp_path, monkeypatch
) -> None:
    records, _, infos = fixture_clusters()
    directory = tmp_path / "review"
    cli.ensure_bundle(directory, records, infos, 5, 100)
    (directory / "RUBRIC.md").write_text("an outdated rubric")
    meta = json.loads((directory / "bundle_meta.json").read_text())
    meta["rubric_version"] = 1
    (directory / "bundle_meta.json").write_text(json.dumps(meta))
    refreshed = cli.ensure_bundle(directory, records, infos, 5, 100)
    assert refreshed["rubric_version"] == review.RUBRIC_VERSION
    assert (directory / "RUBRIC.md").read_text() == review.RUBRIC
    # Once a reviewer has started, the rubric they are following must not change under them.
    sheet = directory / "review_A.csv"
    rows = sheet.read_text().splitlines()
    sheet.write_text("\n".join([rows[0], rows[1][:-3] + "phishing,,alice", *rows[2:]]) + "\n")
    (directory / "RUBRIC.md").write_text("an outdated rubric")
    with pytest.raises(cli.BuildError, match="rubric changed after review began"):
        cli.ensure_bundle(directory, records, infos, 5, 100)
    assert (directory / "RUBRIC.md").read_text() == "an outdated rubric"


def test_the_rubric_has_a_decision_order_examples_and_independence_rules() -> None:
    text = review.RUBRIC
    assert review.RUBRIC_VERSION >= 2 and "Decide in this order" in text
    for label in review.LABELS:
        assert f"`{label}`" in text
    for rule in ("Work alone", "neither reviewer", "one ID per sheet", "language model"):
        assert rule in text
    assert text.count("->") >= 7  # fictional worked examples
