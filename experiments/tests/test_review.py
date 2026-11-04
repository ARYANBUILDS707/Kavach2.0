"""The label audit: Wilson statistics, a blinded blank bundle, and a status that is BLOCKED
unless real, independent, complete human annotations exist. The tests that fill sheets do so
only to exercise the arithmetic on fixtures; the product never fills a label."""

import csv
import hashlib
import json
import re
from pathlib import Path

import pytest
from helpers import fixture_clusters

from sms_prep import review
from sms_prep.review import (
    GATE_MINIMUM,
    cohen_kappa,
    evaluate_audit,
    min_correct_for_gate,
    smallest_passable_sample,
    wilson_interval,
)

PER_CLASS = 100


def test_wilson_interval_matches_known_values() -> None:
    low, high = wilson_interval(95, 100)
    assert (round(low, 4), round(high, 4)) == (0.8882, 0.9785)
    assert wilson_interval(0, 10)[0] == 0.0
    assert wilson_interval(10, 10)[1] == pytest.approx(1.0)
    low, high = wilson_interval(5, 10)
    assert low < 0.5 < high and 0.236 < low < 0.237
    with pytest.raises(ValueError):
        wilson_interval(11, 10)
    with pytest.raises(ValueError):
        wilson_interval(0, 0)


def test_the_promotion_gate_is_demanding() -> None:
    assert GATE_MINIMUM == 0.95
    assert smallest_passable_sample() == 73
    assert wilson_interval(73, 73)[0] >= 0.95 > wilson_interval(72, 72)[0]
    assert min_correct_for_gate(200) == 197
    assert wilson_interval(197, 200)[0] >= 0.95 > wilson_interval(196, 200)[0]
    assert min_correct_for_gate(100) == 100
    assert min_correct_for_gate(54) is None and min_correct_for_gate(72) is None


def test_cohen_kappa() -> None:
    assert cohen_kappa([("a", "a"), ("b", "b"), ("a", "a")]) == 1.0
    assert cohen_kappa([("a", "b"), ("b", "a")]) < 0
    assert cohen_kappa([]) is None
    assert (
        round(
            cohen_kappa(
                [("a", "a")] * 40 + [("b", "b")] * 40 + [("a", "b")] * 10 + [("b", "a")] * 10
            ),
            2,
        )
        == 0.60
    )


@pytest.fixture
def bundle(tmp_path):
    records, _, infos = fixture_clusters()
    directory = tmp_path / "review"
    meta = review.build_bundle(records, infos, directory, seed=5, per_class=PER_CLASS)
    return records, infos, directory, meta


def read(directory: Path, name: str) -> list[dict[str, str]]:
    with (directory / name).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_the_bundle_is_blank_so_no_review_is_ever_invented(bundle) -> None:
    _, _, directory, meta = bundle
    for sheet in ("review_A.csv", "review_B.csv"):
        rows = read(directory, sheet)
        assert len(rows) == meta["items"]
        assert all(not r["label"] and not r["reviewer"] and not r["notes"] for r in rows)
    assert read(directory, "adjudication.csv") == []
    assert evaluate_audit(directory)["label_approval"] == "BLOCKED"


def test_reviewers_are_blinded_and_independent(bundle) -> None:
    records, _, directory, meta = bundle
    a, b = read(directory, "review_A.csv"), read(directory, "review_B.csv")
    assert {r["item_id"] for r in a} == {r["item_id"] for r in b}
    assert [r["item_id"] for r in a] != [r["item_id"] for r in b]  # different orders
    key = json.loads((directory / "answer_key.json").read_text())
    sheets = (directory / "review_A.csv").read_text() + (directory / "review_B.csv").read_text()
    for klass in ("banking", "delivery", "wrong number", "hey mum/dad", "imc_spam", "uci_ham"):
        assert klass not in sheets  # the class lives only in the answer key
    for item_id, entry in key.items():
        assert item_id not in {entry["record_id"], entry["cluster_id"]} and entry["class"]
    assert len({v["record_id"] for v in key.values()}) == len(key)  # no text reviewed twice


