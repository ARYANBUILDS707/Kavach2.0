"""M4-Q solo evaluation: a blinded blank sample drawn only from non-held-out data, labels written
only by a human, criteria registered in advance, and mechanical, honest metrics.

Fixture records are random letter strings; labels written here stand in for a human in tests
only and never touch the real data.
"""

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

import pytest
from helpers import fixture_records

from sms_prep import cli, solo, solo_preflight
from sms_prep.clusters import assign_clusters, build_cluster_infos, write_clusters
from sms_prep.records import write_records
from sms_prep.review import REVIEWER_COLUMNS, build_bundle, display_text, write_csv
from sms_prep.split_versions import VERSIONS
from sms_prep.splits import assign_splits, record_assignments, write_assignments

MANIFESTS = Path(__file__).parents[1] / "manifests"
CRITERIA_V1 = MANIFESTS / "sms_solo_eval_criteria.v1.json"
CRITERIA = MANIFESTS / "sms_solo_eval_criteria.v2.json"
CRITERIA_V1_SHA256 = "1a9879440062d8dc30fcc39365f170e024d69a0970d38e7c367b6710f8a5d5bb"
HUMAN = "tester"


@pytest.fixture
def world(tmp_path):
    """Records, v1 and v2 assignments, an audit answer key, and a data directory laid out as the
    CLI expects it."""
    records = fixture_records()
    data, meta_dir = tmp_path / "data", tmp_path / "manifests"
    work = data / "work"
    write_records(work / "records.jsonl", records)
    stores = {}
    for version in (1, 2):
        spec = VERSIONS[version]
        infos = build_cluster_infos(records, assign_clusters(records, spec.threshold))
        rows = record_assignments(records, infos, assign_splits(infos))
        spec.work_dir(data).mkdir(parents=True, exist_ok=True)
        write_clusters(spec.clusters(data), infos)
        digest = write_assignments(spec.assignments(data), rows)
        meta_dir.mkdir(exist_ok=True)
        (meta_dir / spec.meta_name).write_text(json.dumps({"assignments_sha256": digest}))
        stores[version] = (infos, rows)
    infos1 = stores[1][0]
    build_bundle(records, infos1, data / "review", seed=5, per_class=40)
    (data / "review_pilot").mkdir()
    (data / "review_pilot" / "answer_key.json").write_text("{}")
    return {
        "records": records,
        "v1": stores[1][1],
        "v2": stores[2][1],
        "data": data,
        "meta_dir": meta_dir,
        "tmp": tmp_path,
        "audit_key": json.loads((data / "review" / "answer_key.json").read_text()),
    }


def sample(world, seed: int = solo.SOLO_SEED):
    return solo.select_solo(world["records"], world["v1"], world["v2"], [world["audit_key"]], seed)


def cli_args(world, command: str, *extra: str) -> list[str]:
    return [
        command,
        "--data-dir",
        str(world["data"]),
        "--meta-dir",
        str(world["meta_dir"]),
        "--reports-dir",
        str(world["tmp"] / "reports"),
        "--criteria",
        str(CRITERIA),
        *extra,
    ]


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def human_rule(entry: dict) -> str:
    """A stand-in for a person, used only on fixture data."""
    if entry["origin"] == "synthetic" or entry["stratum"] == "uci:ham":
        return "benign"
    return "spam" if entry["stratum"].endswith("spam") else "phishing"


def fill_sheet(directory: Path, rule=human_rule, only: int | None = None) -> None:
    key = json.loads((directory / solo.KEY).read_text())
    rows = read_rows(directory / solo.SHEET)
    for n, row in enumerate(rows):
        if only is not None and n >= only:
            break
        row["label"], row["reviewer"] = rule(key[row["item_id"]]), HUMAN
    write_csv(directory / solo.SHEET, REVIEWER_COLUMNS, rows)


def fake_score(texts):
    """Deterministic stand-in for the model: fraud for even-hash texts, else legitimate."""
    out = []
    for text in texts:
        fraud = hashlib.sha256(text.encode()).digest()[0] % 2 == 0
        out.append([0.05, 0.05, 0.9] if fraud else [0.9, 0.05, 0.05])
    return out


# --- selection and protection of the held-out sets ---------------------------------------------


def test_the_sample_never_touches_either_held_out_set_or_the_audit(world) -> None:
    items, selection = sample(world)
    v1 = {a.record_id: a for a in world["v1"]}
    v2 = {a.record_id: a for a in world["v2"]}
    assert items and selection["eligible_records"] > 0
    audit_records = {e["record_id"] for e in world["audit_key"].values()}
    audit_clusters_v2 = {v2[r].cluster_id for r in audit_records if r in v2}
    for item in items:
        assert v1[item.record_id].split in ("train", "validation")
        assert v2[item.record_id].split in ("train", "validation")
        assert item.record_id not in audit_records
        assert item.cluster_id not in audit_clusters_v2


