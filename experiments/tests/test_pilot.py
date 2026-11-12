"""The calibration pilot: blind, blank, disjoint from the audit sample, never used by the gate,
and evaluated with the same integrity rules as the audit."""

import csv
import hashlib
import json
from pathlib import Path

import pytest
from helpers import fixture_clusters

from sms_prep import pilot, review
from sms_prep.pilot import PILOT_SHEETS, build_pilot, evaluate_pilot, select_pilot


@pytest.fixture
def setup(tmp_path, monkeypatch):
    # The fixture corpus lacks some IMC classes, so allow a smaller pilot here.
    monkeypatch.setattr(pilot, "PILOT_SIZE_RANGE", (10, 50))
    records, _, infos = fixture_clusters()
    review.build_bundle(records, infos, tmp_path / "review", seed=5, per_class=100)
    main_key = json.loads((tmp_path / "review" / "answer_key.json").read_text())
    directory = tmp_path / "pilot"
    meta = build_pilot(records, infos, main_key, directory, seed=5)
    return records, infos, main_key, directory, meta, tmp_path


def rows(directory: Path, sheet: str) -> list[dict[str, str]]:
    with (directory / sheet).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def fill(directory: Path, sheet: str, rule, reviewer: str) -> None:
    key = json.loads((directory / "answer_key.json").read_text())
    data = rows(directory, sheet)
    for row in data:
        row["label"], row["reviewer"] = rule(key[row["item_id"]]), reviewer
    review.write_csv(directory / sheet, review.REVIEWER_COLUMNS, data)


def sensible(entry: dict) -> str:
    return {"uci_ham": "benign", "uci_spam": "spam", "synthetic_benign": "benign"}.get(
        entry["class"], "phishing"
    )


def test_the_pilot_is_disjoint_from_the_audit_sample(setup) -> None:
    _, _, main_key, directory, meta, _ = setup
    key = json.loads((directory / "answer_key.json").read_text())
    assert not {v["record_id"] for v in key.values()} & {v["record_id"] for v in main_key.values()}
    assert not {v["cluster_id"] for v in key.values()} & {
        v["cluster_id"] for v in main_key.values()
    }
    assert not set(key) & set(main_key)
    assert meta["disjoint_from_main_audit_sample"] is True


def test_the_pilot_is_blank_blind_and_shared(setup) -> None:
    _, _, _, directory, meta, _ = setup
    a, b = rows(directory, PILOT_SHEETS[0]), rows(directory, PILOT_SHEETS[1])
    assert len(a) == len(b) == meta["items"]
    assert {r["item_id"] for r in a} == {r["item_id"] for r in b}
    assert [r["item_id"] for r in a] != [r["item_id"] for r in b]
    assert all(not r["label"] and not r["reviewer"] and not r["notes"] for r in a + b)
    sheets = (directory / PILOT_SHEETS[0]).read_text() + (directory / PILOT_SHEETS[1]).read_text()
    for word in ("banking", "uci_ham", "synthetic_benign", "control", "gated"):
        assert word not in sheets


def test_the_pilot_uses_the_audit_rubric_and_says_it_is_not_the_gate(setup) -> None:
    _, _, _, directory, meta, _ = setup
    assert (directory / "RUBRIC.md").read_text() == review.RUBRIC
    assert meta["rubric_version"] == review.RUBRIC_VERSION
    instructions = (directory / "INSTRUCTIONS.md").read_text()
    for phrase in ("never used to approve", "Work alone", "language model", "neither of them"):
        assert phrase in instructions
    assert "never used by the label-approval gate" in meta["purpose"]


def test_the_pilot_covers_classes_controls_and_synthetic_items(setup) -> None:
    _, _, _, _, meta, _ = setup
    kinds = meta["items_by_kind"]
    assert {"gated", "control_uci_ham", "control_uci_spam", "synthetic_benign"} <= set(kinds)
    # The fixture has four IMC classes and the audit uses up two of them, leaving two.
    assert meta["gated_classes_covered"] == ["banking", "delivery"]


