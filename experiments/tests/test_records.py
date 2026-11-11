"""Record store: provenance, roles, provisional labels, and privacy of the public view."""

import json

import pytest

from sms_prep import records as rec
from sms_prep.synthetic import generate

IMC_COLUMNS = (
    "time,sender_id,telephone_number_type,original_network_name,original_network_country,"
    "text,translation,language,url_shortener,named_entity,scam_type,lure_principles"
)
IMC_HEADER = IMC_COLUMNS + "\n"


def imc_row(text: str, language: str, scam: str) -> str:
    return f',,,,,"{text}",,{language},,,{scam},\n'


def test_imc_roles_and_provisional_labels(tmp_path) -> None:
    path = tmp_path / "imc.csv"
    path.write_text(
        IMC_HEADER
        + imc_row("one", "English", "banking")
        + imc_row("two", "English", "spam")
        + imc_row("three", "English", "wrong number")
        + imc_row("four", "Spanish", "banking")
        + imc_row("five", "English", "")
    )
    r = rec.load_imc(path)
    assert [(x.role, x.label_key, x.provisional) for x in r] == [
        ("candidate", "banking", "needs_review"),
        ("candidate", "spam", "spam"),
        ("candidate", "wrong number", "needs_review"),
        ("experimental_non_english", "banking", "excluded"),
        ("excluded_unlabeled", "(empty)", "excluded"),
    ]
    assert all(x.origin == "collected" and x.source == "imc" for x in r)


def test_no_imc_row_is_ever_phishing_before_the_audit(tmp_path) -> None:
    path = tmp_path / "imc.csv"
    path.write_text(IMC_HEADER + "".join(imc_row(f"t{i}", "English", c) for i, c in enumerate(
        rec.IMC_SCOPE_CLASSES)))  # fmt: skip
    assert {x.provisional for x in rec.load_imc(path)} == {"needs_review"}


def test_uci_labels_stay_separate(tmp_path) -> None:
    path = tmp_path / "uci"
    path.write_text("ham\tsee you soon\nspam\tWIN a prize now\nham\tok\n")
    r = rec.load_uci(path)
    assert [(x.label_key, x.provisional, x.role) for x in r] == [
        ("ham", "benign", "candidate"),
        ("spam", "spam", "candidate"),
        ("ham", "benign", "candidate"),
    ]  # fmt: skip
    (tmp_path / "bad").write_text("smishing\tx\n")
    with pytest.raises(ValueError, match="Unexpected UCI label"):
        rec.load_uci(tmp_path / "bad")


def test_mishra_is_reference_only_and_smishing_needs_review(tmp_path) -> None:
    path = tmp_path / "m.csv"
    path.write_text(
        "LABEL,TEXT,URL,EMAIL,PHONE\nham,a,No,No,No\nspam,b,No,No,No\nsmishing,c,No,No,No\n"
    )
    r = rec.load_mishra(path)
    assert {x.role for x in r} == {"reference"}
    assert [x.provisional for x in r] == ["benign", "spam", "needs_review"]


def test_synthetic_records_carry_origin_and_template_group() -> None:
    r = rec.synthetic_records(generate(per_template=2))
    assert {x.origin for x in r} == {"synthetic"} and {x.provisional for x in r} == {"benign"}
    assert len({x.group for x in r}) == 72 and all(x.role == "candidate" for x in r)


def test_record_ids_are_stable_and_unique() -> None:
    assert rec.make_id("d", 1) == rec.make_id("d", 1) != rec.make_id("d", 2) != rec.make_id("e", 2)
    r = rec.synthetic_records(generate(per_template=2))
    assert len({x.record_id for x in r}) == len(r)


def test_public_view_and_repr_never_contain_the_text() -> None:
    r = rec.synthetic_records(generate(per_template=1))[0]
    assert "text" not in r.public() and r.text not in json.dumps(r.public())
    assert r.text not in repr(r)


def test_round_trip_and_checksum(tmp_path) -> None:
    r = rec.synthetic_records(generate(per_template=1))
    path = tmp_path / "work" / "records.jsonl"
    digest = rec.write_records(path, r)
    assert rec.read_records(path) == r
    assert rec.write_records(path, r) == digest


def test_overlong_text_is_capped(tmp_path) -> None:
    path = tmp_path / "imc.csv"
    path.write_text(IMC_HEADER + imc_row("x" * 20000, "English", "banking"))
    assert len(rec.load_imc(path)[0].text) == rec.MAX_TEXT_CHARS
