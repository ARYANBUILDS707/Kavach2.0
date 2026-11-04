"""Feature normalization: what a model is allowed to see.

Deliberately separate from `dataset_governance.fingerprints.normalize_text`, which is an
aggressive matching normalization for duplicate and contamination checks only. This one keeps
case, punctuation and digits (useful signals) and only removes what must not be learned.

Why it is more than cosmetics: the IMC dataset was anonymized with an entity recognizer, so 82%
of its rows carry placeholders such as `<NAMED_ENTITY>`, `<DATE_TIME>`, `<LOCATION>` and
`<PHONE_NUMBER>`, and many replace URLs with `<URL>`. No other source has them, so a model
could learn "contains a placeholder" as "phishing". The same function therefore runs on every
source (and at inference), and it:

- maps URLs, URL placeholders, emails, phone numbers and dates/times to one fixed token each,
  whatever their source spelling (real dates and relative times are tokenized too, because the
  recognizer replaced them in IMC but not elsewhere);
- deletes every other entity placeholder (names, locations, identifiers) and redaction marker.

This is a best-effort neutralization, not a proof of equality: IMC lost its names and places
while UCI and the synthetic data keep theirs, and that asymmetry remains (M4.2 report).
M4.3 must test for it with a source-probe rather than assume it is gone.
"""

import re
import unicodedata

URL_TOKEN = "<url>"
EMAIL_TOKEN = "<email>"
PHONE_TOKEN = "<phone>"
DATETIME_TOKEN = "<datetime>"
FEATURE_NORMALIZATION_VERSION = 2

ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍⁠﻿­"))
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
# Recognizer placeholders: <URL>, <DATE_TIME>, <NAMED_ENTITY>, <US_DRIVER_LICENSE>, ...
ENTITY = re.compile(r"<([A-Za-z][A-Za-z_]{1,30})>")
ENTITY_TOKENS = {
    "url": URL_TOKEN,
    "phone_number": PHONE_TOKEN,
    "email_address": EMAIL_TOKEN,
    "date_time": DATETIME_TOKEN,
    # This function's own tokens, so that normalizing twice changes nothing.
    "phone": PHONE_TOKEN,
    "email": EMAIL_TOKEN,
    "datetime": DATETIME_TOKEN,
}
# Redaction markers written by reporters or by the dataset authors.
MARKER = re.compile(r"\[(redacted|url[^\]]{0,16}|name|phone|date)\]", re.IGNORECASE)
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
URL = re.compile(
    r"(?:https?://|hxxps?://|www\.)\S+"
    r"|\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|net|org|info|biz|xyz|top|club|online|site|link|click"
    r"|co|io|ly|me|cc|in|uk|us|invalid)(?:/\S*)?\b",
    re.IGNORECASE,
)
PHONE = re.compile(r"(?<!\w)\+?\d[\d\s().-]{7,}\d(?!\w)")
DATETIME = re.compile(
    r"\b\d{1,2}[:.]\d{2}\s?(?:am|pm)?\b"
    r"|\b\d{1,2}\s?(?:am|pm)\b"
    r"|\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b"
    r"|\b(?:mon|tues|wednes|thurs|fri|satur|sun)day\b"
    r"|\b(?:today|tomorrow|tonight|yesterday)\b"
    r"|\b(?:january|february|march|april|june|july|august|september|october|november|december)\b"
    r"(?:\s+\d{1,2}(?:st|nd|rd|th)?)?"
    r"|\bmay\s+\d{1,2}(?:st|nd|rd|th)?\b"
    r"|\b\d+\s?(?:hours?|hrs?|days?|minutes?|mins?|weeks?)\b",
    re.IGNORECASE,
)
DATETIME_RUN = re.compile(r"(?:<datetime>\s*){2,}")
SPACES = re.compile(r"\s+")


def replace_entity(match: re.Match[str]) -> str:
    return f" {ENTITY_TOKENS.get(match.group(1).lower(), '')} "


def replace_marker(match: re.Match[str]) -> str:
    return f" {URL_TOKEN} " if match.group(1).lower().startswith("url") else " "


def feature_normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).translate(ZERO_WIDTH)
    text = CONTROL.sub(" ", text)
    text = ENTITY.sub(replace_entity, text)
    text = MARKER.sub(replace_marker, text)
    text = EMAIL.sub(f" {EMAIL_TOKEN} ", text)
    text = URL.sub(f" {URL_TOKEN} ", text)
    text = PHONE.sub(f" {PHONE_TOKEN} ", text)
    text = DATETIME.sub(f" {DATETIME_TOKEN} ", text)
    text = DATETIME_RUN.sub(f" {DATETIME_TOKEN} ", text)  # "14:30 today" is one date-time
    return SPACES.sub(" ", text).strip()