def test_the_real_plan_fits_the_requested_size() -> None:
    total = sum(size for *_, size in pilot.PILOT_PLAN)
    assert pilot.PILOT_SIZE_RANGE == (30, 50) and 30 <= total <= 50


def test_a_pilot_outside_the_size_range_is_refused(setup, monkeypatch) -> None:
    records, infos, main_key, _, _, tmp = setup
    monkeypatch.setattr(pilot, "PILOT_SIZE_RANGE", (500, 600))
    with pytest.raises(ValueError, match="expected"):
        build_pilot(records, infos, main_key, tmp / "other", seed=5)


def test_selection_is_deterministic(setup) -> None:
    records, infos, main_key, _, _, _ = setup
    assert select_pilot(records, infos, main_key, 5) == select_pilot(records, infos, main_key, 5)


def test_blank_or_partial_sheets_are_incomplete(setup) -> None:
    _, _, _, directory, _, _ = setup
    assert evaluate_pilot(directory)["status"] == "INCOMPLETE"
    fill(directory, PILOT_SHEETS[0], sensible, "alice")
    status = evaluate_pilot(directory)
    assert status["status"] == "INCOMPLETE" and status["used_by_gate"] is False


def test_full_agreement_with_good_controls_is_ready(setup) -> None:
    _, _, _, directory, _, _ = setup
    fill(directory, PILOT_SHEETS[0], sensible, "alice")
    fill(directory, PILOT_SHEETS[1], sensible, "bob")
    status = evaluate_pilot(directory)
    assert status["status"] == "READY" and status["agreement"]["cohen_kappa"] == 1.0
    assert rows(directory, "pilot_disagreements.csv") == []


def test_disagreements_lead_to_calibration_and_are_listed_without_names(setup) -> None:
    _, _, _, directory, _, _ = setup
    fill(directory, PILOT_SHEETS[0], sensible, "alice")
    fill(
        directory, PILOT_SHEETS[1], lambda e: "spam" if e["kind"] == "gated" else sensible(e), "bob"
    )
    status = evaluate_pilot(directory)
    assert status["status"] == "CALIBRATE"
    listed = rows(directory, "pilot_disagreements.csv")
    assert len(listed) == status["agreement"]["disagreements"] > 0
    text = (directory / "pilot_disagreements.csv").read_text()
    assert "alice" not in text and "bob" not in text and all(r["display_text"] for r in listed)


def test_poor_control_accuracy_needs_calibration_even_with_agreement(setup) -> None:
    _, _, _, directory, _, _ = setup
    fill(directory, PILOT_SHEETS[0], lambda e: "phishing", "alice")
    fill(directory, PILOT_SHEETS[1], lambda e: "phishing", "bob")
    assert evaluate_pilot(directory)["status"] == "CALIBRATE"


def test_one_person_twice_or_an_edited_key_is_incomplete(setup) -> None:
    _, _, _, directory, _, _ = setup
    fill(directory, PILOT_SHEETS[0], sensible, "alice")
    fill(directory, PILOT_SHEETS[1], sensible, "alice")
    assert evaluate_pilot(directory)["progress"]["reviewers_distinct_ids"] is False
    fill(directory, PILOT_SHEETS[1], sensible, "bob")
    key = json.loads((directory / "answer_key.json").read_text())
    first = sorted(key)[0]
    key[first]["class"] = "uci_ham"
    (directory / "answer_key.json").write_text(json.dumps(key))
    status = evaluate_pilot(directory)
    assert status["status"] == "INCOMPLETE" and status["progress"]["answer_key_intact"] is False


def test_the_pilot_never_changes_the_main_audit(setup) -> None:
    _, _, _, directory, _, tmp = setup
    main = tmp / "review"
    before = review.evaluate_audit(main)
    digest = hashlib.sha256(b"".join(p.read_bytes() for p in sorted(main.iterdir()))).hexdigest()
    fill(directory, PILOT_SHEETS[0], sensible, "alice")
    fill(directory, PILOT_SHEETS[1], sensible, "bob")
    evaluate_pilot(directory)
    assert review.evaluate_audit(main) == before
    assert (
        hashlib.sha256(b"".join(p.read_bytes() for p in sorted(main.iterdir()))).hexdigest()
        == digest
    )
