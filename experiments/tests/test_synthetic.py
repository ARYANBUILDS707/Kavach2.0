"""The synthetic hard negatives must be safe, fictional, deterministic and separate."""

import re

from dataset_governance.fingerprints import normalize_text, simulator_overlap
from dataset_governance.manifest import load_manifest
from sms_prep import synthetic

REAL_BRANDS = [
    "paypal", "amazon", "apple", "google", "fedex", "dhl", "usps", "royal mail", "hdfc", "sbi",
    "icici", "paytm", "visa", "mastercard", "netflix", "microsoft", "irs", "hsbc", "barclays",
    "wells fargo", "bank of america", "chase", "citibank", "lloyds", "natwest", "santander",
    "whatsapp", "facebook", "instagram", "telegram", "aadhaar", "evri", "tesco", "walmart",
    "ebay", "uber", "airtel", "vodafone", "o2", "verizon", "at&t", "t-mobile",
]  # fmt: skip
URL = re.compile(r"https?://[^\s]+")
PHONE = re.compile(r"\b\d{3}-\d{4}\b")


def test_generation_is_deterministic_and_matches_the_manifest() -> None:
    first, second = synthetic.generate(), synthetic.generate()
    assert first == second
    (record,) = load_manifest().synthetic_sets
    assert synthetic.corpus_sha256(first) == record.corpus_sha256
    assert (len(first), len(synthetic.template_ids())) == (record.records, record.template_families)
    assert synthetic.corpus_sha256(synthetic.generate(seed=1)) != record.corpus_sha256


def test_the_corpus_is_varied() -> None:
    messages = synthetic.generate()
    assert len(synthetic.TEMPLATES) == 12
    assert all(len(t) == 6 for t in synthetic.TEMPLATES.values())
    assert len({m.template_id for m in messages}) == 72
    assert len({normalize_text(m.text) for m in messages}) >= 700
    assert min(len(m.text) for m in messages) > 40


def test_everything_is_fictional_and_nonfunctional() -> None:
    for message in synthetic.generate():
        lowered = message.text.lower()
        for brand in REAL_BRANDS:
            assert re.search(rf"(?<![a-z]){re.escape(brand)}(?![a-z])", lowered) is None, brand
        for url in URL.findall(message.text):
            assert url.rstrip(".,)").split("/")[2].endswith(".invalid")
        assert "http://" not in lowered
        for phone in PHONE.findall(message.text):
            assert phone.startswith("555-01")
        assert "@" not in message.text


def test_no_simulator_text_and_no_marker_leaks_into_the_corpus() -> None:
    texts = [m.text for m in synthetic.generate()]
    assert simulator_overlap(texts) == 0
    assert not any("[SIMULATED]" in t for t in texts)  # no marker a model could learn


def test_benign_hard_negatives_really_share_phishing_surface_cues() -> None:
    texts = [m.text.lower() for m in synthetic.generate()]
    assert sum(".invalid" in t for t in texts) > 100  # links
    assert sum("expires" in t or "valid for" in t for t in texts) > 50  # urgency
    assert sum("not you" in t or "did not" in t for t in texts) > 20  # "if this was not you"
    assert sum("do not share" in t or "never share" in t or "never ask" in t for t in texts) > 20