def test_one_item_per_campaign_and_collected_and_synthetic_never_mix(world) -> None:
    items, _ = sample(world)
    firsts = [i for i in items if i.kind != "repeat"]
    assert len({i.cluster_id for i in firsts}) == len(firsts)
    by_id = {r.record_id: r for r in world["records"]}
    for item in items:
        assert by_id[item.record_id].origin == item.origin
        assert item.kind != "synthetic" or item.origin == "synthetic"
        assert item.origin != "synthetic" or item.kind in ("synthetic", "repeat")
    assert {i.origin for i in items} == {"collected", "synthetic"}
    assert sum(i.kind == "synthetic" for i in items) <= solo.SYNTHETIC_ITEMS
    repeats = [i for i in items if i.kind == "repeat"]
    originals = {i.item_id: i for i in firsts}
    assert 0 < len(repeats) <= solo.REPEATS
    assert all(originals[r.repeat_of].record_id == r.record_id for r in repeats)


def test_selection_is_deterministic_and_never_reads_a_model(world) -> None:
    assert sample(world)[0] == sample(world)[0]
    assert sample(world, seed=1)[0] != sample(world, seed=2)[0]
    assert "score" not in solo.select_solo.__code__.co_names


def test_a_protected_audit_or_pilot_campaign_is_excluded(world) -> None:
    items, _ = sample(world)
    first = next(i for i in items if i.kind == "collected")
    key = {"x": {"record_id": first.record_id, "cluster_id": "unrelated"}}
    again, _ = solo.select_solo(
        world["records"], world["v1"], world["v2"], [world["audit_key"], key], solo.SOLO_SEED
    )
    assert first.cluster_id not in {i.cluster_id for i in again}


# --- the bundle -------------------------------------------------------------------------------


@pytest.fixture
def bundle(world):
    directory = world["tmp"] / "solo"
    meta = solo.build_solo(
        world["records"], world["v1"], world["v2"], [world["audit_key"]], CRITERIA, directory
    )
    return directory, meta


def test_the_sheet_is_blank_blinded_and_has_no_model_output(world, bundle) -> None:
    directory, meta = bundle
    rows = read_rows(directory / solo.SHEET)
    assert len(rows) == meta["rows"]
    assert list(rows[0]) == list(REVIEWER_COLUMNS)
    assert all(not r["label"] and not r["reviewer"] and not r["notes"] for r in rows)
    key = json.loads((directory / solo.KEY).read_text())
    assert [r["item_id"] for r in rows] != sorted(key)  # not in key order
    assert not (directory / solo.OUTPUTS).exists() and meta["model_output_present"] is False
    sheet_text = (directory / solo.SHEET).read_text()
    for entry in key.values():
        assert entry["record_id"] not in sheet_text and entry["cluster_id"] not in sheet_text
    assert not solo.sheet_has_annotations(directory)


def test_the_bundle_records_the_registered_criteria_and_is_deterministic(world, bundle) -> None:
    directory, meta = bundle
    assert meta["criteria_sha256"] == hashlib.sha256(CRITERIA.read_bytes()).hexdigest()
    assert (directory / solo.CRITERIA_COPY).read_bytes() == CRITERIA.read_bytes()
    again = world["tmp"] / "solo2"
    solo.build_solo(
        world["records"], world["v1"], world["v2"], [world["audit_key"]], CRITERIA, again
    )
    for name in (solo.SHEET, solo.KEY, solo.META):
        assert (directory / name).read_bytes() == (again / name).read_bytes()


# --- evaluation refuses before anything is scored ----------------------------------------------


def scored_calls():
    calls = []

    def score(texts):
        calls.append(len(texts))
        return fake_score(texts)

    return calls, score


def texts_for(world, directory):
    key = json.loads((directory / solo.KEY).read_text())
    by_id = {r.record_id: r for r in world["records"]}
    raw = {i: by_id[e["record_id"]].text for i, e in key.items() if e["kind"] != "repeat"}
    return {i: display_text(t) for i, t in raw.items()}, raw


def evaluate(world, directory, score):
    shown, raw = texts_for(world, directory)
    return solo.evaluate_solo(directory, CRITERIA, score, shown, raw, {"candidate": "fake"})


