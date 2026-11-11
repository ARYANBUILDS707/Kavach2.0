"""A small, blinded calibration pilot run before the main label audit.

Both reviewers label the same ~40 items independently, using the same rubric as the audit. The
pilot measures agreement (Cohen's kappa), control accuracy and which rubric points cause
disagreement, so the rubric or the reviewers can be calibrated *before* the 2,970 audit reviews.

The pilot never feeds the gate: its items are drawn from clusters that are not in the audit
sample (so discussing a pilot item cannot bias an audit answer), its results are written to a
separate report, and it promotes nothing. The software writes blank sheets only; it never
fills, guesses or checks a label against an "expected" answer except for the known-provenance
controls, exactly as in the audit.
"""

import hashlib
import json
from collections import Counter
from pathlib import Path

from sms_prep.clusters import ClusterInfo
from sms_prep.records import Record
from sms_prep.review import (
    REVIEWER_COLUMNS,
    RUBRIC,
    RUBRIC_VERSION,
    ReviewItem,
    cohen_kappa,
    display_text,
    draw,
    item_id,
    order_key,
    parse_review_sheet,
    read_sheet,
    representatives,
    reviewer_quality,
    write_csv,
)

PILOT_SHEETS = ("pilot_A.csv", "pilot_B.csv")
# kind -> (class/stratum label, source, size). hey mum/dad has no clusters left outside the
# audit sample (all 45 are audited) and UCI spam with links likewise (all 80), so neither appears.
PILOT_PLAN: tuple[tuple[str, str, str, int], ...] = (
    ("gated", "banking", "imc", 6),
    ("gated", "others", "imc", 6),
    ("gated", "delivery", "imc", 4),
    ("gated", "government", "imc", 4),
    ("gated", "telecom", "imc", 4),
    ("gated", "wrong number", "imc", 4),
    ("composition_imc_spam", "spam", "imc", 4),
    ("control_uci_ham", "ham", "uci", 4),
    ("control_uci_spam", "spam", "uci", 4),
    ("synthetic_benign", "synthetic_benign", "synthetic", 4),
)
PILOT_SIZE_RANGE = (30, 50)
# Suggested readiness bar for starting the main review; the owner may set another.
SUGGESTED_MIN_KAPPA = 0.60
SUGGESTED_MIN_CONTROL_ACCURACY = 0.90

INSTRUCTIONS = """# KAVACH SMS review: calibration pilot

This pilot comes **before** the main label review. It checks that two reviewers apply
`RUBRIC.md` the same way. Its answers are never used to approve or reject any class.

## Who

Reviewer A, Reviewer B, and later an adjudicator who is neither of them: the same three people
who will do the main review.

## Steps

1. Read `RUBRIC.md` fully.
2. Reviewer A labels every row of `pilot_A.csv`; Reviewer B labels every row of `pilot_B.csv`.
   Work alone: do not discuss items, compare answers, look messages up, open links, or use any
   automatic classifier or language model. Write one label from the rubric in `label` and your
   personal reviewer ID in `reviewer` on every row (the same ID on all your rows). Leave a row
   blank rather than guess, and use `notes` for anything unclear about the rubric.
3. When both sheets are complete, run `python -m sms_prep pilot-audit`. It reports agreement
   (Cohen's kappa), control accuracy, and writes `pilot_disagreements.csv` (text and both
   labels, not who gave them).
4. All three meet and go through the disagreements against the rubric. Record any rubric
   clarification as a proposed change; do not edit labels in the main review sheets.
5. The owner decides whether to start the main review. The suggested bar is kappa >= 0.60 on
   all pilot items and control accuracy >= 90% for each reviewer.

The pilot items are drawn from messages that are not in the main review, so the discussion in
step 4 cannot give away a main-review answer. Keep these files private; they contain message
text.
"""


def select_pilot(
    records: list[Record], infos: list[ClusterInfo], main_key: dict, seed: int
) -> list[ReviewItem]:
    """Pilot items from clusters outside the audit sample, stratified by `PILOT_PLAN`."""
    used_clusters = {v["cluster_id"] for v in main_key.values()}
    used_records = {v["record_id"] for v in main_key.values()}
    items = []
    for kind, label, source, size in PILOT_PLAN:
        pool = [
            (cluster, record)
            for cluster, record in representatives(records, infos, label, source)
            if cluster not in used_clusters and record.record_id not in used_records
        ]
        for cluster, record in draw(pool, size, seed, f"pilot|{kind}|{label}"):
            klass = label if kind in ("gated", "synthetic_benign") else f"{source}_{label}"
            items.append(ReviewItem(item_id(seed, "pilot|" + record.record_id),
                                    record.record_id, kind, klass, cluster))  # fmt: skip
    return items


