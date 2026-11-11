"""Dataset manifest governance: v1 is immutable history, v2 carries the owner's D04 decisions,
and the validator rejects each way of breaking the policy. No dataset is needed."""

import copy
import json
from typing import Any

import pytest
from pydantic import ValidationError

from dataset_governance.fingerprints import (
    SIMULATOR_CATALOG,
    jaccard,
    normalize_text,
    shingles,
    simulator_fingerprints,
    simulator_overlap,
    simulator_texts,
    text_fingerprint,
)
from dataset_governance.manifest import (
    DEFAULT_MANIFEST,
    V1_MANIFEST,
    Manifest,
    check_simulator_exclusion,
    load_manifest,
)


def raw(path=DEFAULT_MANIFEST) -> dict[str, Any]:
    return json.loads(path.read_text())


def dataset(data: dict[str, Any], dataset_id: str) -> dict[str, Any]:
    return next(d for d in data["datasets"] if d["id"] == dataset_id)


def rejects(data: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        Manifest.model_validate(data)


# --- v1 is history -------------------------------------------------------------------------


def test_v1_stays_valid_and_records_the_pending_state_before_d04() -> None:
    manifest = load_manifest(V1_MANIFEST)
    assert manifest.manifest_version == 1 and manifest.decisions.d04_sms == "pending"
    assert {d.approval.decision for d in manifest.datasets} == {"pending"}


# --- the shipped v2 manifest ---------------------------------------------------------------


def test_shipped_manifest_is_v2_and_valid() -> None:
    manifest = load_manifest()
    check_simulator_exclusion(manifest)
    assert manifest.manifest_version == 2
    assert [d.id for d in manifest.datasets] == [
        "imc25_smishing_reports",
        "uci_sms_spam_collection",
        "mishra_soni_2022",
        "munoz_islam_2025",
    ]


def test_owner_decisions_are_recorded() -> None:
    manifest = load_manifest()
    by_id = {d.id: d for d in manifest.datasets}
    assert manifest.decisions.d04_sms == "approved"
    assert by_id["imc25_smishing_reports"].approval.decision == "approved"
    assert by_id["uci_sms_spam_collection"].approval.decision == "approved"
    assert by_id["mishra_soni_2022"].status == "audit_reference_only"
    assert by_id["munoz_islam_2025"].status == "excluded"
    assert by_id["munoz_islam_2025"].approval.decision == "rejected"
    assert by_id["munoz_islam_2025"].permitted_use == []


def test_promotion_gate_is_the_owners_wilson_rule() -> None:
    gate = load_manifest().policy.promotion_gate
    assert gate is not None
    assert (gate.statistic, gate.confidence, gate.minimum) == ("wilson_lower_bound", 0.95, 0.95)
    assert gate.reviewers_per_item >= 2 and gate.status_when_incomplete == "BLOCKED"


def test_no_imc_class_is_promoted_by_the_manifest() -> None:
    for d in load_manifest().datasets:
        for label, rule in d.label_mapping.items():
            assert rule.target != "phishing", (d.id, label)
    imc = {d.id: d for d in load_manifest().datasets}["imc25_smishing_reports"]
    for klass in ("wrong number", "hey mum/dad"):
        assert imc.label_mapping[klass].target == "needs_review"
    assert imc.label_mapping["spam"].target == "spam"


def test_synthetic_hard_negatives_are_separate_and_never_real_world_evidence() -> None:
    manifest = load_manifest()
    (synthetic,) = manifest.synthetic_sets
    assert synthetic.label == "benign" and synthetic.approval.decision == "approved"
    assert "held_out_evaluation" not in synthetic.permitted_use
    assert manifest.policy.real_world_test_excludes_synthetic is True
    assert synthetic.records == 720 and synthetic.template_families == 72


def test_every_downloaded_file_is_verifiable() -> None:
    for d in load_manifest().datasets:
        if d.status == "excluded":
            continue
        assert d.allowed_download_hosts and d.download_url.startswith("https://")
        assert d.download_url.split("/")[2] in d.allowed_download_hosts
        for f in d.files:
            assert len(f.sha256) == 64 and f.size_bytes > 0 and f.path_in_download


def test_scripts_and_documents_in_archives_are_never_written_to_disk() -> None:
    mishra = {d.id: d for d in load_manifest().datasets}["mishra_soni_2022"]
    extracted = [f.name for f in mishra.files if f.extract]
    assert extracted == ["Dataset_5971.csv"]
    assert any(f.name.endswith(".py") and not f.extract for f in mishra.files)


def test_manifest_holds_no_message_text_or_local_paths() -> None:
    text = DEFAULT_MANIFEST.read_text()
    for forbidden in ("/Users/", "/tmp/", "C:\\", "~/", "file://", "X-Amz"):
        assert forbidden not in text


# --- the validator rejects policy breaks -------------------------------------------------------


def test_automatic_phishing_labels_are_rejected() -> None:
    data = raw()
    dataset(data, "imc25_smishing_reports")["label_mapping"]["banking"] = {
        "target": "phishing",
        "rule": "auto",
    }
    rejects(data, "automatically to phishing")


@pytest.mark.parametrize("target", ["phishing", "benign"])
def test_spam_is_its_own_class(target: str) -> None:
    data = raw()
    rule = {"target": target, "rule": "x", "human_verified": True}
    dataset(data, "uci_sms_spam_collection")["label_mapping"]["spam"] = rule
    rejects(data, "spam is its own class")


def test_review_labels_need_a_plan() -> None:
    data = raw()
    del dataset(data, "imc25_smishing_reports")["label_mapping"]["banking"]["review_plan"]
    rejects(data, "needs_review requires a review plan")


def test_every_source_label_needs_exactly_one_rule() -> None:
    data = raw()
    del dataset(data, "uci_sms_spam_collection")["label_mapping"]["ham"]
    rejects(data, "every source label needs exactly one mapping rule")


def test_generated_data_cannot_be_used_for_evaluation() -> None:
    data = raw()
    munoz = dataset(data, "munoz_islam_2025")
    munoz["status"] = "candidate_conditional"
    munoz["permitted_use"] = ["training", "held_out_evaluation"]
    rejects(data, "cannot validate or evaluate")


def test_excluded_data_has_no_uses_and_cannot_be_approved() -> None:
    data = raw()
    dataset(data, "munoz_islam_2025")["permitted_use"] = ["training"]
    rejects(data, "excluded data has no permitted uses")
    data = raw()
    dataset(data, "munoz_islam_2025")["approval"] = {"decision": "approved", "reference": "x"}
    rejects(data, "excluded data cannot be approved")


def test_audit_reference_data_is_only_an_audit_reference() -> None:
    data = raw()
    dataset(data, "mishra_soni_2022")["permitted_use"] = ["training"]
    rejects(data, "audit-only data may only be an audit reference")


def test_approvals_need_references_and_follow_d04() -> None:
    data = raw()
    dataset(data, "imc25_smishing_reports")["approval"] = {"decision": "approved"}
    rejects(data, "approved decision needs a reference")
    data = raw()
    data["decisions"]["d04_sms"] = "pending"
    rejects(data, "approved before D04")
    data = raw()
    dataset(data, "uci_sms_spam_collection")["approval"] = {"decision": "pending"}
    rejects(data, "D04 is approved only when every candidate dataset is")


def test_version_two_needs_its_governance_sections() -> None:
    data = raw()
    data["policy"]["promotion_gate"] = None
    rejects(data, "needs a promotion gate")
    data = raw()
    data["policy"]["real_world_test_excludes_synthetic"] = False
    rejects(data, "must exclude synthetic data")
    data = raw()
    data["synthetic_sets"] = []
    rejects(data, "needs the synthetic hard-negative set")
    data = raw()
    dataset(data, "uci_sms_spam_collection")["allowed_download_hosts"] = []
    rejects(data, "needs allowed download hosts")
    data = raw()
    del dataset(data, "uci_sms_spam_collection")["files"][0]["path_in_download"]
    rejects(data, "needs its path in the download")


def test_synthetic_data_cannot_join_the_real_world_test() -> None:
    data = raw()
    data["synthetic_sets"][0]["permitted_use"] = ["held_out_evaluation"]
    rejects(data, "Input should be")


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("datasets", 0, "files", 0, "sha256"), "ABC", "String should match"),
        (("datasets", 0, "source_url"), "http://example.com/x", "String should match"),
        (("datasets", 0, "doi"), "not-a-doi", "String should match"),
        (("datasets", 0, "license", "spdx"), "MIT", "Input should be"),
        (("datasets", 0, "origin"), "scraped", "Input should be"),
        (("datasets", 0, "sample_text"), "message text", "Extra inputs"),
        (("policy", "raw_data_in_git"), True, "Input should be False"),
        (("policy", "promotion_gate", "confidence"), 0.2, "greater than 0.5"),
        (("synthetic_sets", 0, "corpus_sha256"), "zz", "String should match"),
        (("datasets", 0, "limitations"), [], "at least 1 item"),
    ],
)
def test_malformed_records_are_rejected(path: tuple, value: Any, message: str) -> None:
    data = raw()
    target: Any = data
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    rejects(data, message)