def test_sample_sizes_controls_and_gate_arithmetic(bundle) -> None:
    _, _, directory, meta = bundle
    gated = meta["gated_items_by_class"]
    assert gated["banking"] == PER_CLASS and gated["delivery"] == PER_CLASS
    assert gated["hey mum/dad"] < smallest_passable_sample() and gated["wrong number"] == 90
    assert meta["min_correct_for_gate"]["hey mum/dad"] is None
    assert meta["min_correct_for_gate"]["banking"] == 100
    assert meta["min_correct_for_gate"]["wrong number"] == min_correct_for_gate(90)
    kinds = {v["kind"] for v in json.loads((directory / "answer_key.json").read_text()).values()}
    assert {"gated", "control_uci_ham", "control_uci_spam"} <= kinds
    assert meta["reviews_required"] == 2 * meta["items"]
    assert (directory / "RUBRIC.md").read_text().count("`phishing`") >= 1


def test_the_bundle_is_reproducible(tmp_path) -> None:
    records, _, infos = fixture_clusters()
    one = review.build_bundle(records, infos, tmp_path / "one", seed=5, per_class=PER_CLASS)
    two = review.build_bundle(records, infos, tmp_path / "two", seed=5, per_class=PER_CLASS)
    other = review.build_bundle(records, infos, tmp_path / "three", seed=6, per_class=PER_CLASS)
    assert one == two and one["answer_key_sha256"] != other["answer_key_sha256"]
    assert (tmp_path / "one" / "review_A.csv").read_text() == (
        tmp_path / "two" / "review_A.csv"
    ).read_text()


def test_reviewers_see_neutralized_masked_text_only() -> None:
    shown = review.display_text(
        "Pay <NAMED_ENTITY> at <URL> call 0871872975812 ref 12345678 or 4829"
    )
    assert shown == "Pay at <url> call <phone> ref <digits> or 4829"


# --- evaluating annotations (fixtures only) --------------------------------------------------


def annotate(directory: Path, labels: dict[str, str], sheet: str, reviewer: str) -> None:
    rows = read(directory, sheet)
    for row in rows:
        if row["item_id"] in labels:
            row["label"], row["reviewer"] = labels[row["item_id"]], reviewer
    review.write_csv(directory / sheet, review.REVIEWER_COLUMNS, rows)


def truth(directory: Path, rule) -> dict[str, str]:
    key = json.loads((directory / "answer_key.json").read_text())
    return {item: rule(entry) for item, entry in key.items()}


def always(label_for_class: dict[str, str], default: str = "benign"):
    return lambda entry: label_for_class.get(entry["class"], default)


def snapshot(directory: Path) -> str:
    return hashlib.sha256(b"".join(p.read_bytes() for p in sorted(directory.iterdir()))).hexdigest()


def test_one_reviewer_alone_is_blocked(bundle) -> None:
    _, _, directory, _ = bundle
    annotate(directory, truth(directory, always({"banking": "phishing"})), "review_A.csv", "alice")
    status = evaluate_audit(directory)
    assert status["label_approval"] == "BLOCKED" and status["promoted_to_phishing"] == []
    assert status["progress"]["reviewer_b_completed"] == 0
    assert all(c["status"] == "BLOCKED" for c in status["classes"].values())


def test_the_same_reviewer_twice_is_not_independent(bundle) -> None:
    _, _, directory, _ = bundle
    labels = truth(directory, always({"banking": "phishing"}))
    annotate(directory, labels, "review_A.csv", "alice")
    annotate(directory, labels, "review_B.csv", "alice")
    status = evaluate_audit(directory)
    assert (
        status["label_approval"] == "BLOCKED" and not status["progress"]["reviewers_distinct_ids"]
    )