def build_pilot(
    records: list[Record], infos: list[ClusterInfo], main_key: dict, directory: Path, seed: int
) -> dict:
    by_id = {r.record_id: r for r in records}
    items = select_pilot(records, infos, main_key, seed)
    if not PILOT_SIZE_RANGE[0] <= len(items) <= PILOT_SIZE_RANGE[1]:
        raise ValueError(f"The pilot has {len(items)} items; expected {PILOT_SIZE_RANGE}")
    directory.mkdir(parents=True, exist_ok=True)
    for sheet in PILOT_SHEETS:
        rows = [
            {"item_id": i.item_id, "display_text": display_text(by_id[i.record_id].text),
             "label": "", "notes": "", "reviewer": ""}
            for i in sorted(items, key=lambda i: order_key(seed, "pilot" + sheet, i.item_id))
        ]  # fmt: skip
        write_csv(directory / sheet, REVIEWER_COLUMNS, rows)
    key = {
        i.item_id: {"record_id": i.record_id, "kind": i.kind, "class": i.klass,
                    "cluster_id": i.cluster_id}
        for i in items
    }  # fmt: skip
    (directory / "answer_key.json").write_text(json.dumps(key, indent=1, sort_keys=True) + "\n")
    (directory / "RUBRIC.md").write_text(RUBRIC)
    (directory / "INSTRUCTIONS.md").write_text(INSTRUCTIONS)
    meta = {
        "purpose": "calibration pilot; never used by the label-approval gate",
        "seed": seed,
        "items": len(items),
        "items_by_kind": dict(Counter(i.kind for i in items)),
        "gated_classes_covered": sorted({i.klass for i in items if i.kind == "gated"}),
        "rubric_version": RUBRIC_VERSION,
        "disjoint_from_main_audit_sample": True,
        "suggested_min_kappa": SUGGESTED_MIN_KAPPA,
        "suggested_min_control_accuracy": SUGGESTED_MIN_CONTROL_ACCURACY,
        "answer_key_sha256": hashlib.sha256(
            (directory / "answer_key.json").read_bytes()
        ).hexdigest(),
    }
    (directory / "bundle_meta.json").write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n")
    return meta


def pilot_has_annotations(directory: Path) -> bool:
    for name in PILOT_SHEETS:
        sheet = read_sheet(directory / name)
        for row in sheet[0] if sheet else []:
            if any((row.get(c) or "").strip() for c in ("label", "reviewer", "notes")):
                return True
    return False


def evaluate_pilot(directory: Path) -> dict:
    """Agreement and control accuracy. Status INCOMPLETE until both sheets are valid and full;
    then READY or CALIBRATE against the suggested bar. Writes the disagreement list."""
    key = json.loads((directory / "answer_key.json").read_text())
    meta = json.loads((directory / "bundle_meta.json").read_text())
    intact = (
        meta.get("answer_key_sha256")
        == hashlib.sha256((directory / "answer_key.json").read_bytes()).hexdigest()
    )
    key_ids = set(key)
    sheets = {n: parse_review_sheet(directory / n, key_ids) for n in PILOT_SHEETS}
    a, b = (sheets[n] for n in PILOT_SHEETS)
    independent = (
        len(a.reviewers) == 1 and len(b.reviewers) == 1 and not (a.reviewers & b.reviewers)
    )
    valid = all(
        not (p.missing or p.missing_columns or p.duplicate_rows or p.unknown_rows)
        for p in sheets.values()
    )
    complete = intact and valid and independent and set(a.labels) == set(b.labels) == key_ids
    both = sorted(key_ids & set(a.labels) & set(b.labels))
    disagreements = [i for i in both if a.labels[i] != b.labels[i]]
    text = {}
    sheet = read_sheet(directory / PILOT_SHEETS[0])
    if sheet:
        text = {r.get("item_id", "").strip(): r.get("display_text", "") for r in sheet[0]}
    write_csv(
        directory / "pilot_disagreements.csv",
        ("item_id", "display_text", "label_reviewer_a", "label_reviewer_b"),
        [{"item_id": i, "display_text": text.get(i, ""), "label_reviewer_a": a.labels[i],
          "label_reviewer_b": b.labels[i]} for i in disagreements],
    )  # fmt: skip
    quality = reviewer_quality(key, dict(zip(("pilot_A.csv", "pilot_B.csv"), (a, b), strict=True)))
    kappa = cohen_kappa([(a.labels[i], b.labels[i]) for i in both]) if both else None
    accuracies = [quality[n]["control_accuracy"] for n in PILOT_SHEETS]
    if not complete:
        status = "INCOMPLETE"
    elif (kappa or 0) >= SUGGESTED_MIN_KAPPA and all(
        x is not None and x >= SUGGESTED_MIN_CONTROL_ACCURACY for x in accuracies
    ):
        status = "READY"
    else:
        status = "CALIBRATE"
    return {
        "status": status,
        "used_by_gate": False,
        "progress": {
            "items": len(key),
            "reviewer_a_completed": len(a.labels),
            "reviewer_b_completed": len(b.labels),
            "reviewers_distinct_ids": independent,
            "answer_key_intact": intact,
            "sheets_valid": valid,
        },
        "agreement": {
            "items_compared": len(both),
            "agreements": len(both) - len(disagreements),
            "disagreements": len(disagreements),
            "cohen_kappa": kappa,
            "by_kind": {
                kind: {
                    "compared": sum(key[i]["kind"] == kind for i in both),
                    "disagreements": sum(key[i]["kind"] == kind for i in disagreements),
                }
                for kind in sorted({v["kind"] for v in key.values()})
            },
        },  # fmt: skip
        "reviewer_quality": quality,
        "suggested_bar": {
            "min_kappa": SUGGESTED_MIN_KAPPA,
            "min_control_accuracy": SUGGESTED_MIN_CONTROL_ACCURACY,
        },
    }
