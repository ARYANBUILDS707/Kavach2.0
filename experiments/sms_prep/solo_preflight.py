"""Read-only preflight for the solo evaluation (M4-Q): is the sheet ready to be scored?

It reads the bundle and the sheet and nothing else. It never loads a model, never scores, never
writes a file, and its output holds only counts and fixed phrases: no message text, no item IDs
and no reviewer names. Each check is PASS, FAIL or NOT EVALUATED; a rate whose denominator is
zero is NOT EVALUATED, never 0% and never PASS. Only an all-PASS preflight is READY.
"""

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from sms_prep import solo
from sms_prep.review import read_sheet

PASS, FAIL, NOT_EVALUATED = "PASS", "FAIL", "NOT EVALUATED"
EXPECTED_ROWS = 183  # revision 2: 173 first-time items + 10 repeats
EXPECTED_REPEATS = 10
MIN_USABLE_PAIRS = 5  # the registered minimum (criteria: reviewer_repeat_agreement)


@dataclass(frozen=True)
class Check:
    status: str
    detail: str


def unclear_share_check(unclear: int, valid_labels: int, maximum: float) -> Check:
    """The registered share: `unclear` rows over all valid labels (repeat rows included)."""
    if valid_labels <= 0:
        return Check(NOT_EVALUATED, f"unclear share: no valid labels yet (maximum {maximum:.0%})")
    share = unclear / valid_labels
    status = PASS if share <= maximum else FAIL
    return Check(
        status, f"unclear labels: {unclear} of {valid_labels} ({share:.1%}; maximum {maximum:.0%})"
    )


def minimum_check(name: str, have: int, minimum: int) -> Check:
    return Check(PASS if have >= minimum else FAIL, f"{name}: {have} (minimum {minimum})")


def preflight(
    directory: Path, criteria_path: Path, expected_display: Callable[[str], str]
) -> list[Check]:
    """`expected_display(record_id)` is the prepared masked text, used only to detect an edited
    `display_text` cell; the text itself is compared in memory and never reported."""
    key, meta, criteria, problems = solo.load_bundle(directory, criteria_path)
    checks: list[Check] = []

    def add(ok: bool, text: str) -> None:
        checks.append(Check(PASS if ok else FAIL, text))

    add(not problems, f"bundle and hash integrity problems: {len(problems)}")
    add(
        solo.sha256_file(directory / solo.KEY) == meta.get("answer_key_sha256"),
        "answer key hash matches the bundle record",
    )
    add(
        solo.sha256_file(directory / solo.CRITERIA_COPY) == meta.get("criteria_sha256"),
        "bundle criteria copy hash matches the bundle record",
    )
    add(
        solo.sha256_file(criteria_path) == meta.get("criteria_sha256"),
        "registered criteria manifest hash matches the bundle record",
    )
    add(
        meta.get("revision") == 2 and criteria.get("criteria_version") == 2,
        "bundle is revision 2 with criteria version 2",
    )
    add(
        not (directory / solo.OUTPUTS).exists() and meta.get("model_output_present") is False,
        "no model output exists yet",
    )

    sheet = read_sheet(directory / solo.SHEET)
    rows = sheet[0] if sheet else []
    kinds = Counter(e["kind"] for e in key.values())
    add(
        len(rows) == EXPECTED_ROWS and len(key) == EXPECTED_ROWS,
        f"rows: sheet {len(rows)}, key {len(key)} (expected {EXPECTED_ROWS})",
    )
    add(
        kinds["repeat"] == EXPECTED_REPEATS,
        f"repeat rows in the key: {kinds['repeat']} (expected {EXPECTED_REPEATS})",
    )

    labels, progress = solo.read_labels(directory, key)
    add(not progress["problems"], f"sheet structure problems: {len(progress['problems'])}")
    add(len(labels) == len(key), f"valid labels: {len(labels)} of {len(key)}")
    repeats = [i for i, e in key.items() if e["kind"] == "repeat"]
    add(
        all(i in labels for i in repeats),
        f"repeat rows labeled: {sum(i in labels for i in repeats)} of {len(repeats)}",
    )
    add(
        all(key[i]["repeat_of"] in labels for i in repeats),
        "originals of the repeat rows labeled: "
        f"{sum(key[i]['repeat_of'] in labels for i in repeats)} of {len(repeats)}",
    )
    names = progress["reviewer_names_used"]
    if names == 0:
        checks.append(Check(NOT_EVALUATED, "reviewer name: no valid rows yet"))
    else:
        add(names == 1, f"distinct reviewer names on valid rows: {names} (expected 1)")
    unnamed = sum(
        1 for r in rows if (r.get("label") or "").strip() and not (r.get("reviewer") or "").strip()
    )
    add(unnamed == 0, f"rows with a label but no reviewer name: {unnamed}")
    edited = sum(
        1
        for r in rows
        if r.get("item_id") in key
        and r.get("display_text") != expected_display(key[r["item_id"]]["record_id"])
    )
    add(edited == 0, f"rows whose display text differs from the prepared text: {edited}")

    mapping = criteria["human_to_model_class"]
    counts = Counter(labels.values())
    checks.append(
        Check(
            PASS,
            "label counts, all rows: " + ", ".join(f"{k} {counts[k]}" for k in sorted(counts))
            if counts
            else "label counts, all rows: none",
        )
    )

    def count(origin: str, cls: str) -> int:
        return sum(
            1
            for i, label in labels.items()
            if key[i]["kind"] != "repeat"
            and key[i]["origin"] == origin
            and mapping.get(label) == cls
        )

    mins = criteria["minimum_denominators_collected"]
    for name, cls in (
        ("human_fraud", "fraud"),
        ("human_spam", "spam"),
        ("human_legitimate", "legitimate"),
    ):
        checks.append(minimum_check(f"collected {cls} labels", count("collected", cls), mins[name]))
    syn_min = criteria["minimum_denominators_synthetic"]["human_legitimate"]
    checks.append(
        minimum_check("synthetic benign labels", count("synthetic", "legitimate"), syn_min)
    )
    checks.append(
        unclear_share_check(
            sum(label == "unclear" for label in labels.values()),
            len(labels),
            criteria["completeness"]["max_unclear_share"],
        )
    )
    pairs = sum(
        1
        for i in repeats
        if labels.get(i) in mapping and labels.get(key[i]["repeat_of"]) in mapping
    )
    checks.append(
        minimum_check("usable repeat pairs (both labels not unclear)", pairs, MIN_USABLE_PAIRS)
    )
    return checks


def ready(checks: list[Check]) -> bool:
    return all(c.status == PASS for c in checks)


def summary_line(checks: list[Check]) -> str:
    """One line built from the same list that is printed, so the counts cannot drift from it."""
    tally = Counter(c.status for c in checks)
    not_passing = len(checks) - tally[PASS]
    verdict = "READY" if ready(checks) else f"NOT READY ({not_passing} checks not passing)"
    return (
        f"PREFLIGHT: {verdict}; {len(checks)} checks: "
        f"{tally[PASS]} PASS, {tally[FAIL]} FAIL, {tally[NOT_EVALUATED]} NOT EVALUATED"
    )