def test_partial_sheets_and_invalid_labels_do_not_count(bundle) -> None:
    _, _, directory, _ = bundle
    labels = truth(directory, always({"banking": "phishing"}))
    half = dict(list(labels.items())[: len(labels) // 2])
    annotate(directory, half, "review_A.csv", "alice")
    annotate(directory, {k: "definitely-phishing" for k in labels}, "review_B.csv", "bob")
    status = evaluate_audit(directory)
    assert status["label_approval"] == "BLOCKED" and status["progress"]["reviewer_b_completed"] == 0
    assert status["progress"]["reviewer_a_completed"] == len(half)


def test_unadjudicated_disagreements_block(bundle) -> None:
    _, _, directory, _ = bundle
    labels = truth(directory, always({"banking": "phishing"}))
    annotate(directory, labels, "review_A.csv", "alice")
    first_phishing = sorted(k for k, v in labels.items() if v == "phishing")[0]
    split = {**labels, first_phishing: "spam"}
    annotate(directory, split, "review_B.csv", "bob")
    status = evaluate_audit(directory)
    assert status["progress"]["disagreements"] == 1 and status["label_approval"] == "BLOCKED"


def complete(directory: Path, rule, other=None) -> dict:
    annotate(directory, truth(directory, rule), "review_A.csv", "alice")
    annotate(directory, truth(directory, other or rule), "review_B.csv", "bob")
    return evaluate_audit(directory)


def test_a_class_passes_only_when_the_wilson_lower_bound_clears_the_gate(bundle) -> None:
    _, _, directory, meta = bundle
    # banking: 100/100 phishing (lower bound 0.963); delivery: 97/100 (below the gate);
    # wrong number: no phishing; hey mum/dad: all phishing but only 47 items (too few).
    key = json.loads((directory / "answer_key.json").read_text())
    delivery = sorted(i for i, e in key.items() if e["class"] == "delivery")
    wrong = {i: "spam" for i in delivery[:3]}

    def rule(entry):
        return {"banking": "phishing", "delivery": "phishing", "wrong number": "other_scam",
                "hey mum/dad": "phishing"}.get(entry["class"], "benign")  # fmt: skip

    annotate(directory, truth(directory, rule), "review_A.csv", "alice")
    final = {**truth(directory, rule), **wrong}
    annotate(directory, final, "review_B.csv", "bob")
    adjudication = [
        {"item_id": i, "final_label": "spam", "adjudicator": "carol", "notes": ""} for i in wrong
    ]
    review.write_csv(directory / "adjudication.csv", review.ADJUDICATION_COLUMNS, adjudication)
    status = evaluate_audit(directory)
    assert status["label_approval"] == "APPROVED_CLASSES"
    classes = status["classes"]
    assert classes["banking"]["status"] == "PASS" and classes["banking"]["wilson_95_low"] >= 0.95
    assert classes["delivery"]["status"] == "FAIL" and classes["delivery"]["correct"] == 97
    assert classes["wrong number"]["status"] == "FAIL" and classes["wrong number"]["precision"] == 0
    assert classes["hey mum/dad"]["status"] == "FAIL"
    assert classes["hey mum/dad"]["reason"] == "sample too small to reach the gate"
    assert status["promoted_to_phishing"] == ["banking"]
    assert status["progress"]["disagreements"] == 3 and status["cohen_kappa_all_items"] > 0.9


def test_when_complete_but_nothing_passes_no_class_is_promoted(bundle) -> None:
    _, _, directory, _ = bundle
    status = complete(directory, always({}, default="spam"))
    assert status["label_approval"] == "NO_CLASS_PASSED" and status["promoted_to_phishing"] == []


def test_evaluating_never_modifies_the_review_files(bundle) -> None:
    _, _, directory, _ = bundle
    complete(directory, always({"banking": "phishing"}))
    before = snapshot(directory)
    evaluate_audit(directory)
    evaluate_audit(directory)
    assert snapshot(directory) == before


def test_the_audit_module_cannot_call_a_model_or_the_network() -> None:
    source = Path(review.__file__).read_text()
    imports = set(re.findall(r"^(?:from|import)\s+([\w.]+)", source, flags=re.MULTILINE))
    forbidden = {"urllib", "requests", "http", "socket", "openai", "anthropic", "sklearn", "numpy"}
    assert not {i.split(".")[0] for i in imports} & forbidden