def test_duplicate_dataset_ids_are_rejected() -> None:
    data = raw()
    data["datasets"].append(copy.deepcopy(data["datasets"][0]))
    rejects(data, "dataset IDs must be unique")


def test_the_manifest_must_declare_which_simulator_catalog_it_excludes() -> None:
    data = raw()
    data["policy"]["simulator_exclusion"]["catalog_version"] = 99
    with pytest.raises(ValueError, match="packaged is v1"):
        check_simulator_exclusion(Manifest.model_validate(data))


# --- fingerprints and the simulator fixtures ------------------------------------------------------


def test_normalization_ignores_case_digits_urls_punctuation_and_unicode_form() -> None:
    a = "WIN £1000 now!! Visit http://Win-Now.example.invalid/x?id=123 or call 0871 872 9758"
    b = "win £5 NOW. visit <URL> or call 1 2 3"
    assert normalize_text(a) == normalize_text(b)
    assert text_fingerprint("Ｈｅｌｌｏ  World") == text_fingerprint("hello world")
    assert text_fingerprint("one thing") != text_fingerprint("another thing")


def test_near_duplicate_measure_separates_variants_from_unrelated_texts() -> None:
    base = normalize_text("Your parcel is held, pay the redelivery fee at the link today")
    variant = normalize_text("Your parcel is held. Pay the redelivery fee at the link now")
    other = normalize_text("Are we still meeting for lunch near the station tomorrow")
    assert jaccard(shingles(base), shingles(variant)) >= 0.7
    assert jaccard(shingles(base), shingles(other)) < 0.3


def test_every_simulator_sms_text_is_fingerprinted_from_the_packaged_catalog() -> None:
    assert SIMULATOR_CATALOG.exists()
    texts = simulator_texts()
    assert len(texts) >= 10 and all(t.startswith("[SIMULATED]") for t in texts)
    assert simulator_fingerprints() == {text_fingerprint(t) for t in texts}
    assert simulator_overlap(texts) == len(texts)


def test_fixture_texts_are_caught_even_after_formatting_changes() -> None:
    text = sorted(simulator_texts())[0]
    disguised = text.upper().replace(" ", "  ")
    assert simulator_overlap([disguised, "an unrelated benign message about lunch"]) == 1
    assert simulator_overlap(["hello there", "call me back", "your parcel has shipped"]) == 0