def test_nothing_is_scored_and_no_label_is_written_while_the_sheet_is_unfinished(
    world, bundle
) -> None:
    directory, _ = bundle
    before = (directory / solo.SHEET).read_bytes()
    fill_sheet(directory, only=len(read_rows(directory / solo.SHEET)) // 2)
    half = (directory / solo.SHEET).read_bytes()
    calls, score = scored_calls()
    with pytest.raises(solo.SoloError, match="incomplete"):
        evaluate(world, directory, score)
    assert calls == [] and not (directory / solo.OUTPUTS).exists()
    assert (directory / solo.SHEET).read_bytes() == half != before


@pytest.mark.parametrize(
    "damage",
    [
        lambda d, rows: rows.pop(),
        lambda d, rows: rows.append(dict(rows[0])),
        lambda d, rows: rows[0].update(reviewer="somebody else"),
    ],
)
def test_a_damaged_sheet_is_rejected_without_scoring(world, bundle, damage) -> None:
    directory, _ = bundle
    fill_sheet(directory)
    rows = read_rows(directory / solo.SHEET)
    damage(directory, rows)
    write_csv(directory / solo.SHEET, REVIEWER_COLUMNS, rows)
    calls, score = scored_calls()
    with pytest.raises(solo.SoloError):
        evaluate(world, directory, score)
    assert calls == []


def test_edited_key_or_criteria_is_refused(world, bundle, tmp_path) -> None:
    directory, _ = bundle
    fill_sheet(directory)
    calls, score = scored_calls()
    changed = tmp_path / "criteria.json"
    data = json.loads(CRITERIA.read_text())
    data["go"]["all_required"]["fraud_recall_wilson_lower_at_least"] = 0.01
    changed.write_text(json.dumps(data))
    shown, raw = texts_for(world, directory)
    with pytest.raises(solo.SoloError, match="criteria"):
        solo.evaluate_solo(directory, changed, score, shown, raw, {})
    key = json.loads((directory / solo.KEY).read_text())
    key[next(iter(key))]["stratum"] = "imc:banking"
    (directory / solo.KEY).write_text(json.dumps(key))
    with pytest.raises(solo.SoloError, match="answer key"):
        evaluate(world, directory, score)
    assert calls == []


def test_a_complete_sheet_is_scored_separately_by_origin_with_no_text_in_the_output(
    world, bundle
) -> None:
    directory, _ = bundle
    fill_sheet(directory)
    calls, score = scored_calls()
    report = evaluate(world, directory, score)
    assert calls and report["status"] in ("GO", "CONDITIONAL", "NO-GO")
    key = json.loads((directory / solo.KEY).read_text())
    firsts = [e for e in key.values() if e["kind"] != "repeat"]
    for origin in ("collected", "synthetic"):
        expected = sum(e["origin"] == origin for e in firsts)
        assert report[origin]["denominators"]["total"] == expected
    assert "synthetic_fraud_on_benign" in report["synthetic"]
    assert "synthetic_fraud_on_benign" not in report["collected"]
    assert report["items_scored"] == len(firsts)
    outputs = json.loads((directory / solo.OUTPUTS).read_text())
    assert outputs["score_semantics"] == "uncalibrated_softmax"
    assert outputs["labels_order"] == ["legitimate", "spam", "fraud"]
    blob = json.dumps(report) + (directory / solo.OUTPUTS).read_text()
    by_id = {r.record_id: r for r in world["records"]}
    assert not any(by_id[e["record_id"]].text[:30] in blob for e in firsts)
    assert not any(i in json.dumps(report) for i in key)


# --- metrics ----------------------------------------------------------------------------------


def make_rows(spec):
    """spec: (human_label, human_class, model_label) -> count."""
    return [
        {"human_label": hl, "human": hc, "model": m, "stratum": "s"}
        for (hl, hc, m), n in spec.items()
        for _ in range(n)
    ]


def test_confusion_matrix_and_one_versus_rest_rates_are_exact() -> None:
    rows = make_rows(
        {
            ("phishing", "fraud", "fraud"): 40,
            ("other_scam", "fraud", "fraud"): 10,
            ("phishing", "fraud", "spam"): 6,
            ("phishing", "fraud", "legitimate"): 4,
            ("spam", "spam", "spam"): 30,
            ("spam", "spam", "fraud"): 8,
            ("benign", "legitimate", "legitimate"): 45,
            ("benign", "legitimate", "fraud"): 3,
            ("benign", "legitimate", "spam"): 2,
        }
    )
    m = solo.pool_metrics(rows)
    assert m["denominators"] == {"fraud": 60, "spam": 38, "legitimate": 50, "total": 148}
    assert m["confusion_rows_human_columns_model"]["fraud"] == {
        "legitimate": 4,
        "spam": 6,
        "fraud": 50,
    }
    fraud = m["per_class_one_vs_rest"]["fraud"]
    assert (fraud["recall"]["k"], fraud["recall"]["n"]) == (50, 60)
    assert (fraud["precision"]["k"], fraud["precision"]["n"]) == (50, 61)
    assert (fraud["false_positive_rate"]["k"], fraud["false_positive_rate"]["n"]) == (11, 88)
    z, k, n = 1.959964, 50, 60  # Wilson score interval from its closed form
    centre = (k / n + z * z / (2 * n)) / (1 + z * z / n)
    margin = z * ((k / n) * (1 - k / n) / n + z * z / (4 * n * n)) ** 0.5 / (1 + z * z / n)
    assert fraud["recall"]["wilson95"] == pytest.approx(
        [centre - margin, centre + margin], abs=1e-4
    )
    fvs = m["fraud_versus_spam"]
    assert (fvs["spam_labeled_fraud"]["k"], fvs["spam_labeled_fraud"]["n"]) == (8, 38)
    assert (fvs["fraud_labeled_spam"]["k"], fvs["fraud_labeled_spam"]["n"]) == (6, 60)
    assert m["fraud_recall_by_human_label"]["other_scam"]["rate"] == 1.0
    assert m["fraud_recall_by_human_label"]["phishing"]["n"] == 50


def test_undefined_rates_are_none_never_zero() -> None:
    m = solo.pool_metrics(make_rows({("benign", "legitimate", "legitimate"): 5}))
    fraud = m["per_class_one_vs_rest"]["fraud"]
    assert fraud["recall"] == {"k": 0, "n": 0, "rate": None, "wilson95": None}
    assert fraud["precision"]["rate"] is None


GOOD = {
    ("phishing", "fraud", "fraud"): 58,
    ("phishing", "fraud", "spam"): 1,
    ("phishing", "fraud", "legitimate"): 1,
    ("spam", "spam", "spam"): 35,
    ("spam", "spam", "fraud"): 3,
    ("spam", "spam", "legitimate"): 2,
    ("benign", "legitimate", "legitimate"): 39,
    ("benign", "legitimate", "spam"): 1,
}


def decision(collected_spec, synthetic_spec=None, agree=9, of=10, unclear=0.0):
    criteria = json.loads(CRITERIA.read_text())
    collected = solo.pool_metrics(make_rows(collected_spec))
    benign = synthetic_spec or {("benign", "legitimate", "legitimate"): 24}
    synthetic = solo.pool_metrics(make_rows(benign))
    rows = make_rows(benign)
    legit = [r for r in rows if r["human"] == "legitimate"]
    synthetic["synthetic_fraud_on_benign"] = solo.rate(
        sum(r["model"] == "fraud" for r in legit), len(legit)
    )
    completeness = {"unclear_share": unclear}
    return solo.decide(criteria, collected, synthetic, completeness, solo.rate(agree, of))


def test_go_requires_every_registered_check() -> None:
    result = decision(GOOD)
    assert result["verdict"] == "GO", result
    assert result["go_checks_failed"] == [] and result["caps"] == []


def test_poor_recall_is_no_go_from_the_interval_not_the_point_estimate() -> None:
    bad = GOOD | {("phishing", "fraud", "fraud"): 18, ("phishing", "fraud", "legitimate"): 41}
    result = decision(bad)
    assert result["verdict"] == "NO-GO"
    assert "fraud recall, Wilson upper below" in result["no_go_rules_fired"]


def test_synthetic_false_alarms_alone_can_force_no_go_or_cap_go() -> None:
    flagged = {("benign", "legitimate", "fraud"): 14, ("benign", "legitimate", "legitimate"): 10}
    assert decision(GOOD, flagged)["verdict"] == "NO-GO"
    some = {("benign", "legitimate", "fraud"): 3, ("benign", "legitimate", "legitimate"): 21}
    capped = decision(GOOD, some)
    assert capped["verdict"] == "CONDITIONAL"
    assert "synthetic benign flagged fraud, Wilson upper" in capped["go_checks_failed"]


def test_small_denominators_a_noisy_reviewer_or_many_unclear_cap_go() -> None:
    small = GOOD | {
        ("phishing", "fraud", "fraud"): 30,
        ("phishing", "fraud", "spam"): 0,
        ("phishing", "fraud", "legitimate"): 0,
    }
    capped = decision(small)
    assert capped["verdict"] == "CONDITIONAL" and "human_fraud" in capped["caps"][0]
    assert decision(GOOD, agree=6, of=10)["verdict"] == "CONDITIONAL"
    assert decision(GOOD, agree=4, of=4)["verdict"] == "CONDITIONAL"  # fewer than 5 pairs
    assert decision(GOOD, unclear=0.25)["verdict"] == "CONDITIONAL"


def test_confusing_fraud_with_spam_blocks_go() -> None:
    mixed = GOOD | {("phishing", "fraud", "fraud"): 35, ("phishing", "fraud", "spam"): 25}
    result = decision(mixed)
    assert result["verdict"] != "GO"
    assert "fraud labeled spam, rate" in result["go_checks_failed"]


def test_no_data_never_passes_and_never_fires_no_go() -> None:
    result = decision({("benign", "legitimate", "legitimate"): 30})
    assert result["verdict"] == "CONDITIONAL" and result["no_go_rules_fired"] == []
    assert not all(c["passed"] for c in result["go_checks"])


def test_the_registered_criteria_cover_every_rule_and_label() -> None:
    criteria = json.loads(CRITERIA.read_text())
    assert set(criteria["human_to_model_class"]) == set(solo.LABELS_MAPPED)
    assert set(criteria["go"]["all_required"]) == {
        "fraud_recall_wilson_lower_at_least",
        "fraud_precision_wilson_lower_at_least",
        "fraud_false_positive_rate_on_legitimate_wilson_upper_at_most",
        "synthetic_fraud_rate_on_benign_wilson_upper_at_most",
        "fraud_labeled_spam_rate_at_most",
        "spam_labeled_fraud_rate_at_most",
        "reviewer_repeat_agreement_at_least",
    }
    assert len(criteria["no_go"]["any_of"]) == 4
    assert "validate" in criteria["purpose"] and "BLOCKED" in criteria["purpose"]
    assert "calibrated probabilities" in criteria["not_claimed"]


# --- the command line -------------------------------------------------------------------------


def test_cli_prepare_then_evaluate_reports_progress_only_until_the_human_finishes(
    world, monkeypatch, capsys
) -> None:
    assert cli.main(cli_args(world, "solo-prepare")) == 0
    directory = world["data"] / "review_solo_v2"
    assert not solo.sheet_has_annotations(directory)
    status = world["tmp"] / "reports" / "solo_eval_status.v2.json"
    assert cli.main(cli_args(world, "solo-evaluate")) == 3
    assert json.loads(status.read_text())["status"] == "INCOMPLETE"
    assert not (directory / solo.OUTPUTS).exists()

    class Fake:
        def info(self):
            return {"candidate": "fake"}

        def __call__(self, texts):
            return fake_score(texts)

    monkeypatch.setattr(cli, "LazyScorer", Fake)
    fill_sheet(directory)
    capsys.readouterr()
    assert cli.main(cli_args(world, "solo-evaluate")) == 0
    out = capsys.readouterr().out
    assert "Solo evaluation:" in out
    report = json.loads(status.read_text())
    assert report["status"] in ("GO", "CONDITIONAL", "NO-GO")
    by_id = {r.record_id: r for r in world["records"]}
    assert not any(r.text[:30] in status.read_text() + out for r in by_id.values())


def test_cli_prepare_never_overwrites_labels_and_is_idempotent(world, capsys) -> None:
    assert cli.main(cli_args(world, "solo-prepare")) == 0
    directory = world["data"] / "review_solo_v2"
    fill_sheet(directory, only=5)
    labeled = (directory / solo.SHEET).read_bytes()
    assert cli.main(cli_args(world, "solo-prepare")) == 0
    assert "left unchanged" in capsys.readouterr().out
    assert cli.main(cli_args(world, "solo-prepare", "--seed", "99")) == 1
    assert (directory / solo.SHEET).read_bytes() == labeled


def test_cli_refuses_when_a_frozen_assignment_file_changed(world) -> None:
    path = VERSIONS[2].assignments(world["data"])
    path.write_text(path.read_text() + "\n")
    assert cli.main(cli_args(world, "solo-prepare")) == 1
    assert not (world["data"] / "review_solo_v2").exists()


def test_the_scorer_refuses_rather_than_inventing_scores(monkeypatch) -> None:
    import sys

    monkeypatch.setitem(sys.modules, "pretrained.inference", None)
    with pytest.raises(solo.SoloError, match="not installed"):
        cli.LazyScorer()(["FICTIONAL DEMO: hello"])


def test_the_software_has_no_code_path_that_writes_a_label() -> None:
    source = Path(solo.__file__).read_text()
    # The only CSV the module writes is the blank sheet, with an empty label in every row.
    assert source.count("write_csv(") == 1 and '"label": ""' in source
    cli_source = Path(cli.__file__).read_text()
    assert "SHEET" not in cli_source.replace("solo.SHEET", "")  # the CLI never opens it for writing
    assert Counter(solo.LABELS_MAPPED) == Counter(("phishing", "other_scam", "spam", "benign"))


def test_a_record_held_out_in_either_split_version_is_never_eligible() -> None:
    """Eligibility is the intersection: train/validation in BOTH v1 and v2, so neither the frozen
    test set nor the proposed one can leak in, whichever split is later adopted."""
    from helpers import record

    from sms_prep.splits import Assignment

    names = ["both_ok", "v2_test", "v1_test", "v2_missing", "v1_missing", "protected"]
    recs = [
        record("imc25_smishing_reports", "imc", i, "banking", f"text {n}")
        for i, n in enumerate(names)
    ]
    by_name = dict(zip(names, recs, strict=True))

    def row(name: str, split: str, cluster: str) -> Assignment:
        return Assignment(
            by_name[name].record_id,
            cluster,
            split,
            "imc:banking",
            "imc25_smishing_reports",
            "collected",
        )

    v1 = [
        row("both_ok", "train", "a"),
        row("v2_test", "validation", "b"),
        row("v1_test", "test", "c"),
        row("v2_missing", "train", "d"),
        row("protected", "train", "p"),
    ]
    v2 = [
        row("both_ok", "validation", "A"),
        row("v2_test", "test", "B"),
        row("v1_test", "train", "C"),
        row("v1_missing", "train", "E"),
        row("protected", "train", "P"),
    ]
    kept = solo.eligible_records(recs, v1, v2, protected_v1={"p"}, protected_v2=set())
    assert [r.record_id for r, _ in kept] == [by_name["both_ok"].record_id]
    kept = solo.eligible_records(recs, v1, v2, protected_v1=set(), protected_v2={"P"})
    assert by_name["protected"].record_id not in [r.record_id for r, _ in kept]


def test_a_campaign_is_sampled_once_across_strata_and_pools() -> None:
    """The pickers share one `used` set: a campaign taken by one stratum is skipped by the next,
    including a synthetic template that joined a collected campaign."""
    from helpers import record

    from sms_prep.splits import Assignment

    def pair(name: str, cluster: str, group: str = "", origin: str = "collected"):
        r = record(
            "imc25_smishing_reports",
            "imc",
            hash(name) % 10**6,
            "banking",
            f"text {name}",
            group=group,
            origin=origin,
        )
        return r, Assignment(r.record_id, cluster, "train", "imc:banking", r.dataset, origin)

    first = [pair("a", "campaign-1"), pair("b", "campaign-2")]
    second = [pair("c", "campaign-1"), pair("d", "campaign-3")]
    used: set[str] = set()
    took_first = solo.pick(first, 5, 1, "x", used)
    took_second = solo.pick(second, 5, 1, "y", used)
    assert {a.cluster_id for _, a in took_first} == {"campaign-1", "campaign-2"}
    assert {a.cluster_id for _, a in took_second} == {"campaign-3"}
    assert used == {"campaign-1", "campaign-2", "campaign-3"}

    templates = [
        pair("t1", "campaign-1", "otp_login-1", "synthetic"),
        pair("t2", "campaign-9", "otp_login-2", "synthetic"),
    ]
    used = {"campaign-1"}
    taken = solo.synthetic_picks(templates, 5, 1, used)
    assert [a.cluster_id for _, a in taken] == ["campaign-9"]
    assert used == {"campaign-1", "campaign-9"}


# --- revision 2: ten more UCI ham campaigns, the same thresholds -------------------------------


def stratum_ids(items, stratum):
    return {i.item_id for i in items if i.stratum == stratum and i.kind != "repeat"}


def test_revision_two_adds_exactly_ten_ham_campaigns_and_nothing_else_changes(world) -> None:
    one, _ = solo.select_solo(world["records"], world["v1"], world["v2"], [world["audit_key"]],
                              solo.SOLO_SEED, 1)  # fmt: skip
    two, _ = sample(world)
    assert len(stratum_ids(one, "uci:ham")) == 30 and len(stratum_ids(two, "uci:ham")) == 40
    assert stratum_ids(one, "uci:ham") < stratum_ids(two, "uci:ham")  # the original 30 are kept
    for stratum in {i.stratum for i in one if i.kind != "repeat"} - {"uci:ham"}:
        if stratum.startswith("synthetic") or stratum == "uci:spam":
            continue  # may shift only if a new ham campaign collided with them
        assert stratum_ids(one, stratum) == stratum_ids(two, stratum)
    assert sum(i.kind == "repeat" for i in two) == solo.REPEATS
    assert solo.PLAN_REV2 == tuple(
        (s, label, n + 10 if (s, label) == ("uci", "ham") else n) for s, label, n in solo.PLAN_REV1
    )


@pytest.mark.parametrize("revision", [1, 2])
def test_every_revision_keeps_the_protections(world, revision) -> None:
    items, _ = solo.select_solo(world["records"], world["v1"], world["v2"],
                                [world["audit_key"]], solo.SOLO_SEED, revision)  # fmt: skip
    v1 = {a.record_id: a for a in world["v1"]}
    v2 = {a.record_id: a for a in world["v2"]}
    audit = {e["record_id"] for e in world["audit_key"].values()}
    audit_v2 = {v2[r].cluster_id for r in audit if r in v2}
    firsts = [i for i in items if i.kind != "repeat"]
    assert len({i.cluster_id for i in firsts}) == len(firsts)
    for item in items:
        assert v1[item.record_id].split in ("train", "validation")
        assert v2[item.record_id].split in ("train", "validation")
        assert item.record_id not in audit and item.cluster_id not in audit_v2


def test_revision_two_bundle_is_blank_hashed_and_leaves_revision_one_alone(world) -> None:
    keys = [world["audit_key"]]
    old, new = world["tmp"] / "rev1", world["tmp"] / "rev2"
    m1 = solo.build_solo(
        world["records"], world["v1"], world["v2"], keys, CRITERIA_V1, old, solo.SOLO_SEED, 1
    )
    before = {
        n: (old / n).read_bytes() for n in (solo.SHEET, solo.KEY, solo.META, solo.CRITERIA_COPY)
    }
    m2 = solo.build_solo(world["records"], world["v1"], world["v2"], keys, CRITERIA, new)
    assert (m1["revision"], m2["revision"]) == (1, 2) and m2["rows"] == m1["rows"] + 10
    assert before == {
        n: (old / n).read_bytes() for n in before
    }  # building revision 2 left it alone
    assert m2["criteria_sha256"] == hashlib.sha256(CRITERIA.read_bytes()).hexdigest()
    assert m2["criteria_sha256"] != m1["criteria_sha256"]
    assert (new / solo.CRITERIA_COPY).read_bytes() == CRITERIA.read_bytes()
    assert m2["items_by_stratum"]["uci:ham"] == 40
    assert not solo.sheet_has_annotations(new) and not (new / solo.OUTPUTS).exists()
    assert (new / "INSTRUCTIONS.md").read_text().count("sms_solo_eval_criteria.v2.json") == 1
    assert "criteria.v1" not in (new / "INSTRUCTIONS.md").read_text()
    assert hashlib.sha256(CRITERIA_V1.read_bytes()).hexdigest() == CRITERIA_V1_SHA256


def test_criteria_v2_changes_only_the_attainability_minimums() -> None:
    one, two = (json.loads(p.read_text()) for p in (CRITERIA_V1, CRITERIA))
    assert one["criteria_version"] == 1 and two["criteria_version"] == 2
    for section in ("go", "no_go", "completeness", "human_to_model_class", "interval", "pools"):
        assert one[section] == two[section]  # every threshold is unchanged
    assert one["minimum_denominators_collected"]["human_legitimate"] == 25
    assert two["minimum_denominators_collected"] == {
        "human_fraud": 40, "human_spam": 25, "human_legitimate": 35,
        "below_min": one["minimum_denominators_collected"]["below_min"],
    }  # fmt: skip
    assert two["minimum_denominators_synthetic"]["human_legitimate"] == 16
    assert (
        two["go"]["all_required"]["fraud_false_positive_rate_on_legitimate_wilson_upper_at_most"]
        == 0.10
    )


def wilson_upper_zero_events(n: int) -> float:
    z = 1.959964
    return z * z / (n + z * z)  # closed form for k = 0


@pytest.mark.parametrize(
    ("n", "limit", "reachable"),
    [(30, 0.10, False), (34, 0.10, False), (35, 0.10, True), (15, 0.20, False), (16, 0.20, True)],
)
def test_the_wilson_boundaries_that_set_the_minimum_label_counts(n, limit, reachable) -> None:
    upper = solo.rate(0, n)["wilson95"][1]
    assert upper == pytest.approx(wilson_upper_zero_events(n), abs=1e-4)
    assert (upper <= limit) is reachable


def test_go_needs_35_collected_legitimate_and_16_synthetic_benign_labels() -> None:
    def legit(n):
        return GOOD | {
            ("benign", "legitimate", "legitimate"): n,
            ("benign", "legitimate", "spam"): 0,
        }

    short = decision(legit(34))
    assert short["verdict"] == "CONDITIONAL" and "human_legitimate" in short["caps"][0]
    assert "legitimate flagged fraud, Wilson upper" in short["go_checks_failed"]
    assert decision(legit(35))["verdict"] == "GO"
    benign = {("benign", "legitimate", "legitimate"): 15}
    thin = decision(GOOD, benign)
    assert thin["verdict"] == "CONDITIONAL" and "too few synthetic benign labels" in thin["caps"]
    assert "synthetic benign flagged fraud, Wilson upper" in thin["go_checks_failed"]
    assert decision(GOOD, {("benign", "legitimate", "legitimate"): 16})["verdict"] == "GO"
    one_flag = legit(40) | {("benign", "legitimate", "fraud"): 1}
    assert decision(one_flag)["verdict"] == "CONDITIONAL"  # 1 of 41: upper bound is above 0.10


def test_the_cli_builds_revision_one_and_two_side_by_side(world) -> None:
    assert cli.main(cli_args(world, "solo-prepare", "--revision", "2")) == 0
    assert (world["data"] / "review_solo_v2" / solo.SHEET).exists()
    assert not (world["data"] / "review_solo").exists()


# --- the read-only preflight ------------------------------------------------------------------


def run_preflight(world, directory):
    by_id = {r.record_id: r for r in world["records"]}
    return solo_preflight.preflight(
        directory, CRITERIA, lambda record_id: display_text(by_id[record_id].text)
    )


def by_status(checks, fragment):
    return next(c for c in checks if fragment in c.detail)


def total_rows(directory: Path) -> int:
    return len(read_rows(directory / solo.SHEET))


def test_a_blank_sheet_never_reports_a_zero_unclear_share_as_a_pass(world, bundle) -> None:
    directory, _ = bundle
    checks = run_preflight(world, directory)
    share = by_status(checks, "unclear share")
    assert share.status == solo_preflight.NOT_EVALUATED
    assert "0.0%" not in share.detail and "PASS" not in share.status
    assert by_status(checks, "reviewer name").status == solo_preflight.NOT_EVALUATED
    assert not solo_preflight.ready(checks)
    assert by_status(checks, "valid labels").status == solo_preflight.FAIL


@pytest.mark.parametrize(
    ("unclear", "valid", "status"),
    [
        (0, 0, solo_preflight.NOT_EVALUATED),
        (0, 183, solo_preflight.PASS),  # a real 0% with a real denominator is a pass
        (18, 183, solo_preflight.PASS),  # 9.8%
        (19, 183, solo_preflight.FAIL),  # 10.4%
        (1, 5, solo_preflight.FAIL),
    ],
)
def test_unclear_share_uses_valid_labels_and_the_registered_maximum(unclear, valid, status) -> None:
    maximum = json.loads(CRITERIA.read_text())["completeness"]["max_unclear_share"]
    assert maximum == 0.10
    check = solo_preflight.unclear_share_check(unclear, valid, maximum)
    assert check.status == status
    if valid:
        assert f"{unclear} of {valid}" in check.detail


def test_the_preflight_agrees_with_the_evaluator_on_the_unclear_share(world, bundle) -> None:
    directory, _ = bundle
    key = json.loads((directory / solo.KEY).read_text())

    def rule(entry):  # every 5th first-time ham row is unclear, the rest as the usual stand-in
        return (
            "unclear"
            if entry["stratum"] == "uci:ham" and entry["record_id"][-1] in "0123"
            else human_rule(entry)
        )

    fill_sheet(directory, rule)
    labels, _ = solo.read_labels(directory, key)
    unclear = sum(v == "unclear" for v in labels.values())
    share = by_status(run_preflight(world, directory), "unclear labels")
    assert f"{unclear} of {len(labels)}" in share.detail
    report = evaluate(world, directory, fake_score)
    assert report["completeness"]["unclear_share"] == round(unclear / len(labels), 4)


def test_a_fully_labeled_sheet_is_ready_only_if_every_registered_minimum_holds(
    world, bundle
) -> None:
    directory, _ = bundle
    fill_sheet(directory)
    checks = run_preflight(world, directory)
    assert by_status(checks, "valid labels").status == solo_preflight.PASS
    assert by_status(checks, "repeat rows labeled").status == solo_preflight.PASS
    assert by_status(checks, "reviewer name").status == solo_preflight.PASS
    assert by_status(checks, "unclear labels").status == solo_preflight.PASS
    assert by_status(checks, "answer key hash").status == solo_preflight.PASS
    assert by_status(checks, "collected fraud").status == by_status(checks, "collected spam").status
    # the fixture world has fewer than 40 fraud / 35 ham first-time rows, so it is not ready
    assert by_status(checks, "rows:").status == solo_preflight.FAIL  # fixture is not 183 rows
    assert not solo_preflight.ready(checks)


def test_the_preflight_catches_each_defect_without_scoring(world, bundle) -> None:
    directory, _ = bundle
    key = json.loads((directory / solo.KEY).read_text())
    fill_sheet(directory)
    rows = read_rows(directory / solo.SHEET)
    repeat = next(r for r in rows if key[r["item_id"]]["kind"] == "repeat")
    repeat["label"] = ""
    rows[0]["reviewer"] = "someone else"
    other = next(r for r in rows if r is not rows[0] and r is not repeat)
    other["display_text"] = other["display_text"] + " edited"
    write_csv(directory / solo.SHEET, REVIEWER_COLUMNS, rows)
    checks = run_preflight(world, directory)
    assert by_status(checks, "repeat rows labeled").status == solo_preflight.FAIL
    assert by_status(checks, "distinct reviewer names").status == solo_preflight.FAIL
    assert by_status(checks, "display text differs").detail.endswith(": 1")
    (directory / solo.KEY).write_text((directory / solo.KEY).read_text() + " ")
    assert (
        by_status(run_preflight(world, directory), "answer key hash").status == solo_preflight.FAIL
    )
    assert not (directory / solo.OUTPUTS).exists()


def test_the_preflight_is_read_only_and_prints_no_text_ids_or_names(world, capsys) -> None:
    assert cli.main(cli_args(world, "solo-prepare")) == 0
    directory = world["data"] / "review_solo_v2"
    fill_sheet(directory)
    before = {p.name: p.read_bytes() for p in directory.iterdir()}
    code = cli.main(cli_args(world, "solo-preflight") + [])
    out = capsys.readouterr().out
    assert code == 3 and "PREFLIGHT:" in out
    assert before == {p.name: p.read_bytes() for p in directory.iterdir()}
    assert not (directory / solo.OUTPUTS).exists()
    by_id = {r.record_id: r for r in world["records"]}
    key = json.loads((directory / solo.KEY).read_text())
    assert not any(by_id[e["record_id"]].text[:30] in out for e in key.values())
    assert not any(item in out for item in key) and HUMAN not in out
    source = Path(solo_preflight.__file__).read_text()
    for forbidden in (
        "torch",
        "transformers",
        "pretrained",
        "write_text",
        "write_bytes",
        "write_csv",
        "open(",
    ):
        assert forbidden not in source


def test_the_cli_preflight_on_a_blank_bundle_is_not_ready_and_reports_not_evaluated(
    world, capsys
) -> None:
    assert cli.main(cli_args(world, "solo-prepare")) == 0
    capsys.readouterr()
    assert cli.main(cli_args(world, "solo-preflight")) == 3
    out = capsys.readouterr().out
    assert "NOT EVALUATED" in out and "unclear share" in out and "NOT READY" in out
    assert "0.0%" not in out


def test_the_blank_sheet_summary_matches_the_displayed_checks_exactly(world, capsys) -> None:
    assert cli.main(cli_args(world, "solo-prepare")) == 0
    capsys.readouterr()
    assert cli.main(cli_args(world, "solo-preflight")) == 3
    lines = capsys.readouterr().out.splitlines()
    *shown, summary = lines
    statuses = [line[:14].strip() for line in shown]
    assert set(statuses) <= {"PASS", "FAIL", "NOT EVALUATED"}
    passing, failing, unevaluated = (statuses.count(s) for s in ("PASS", "FAIL", "NOT EVALUATED"))
    assert len(shown) == passing + failing + unevaluated
    not_passing = failing + unevaluated
    assert not_passing > 0
    assert summary == (
        f"PREFLIGHT: NOT READY ({not_passing} checks not passing); {len(shown)} checks: "
        f"{passing} PASS, {failing} FAIL, {unevaluated} NOT EVALUATED"
    )
    # every non-passing check is one visible line, none merged into another
    assert sum(not s.startswith("PASS") for s in shown) == not_passing


def test_summary_line_counts_every_status_and_only_all_pass_is_ready() -> None:
    P, F, N = solo_preflight.PASS, solo_preflight.FAIL, solo_preflight.NOT_EVALUATED
    mixed = [solo_preflight.Check(s, "x") for s in (P, P, F, N, N, F, F)]
    assert solo_preflight.summary_line(mixed) == (
        "PREFLIGHT: NOT READY (5 checks not passing); 7 checks: 2 PASS, 3 FAIL, 2 NOT EVALUATED"
    )
    assert not solo_preflight.ready(mixed)
    only_unevaluated = [solo_preflight.Check(s, "x") for s in (P, P, N)]
    assert not solo_preflight.ready(only_unevaluated)
    assert "NOT READY (1 checks not passing)" in solo_preflight.summary_line(only_unevaluated)
    all_pass = [solo_preflight.Check(P, "x")] * 3
    assert solo_preflight.ready(all_pass)
    assert solo_preflight.summary_line(all_pass) == (
        "PREFLIGHT: READY; 3 checks: 3 PASS, 0 FAIL, 0 NOT EVALUATED"
    )
