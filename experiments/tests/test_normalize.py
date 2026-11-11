"""Feature normalization must give every source the same view of URLs, placeholders, phone
numbers and dates, so a dataset-specific marker cannot become a label."""

import pytest

from sms_prep.normalize import FEATURE_NORMALIZATION_VERSION, feature_normalize


def test_url_forms_from_every_source_become_one_token() -> None:
    forms = [
        "click http://evil.example.invalid/x?a=1 now",
        "click HTTPS://EVIL.example.invalid now",
        "click www.evil.example.invalid/pay now",
        "click evil-site.example.invalid now",
        "click <URL> now",
        "click <url> now",
        "click hxxps://evil.example.invalid now",
        "click [URL maliciosa] now",
        "click [URL] now",
    ]
    assert {feature_normalize(f) for f in forms} == {"click <url> now"}


def test_glued_placeholders_do_not_leave_markers() -> None:
    assert feature_normalize("go to <URL>in an hour") == "go to <url> in an hour"


def test_recognizer_placeholders_are_neutralized() -> None:
    text = (
        "Dear <NAMED_ENTITY>, your <US_BANK_NUMBER> at <LOCATION> on <DATE_TIME> "
        "call <PHONE_NUMBER> or <EMAIL_ADDRESS>"
    )
    assert feature_normalize(text) == "Dear , your at on <datetime> call <phone> or <email>"
    for name in ("NAMED_ENTITY", "LOCATION", "NRP", "US_DRIVER_LICENSE", "UK_NHS", "IP_ADDRESS"):
        assert "<" not in feature_normalize(f"x <{name}> y")


@pytest.mark.parametrize("marker", ["[REDACTED]", "[redacted]", "[Name]"])
def test_redaction_markers_are_removed(marker: str) -> None:
    assert feature_normalize(f"hello {marker} there") == "hello there"


def test_phone_numbers_emails_and_control_characters() -> None:
    assert feature_normalize("call 0871 872 9758 now") == "call <phone> now"
    assert feature_normalize("call +44 7700 900123 now") == "call <phone> now"
    assert feature_normalize("mail me@example.invalid please") == "mail <email> please"
    assert feature_normalize("ver\u200bify\u00ad now") == "verify now"
    assert feature_normalize("a\x00b\x07c") == "a b c"


@pytest.mark.parametrize(
    "form",
    [
        "pay by 14:30 today",
        "pay by 2:30 pm tomorrow",
        "pay by <DATE_TIME>",
        "pay by 02/09/2003",
        "pay by March 3rd",
        "pay by Friday",
        "pay by 5pm",
    ],
)
def test_dates_and_relative_times_are_one_token_in_every_source(form: str) -> None:
    assert feature_normalize(form) == "pay by <datetime>"
    assert feature_normalize("pay within 2 hours") == "pay within <datetime>"


def test_the_verb_may_is_not_a_month() -> None:
    assert feature_normalize("you may win") == "you may win"
    assert feature_normalize("by May 5") == "by <datetime>"


def test_case_digits_and_punctuation_are_kept_as_signals() -> None:
    assert feature_normalize("URGENT!! Your code is 4829.") == "URGENT!! Your code is 4829."


def test_the_same_message_normalizes_identically_across_sources() -> None:
    imc_style = "Your <NAMED_ENTITY> parcel is held. Pay at <URL> before <DATE_TIME>."
    plain_style = "Your parcel is held. Pay at http://pay.example.invalid/x before 18:00."
    assert feature_normalize(imc_style) == feature_normalize(plain_style)


def test_normalization_is_idempotent_and_versioned() -> None:
    text = "Hi <NAMED_ENTITY>, visit www.a.example.invalid at 9:15 or call 555 0100 1234"
    once = feature_normalize(text)
    assert feature_normalize(once) == once
    assert FEATURE_NORMALIZATION_VERSION == 2
