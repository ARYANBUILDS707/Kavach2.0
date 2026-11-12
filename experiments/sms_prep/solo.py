"""Solo-reviewer evaluation of the pretrained SMS model (M4-Q).

One human reviewer labels a small, blinded, stratified sample with the existing rubric; the
pinned model is then scored offline on the same texts and the two are compared against criteria
registered *before* any label exists (`manifests/sms_solo_eval_criteria.v1.json`).

What this is not:
- It never replaces the independent two-reviewer plus adjudicator label-approval gate, which is
  unchanged and still blocked. A solo sample cannot establish production accuracy.
- It never writes a label. The sheet is created blank and only the human edits it.
- It never touches the held-out sets. Messages come only from records that sit in *train or
  validation in both* the frozen split v1 and the proposed split v2, so neither candidate test
  set is read, and a campaign (v2 cluster) that touches the audit or the pilot is excluded.
- It does not tune anything: the model is frozen, the thresholds are registered in advance, and
  selection never looks at a model output.

Collected and synthetic messages are drawn from separate pools and reported separately; they are
never pooled in a metric. Model outputs are the native, uncalibrated softmax values.
"""

import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from sms_prep.records import Record
from sms_prep.review import (
    LABELS,
    REVIEWER_COLUMNS,
    RUBRIC,
    RUBRIC_VERSION,
    Z95,
    display_text,
    item_id,
    order_key,
    parse_review_sheet,
    read_sheet,
    wilson_interval,
    write_csv,
)
from sms_prep.splits import Assignment

SOLO_SEED = 20261107
SHEET = "solo_review.csv"
KEY = "answer_key.json"
META = "bundle_meta.json"
CRITERIA_COPY = "criteria.json"
OUTPUTS = "model_outputs.json"
REPEATS = 10
SYNTHETIC_ITEMS = 24
READABLE = ("train", "validation")  # the only splits this module may draw from
MODEL_LABELS = ("legitimate", "spam", "fraud")  # the manifest's order
LABELS_MAPPED = tuple(label for label in LABELS if label != "unclear")
HUMAN_CLASSES = ("fraud", "spam", "legitimate")
# (source, label_key, items). IMC "others", "wrong number" and "hey mum/dad" are the ambiguous
# strata: the audit found their composition unknown or outside credential phishing.
PLAN_REV1: tuple[tuple[str, str, int], ...] = (
    ("imc", "banking", 20),
    ("imc", "delivery", 12),
    ("imc", "government", 12),
    ("imc", "telecom", 12),
    ("imc", "others", 16),
    ("imc", "wrong number", 6),
    ("imc", "hey mum/dad", 3),
    ("imc", "spam", 16),
    ("uci", "ham", 30),
    ("uci", "spam", 16),
)
# Revision 2 adds exactly 10 UCI ham campaigns: zero false alarms among 30 legitimate labels gives
# a Wilson upper bound of 0.1135, so the registered limit of 0.10 needs at least 35 (0.0989).
PLAN_REV2: tuple[tuple[str, str, int], ...] = tuple(
    (source, label, n + 10 if (source, label) == ("uci", "ham") else n)
    for source, label, n in PLAN_REV1
)


@dataclass(frozen=True)
class Revision:
    """One versioned bundle: its plan, private folder, registered criteria and status report.
    Revision 1 is kept as the original record and is never edited."""

    number: int
    plan: tuple[tuple[str, str, int], ...]
    folder: str
    criteria_file: str
    status_file: str


REVISIONS = {
    1: Revision(1, PLAN_REV1, "review_solo", "sms_solo_eval_criteria.v1.json",
                "solo_eval_status.json"),
    2: Revision(2, PLAN_REV2, "review_solo_v2", "sms_solo_eval_criteria.v2.json",
                "solo_eval_status.v2.json"),
}  # fmt: skip
CURRENT_REVISION = 2
AMBIGUOUS = {("imc", "others"), ("imc", "wrong number"), ("imc", "hey mum/dad")}

INSTRUCTIONS = """# KAVACH solo SMS review (M4-Q)

You are the only reviewer. Your labels are compared with the pretrained model afterwards, so
the model's answers are **not** in this folder and are not computed until you finish.

## What to do

1. Read `RUBRIC.md` once (the same rubric version 2 used for the main review).
2. Open `solo_review.csv` in a plain editor or spreadsheet. For every row write ONE label in the
   `label` column: `phishing`, `other_scam`, `spam`, `benign` or `unclear`. Put your name or
   initials in the `reviewer` column of every row you complete (the same text on all rows).
   Use `notes` for anything the rubric did not settle.
3. Work alone and in one sitting if you can. Do not look anything up, open links, ask a classifier
   or language model, or look at any model output. About 15 seconds a message is typical.
4. Leave a row blank rather than guess; blank rows are counted as unfinished. Use `unclear` only
   when the text is too short or garbled to apply the rubric.
5. Some messages appear twice under different IDs on purpose: label each on its own text without
   trying to remember the first answer. This measures your own consistency.
6. Save the file as CSV with the same name and columns. Do not add, delete or reorder columns, do
   not edit `item_id` or `display_text`, and do not rename the file.
7. Run `python -m sms_prep solo-evaluate`. While anything is unfinished it only reports progress.

## Rules the software enforces

- It never writes a label for you.
- The criteria for GO / CONDITIONAL / NO-GO are fixed in `criteria.json` (a copy of
  `experiments/manifests/{criteria}`) and cannot be changed after you label.
- The result is an experiment on one person's labels. It does not validate the model.
"""


class SoloError(Exception):
    """A refusal, with a message that never contains message text."""


@dataclass(frozen=True)
class SoloItem:
    item_id: str
    record_id: str
    kind: str  # collected | ambiguous | synthetic | repeat
    stratum: str
    origin: str  # collected | synthetic
    cluster_id: str  # v2 cluster (campaign)
    repeat_of: str = ""


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def hashed(seed: int, tag: str, value: str) -> str:
    return hashlib.sha256(f"solo|{seed}|{tag}|{value}".encode()).hexdigest()


def protected_clusters(
    keys: Sequence[dict], v2_cluster_of: dict[str, str]
) -> tuple[set[str], set[str]]:
    """(v1 cluster IDs, v2 cluster IDs) already used by the main audit or the pilot."""
    v1 = {entry["cluster_id"] for key in keys for entry in key.values()}
    records = {entry["record_id"] for key in keys for entry in key.values()}
    v2 = {v2_cluster_of[r] for r in records if r in v2_cluster_of}
    return v1, v2


def eligible_records(
    records: list[Record],
    v1: list[Assignment],
    v2: list[Assignment],
    protected_v1: set[str],
    protected_v2: set[str],
) -> list[tuple[Record, Assignment]]:
    """Candidate records in train/validation under BOTH splits and clear of the audit and pilot."""
    in_v1 = {a.record_id: a for a in v1 if a.split in READABLE}
    in_v2 = {a.record_id: a for a in v2 if a.split in READABLE}
    out = []
    for record in records:
        a1, a2 = in_v1.get(record.record_id), in_v2.get(record.record_id)
        if record.role != "candidate" or a1 is None or a2 is None:
            continue
        if a1.cluster_id in protected_v1 or a2.cluster_id in protected_v2:
            continue
        out.append((record, a2))
    return out


def pick(
    pool: list[tuple[Record, Assignment]], n: int, seed: int, tag: str, used: set[str]
) -> list:
    """One record per v2 cluster (one per campaign), chosen by a hash, at most n. Campaigns in
    `used` (already in the sample, from any stratum) are skipped, and the chosen ones are added."""
    best: dict[str, tuple[Record, Assignment]] = {}
    for record, assignment in pool:
        if assignment.cluster_id in used:
            continue
        current = best.get(assignment.cluster_id)
        if current is None or record.record_id < current[0].record_id:
            best[assignment.cluster_id] = (record, assignment)
    ordered = sorted(best.values(), key=lambda p: hashed(seed, tag, p[1].cluster_id))
    chosen = ordered[:n]
    used.update(a.cluster_id for _, a in chosen)
    return chosen


def synthetic_picks(
    pool: list[tuple[Record, Assignment]], n: int, seed: int, used: set[str]
) -> list:
    """Round-robin over template categories (otp_login, bank_debit, ...), one family each."""
    categories: dict[str, dict[str, tuple[Record, Assignment]]] = defaultdict(dict)
    for record, assignment in pool:
        family = record.group or record.record_id
        category = family.split("-")[0]
        current = categories[category].get(family)
        if current is None or record.record_id < current[0].record_id:
            categories[category][family] = (record, assignment)
    queues = {
        c: sorted(f.values(), key=lambda p: hashed(seed, "syn", p[0].group))
        for c, f in categories.items()
    }
    order = sorted(queues, key=lambda c: hashed(seed, "syn-cat", c))
    chosen: list = []
    while len(chosen) < n and any(queues.values()):
        for category in order:
            while queues[category] and len(chosen) < n:
                candidate = queues[category].pop(0)
                if candidate[1].cluster_id in used:
                    continue  # the same campaign is already in the sample
                used.add(candidate[1].cluster_id)
                chosen.append(candidate)
                break
    return chosen


def select_solo(
    records: list[Record],
    v1: list[Assignment],
    v2: list[Assignment],
    keys: Sequence[dict],
    seed: int = SOLO_SEED,
    revision: int = CURRENT_REVISION,
) -> tuple[list[SoloItem], dict]:
    v2_cluster_of = {a.record_id: a.cluster_id for a in v2}
    protected_v1, protected_v2 = protected_clusters(keys, v2_cluster_of)
    pool = eligible_records(records, v1, v2, protected_v1, protected_v2)
    items: list[SoloItem] = []
    available: dict[str, int] = {}
    used: set[str] = set()
    for source, label, n in REVISIONS[revision].plan:
        stratum = f"{source}:{label}"
        sub = [
            p
            for p in pool
            if p[0].source == source and p[0].label_key == label and p[0].origin == "collected"
        ]
        available[stratum] = len({a.cluster_id for _, a in sub})
        kind = "ambiguous" if (source, label) in AMBIGUOUS else "collected"
        for record, a in pick(sub, n, seed, stratum, used):
            items.append(
                SoloItem(
                    item_id(seed, record.record_id),
                    record.record_id,
                    kind,
                    stratum,
                    "collected",
                    a.cluster_id,
                )
            )
    synthetic = [p for p in pool if p[0].origin == "synthetic"]
    available["synthetic"] = len({p[0].group for p in synthetic})
    for record, a in synthetic_picks(synthetic, SYNTHETIC_ITEMS, seed, used):
        items.append(
            SoloItem(
                item_id(seed, record.record_id),
                record.record_id,
                "synthetic",
                f"synthetic:{record.group.split('-')[0]}",
                "synthetic",
                a.cluster_id,
            )
        )
    firsts = sorted(items, key=lambda i: hashed(seed, "repeat", i.record_id))[:REPEATS]
    for original in firsts:
        items.append(
            SoloItem(
                item_id(seed, "repeat|" + original.record_id),
                original.record_id,
                "repeat",
                original.stratum,
                original.origin,
                original.cluster_id,
                original.item_id,
            )
        )
    if len({i.item_id for i in items}) != len(items):
        raise SoloError("duplicate item IDs")
    return items, {
        "eligible_records": len(pool),
        "clusters_available_by_stratum": available,
        "excluded_audit_pilot_v1_clusters": len(protected_v1),
        "excluded_audit_pilot_v2_clusters": len(protected_v2),
    }


def build_solo(
    records: list[Record],
    v1: list[Assignment],
    v2: list[Assignment],
    keys: Sequence[dict],
    criteria_path: Path,
    directory: Path,
    seed: int = SOLO_SEED,
    revision: int = CURRENT_REVISION,
) -> dict:
    """Write the blank sheet, the private answer key, the rubric, the instructions and the
    registered criteria. No label and no model output is created."""
    by_id = {r.record_id: r for r in records}
    items, selection = select_solo(records, v1, v2, keys, seed, revision)
    directory.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "item_id": i.item_id,
            "display_text": display_text(by_id[i.record_id].text),
            "label": "",
            "notes": "",
            "reviewer": "",
        }
        for i in sorted(items, key=lambda i: order_key(seed, "solo", i.item_id))
    ]
    write_csv(directory / SHEET, REVIEWER_COLUMNS, rows)
    key = {
        i.item_id: {
            "record_id": i.record_id,
            "kind": i.kind,
            "stratum": i.stratum,
            "origin": i.origin,
            "cluster_id": i.cluster_id,
            "repeat_of": i.repeat_of,
        }
        for i in items
    }
    (directory / KEY).write_text(json.dumps(key, indent=1, sort_keys=True) + "\n")
    (directory / "RUBRIC.md").write_text(RUBRIC)
    (directory / "INSTRUCTIONS.md").write_text(
        INSTRUCTIONS.replace("{criteria}", REVISIONS[revision].criteria_file)
    )
    (directory / CRITERIA_COPY).write_bytes(criteria_path.read_bytes())
    meta = {
        "purpose": "solo-reviewer experiment; never used by the label-approval gate",
        "revision": revision,
        "seed": seed,
        "rows": len(items),
        "items_by_kind": dict(Counter(i.kind for i in items)),
        "items_by_stratum": dict(
            sorted(Counter(i.stratum for i in items if i.kind != "repeat").items())
        ),
        "origins_are_reported_separately": True,
        "drawn_only_from": "train or validation under both frozen split v1 and proposed split v2",
        "disjoint_from": "the main audit sample and the calibration pilot (records and campaigns)",
        "selection": selection,
        "rubric_version": RUBRIC_VERSION,
        "answer_key_sha256": sha256_file(directory / KEY),
        "criteria_sha256": sha256_file(criteria_path),
        "model_output_present": False,
    }
    (directory / META).write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n")
    return meta


def sheet_has_annotations(directory: Path) -> bool:
    sheet = read_sheet(directory / SHEET)
    return bool(
        sheet
        and any(
            (row.get(c) or "").strip() for row in sheet[0] for c in ("label", "reviewer", "notes")
        )
    )


# --- progress and evaluation -------------------------------------------------------------------


def load_bundle(directory: Path, criteria_path: Path) -> tuple[dict, dict, dict, list[str]]:
    """(key, meta, criteria, integrity problems). Problems are fixed texts, never content."""
    try:
        key = json.loads((directory / KEY).read_text())
        meta = json.loads((directory / META).read_text())
        copy = (directory / CRITERIA_COPY).read_bytes()
        criteria = json.loads(copy)
    except (OSError, ValueError):
        raise SoloError("The solo bundle is missing or unreadable; run solo-prepare") from None
    problems = []
    if sha256_file(directory / KEY) != meta.get("answer_key_sha256"):
        problems.append("the answer key was changed after the sample was prepared")
    if hashlib.sha256(copy).hexdigest() != meta.get("criteria_sha256"):
        problems.append("the bundle's criteria copy was changed")
    if criteria_path.exists() and sha256_file(criteria_path) != meta.get("criteria_sha256"):
        problems.append(
            "the registered criteria file differs from the one the sample was built with"
        )
    return key, meta, criteria, problems


def read_labels(directory: Path, key: dict) -> tuple[dict[str, str], dict]:
    """Valid labels by item ID plus a progress summary. Reads only the sheet the human edits."""
    key_ids = set(key)
    parsed = parse_review_sheet(directory / SHEET, key_ids)
    sheet = read_sheet(directory / SHEET)
    present = {(r.get("item_id") or "").strip() for r in sheet[0]} if sheet else set()
    problems = []
    if parsed.missing:
        problems.append("the sheet is missing")
    if parsed.missing_columns:
        problems.append("required columns are missing")
    if parsed.duplicate_rows or parsed.unknown_rows:
        problems.append("rows were duplicated or added")
    if key_ids - present:
        problems.append("rows were deleted")
    if len(parsed.reviewers) > 1:
        problems.append("more than one reviewer name is used")
    progress = {
        "rows": len(key_ids),
        "labeled": len(parsed.labels),
        "unfinished": len(key_ids) - len(parsed.labels),
        "reviewer_names_used": len(parsed.reviewers),
        "problems": problems,
    }
    return parsed.labels, progress


def rate(k: int, n: int) -> dict:
    if n <= 0:
        return {"k": k, "n": n, "rate": None, "wilson95": None}
    lo, hi = wilson_interval(k, n, Z95)
    return {"k": k, "n": n, "rate": round(k / n, 4), "wilson95": [round(lo, 4), round(hi, 4)]}


def top_label(probabilities: Sequence[float]) -> str:
    return MODEL_LABELS[max(range(len(probabilities)), key=probabilities.__getitem__)]


def one_vs_rest(matrix: dict[str, Counter], target: str) -> dict:
    total = sum(sum(row.values()) for row in matrix.values())
    tp = matrix[target][target]
    fn = sum(matrix[target].values()) - tp
    fp = sum(matrix[h][target] for h in matrix if h != target)
    tn = total - tp - fn - fp
    return {
        "precision": rate(tp, tp + fp),
        "recall": rate(tp, tp + fn),
        "false_positive_rate": rate(fp, fp + tn),
    }


def pool_metrics(rows: list[dict]) -> dict:
    """Metrics for one origin. Each row: human_label, human (mapped class), model, stratum."""
    matrix = {h: Counter() for h in HUMAN_CLASSES}
    for r in rows:
        matrix[r["human"]][r["model"]] += 1
    sizes = {h: sum(matrix[h].values()) for h in HUMAN_CLASSES}
    fraud_rows = [r for r in rows if r["human"] == "fraud"]
    by_label = {
        lab: rate(
            sum(r["model"] == "fraud" for r in fraud_rows if r["human_label"] == lab),
            sum(r["human_label"] == lab for r in fraud_rows),
        )
        for lab in ("phishing", "other_scam")
    }
    unwanted = sizes["fraud"] + sizes["spam"]
    flagged = sum(matrix[h][m] for h in ("fraud", "spam") for m in ("fraud", "spam"))
    both = [r for r in rows if r["human"] != "legitimate" and r["model"] != "legitimate"]
    strata: dict[str, dict] = {}
    for r in rows:
        cell = strata.setdefault(r["stratum"], {"n": 0, "human": Counter(), "model": Counter()})
        cell["n"] += 1
        cell["human"][r["human_label"]] += 1
        cell["model"][r["model"]] += 1
    return {
        "denominators": {h: sizes[h] for h in HUMAN_CLASSES} | {"total": len(rows)},
        "confusion_rows_human_columns_model": {
            h: {m: matrix[h][m] for m in MODEL_LABELS} for h in HUMAN_CLASSES
        },
        "per_class_one_vs_rest": {c: one_vs_rest(matrix, c) for c in HUMAN_CLASSES},
        "fraud_versus_spam": {
            "spam_labeled_fraud": rate(matrix["spam"]["fraud"], sizes["spam"]),
            "fraud_labeled_spam": rate(matrix["fraud"]["spam"], sizes["fraud"]),
            "right_class_when_both_say_unwanted": rate(
                sum((r["human"] == "fraud") == (r["model"] == "fraud") for r in both), len(both)
            ),
        },
        "unwanted_versus_legitimate": {
            "unwanted_flagged_unwanted": rate(flagged, unwanted),
            "legitimate_flagged_unwanted": rate(
                matrix["legitimate"]["fraud"] + matrix["legitimate"]["spam"], sizes["legitimate"]
            ),
        },
        "fraud_recall_by_human_label": by_label,
        "by_stratum": {
            s: {"n": c["n"], "human_labels": dict(c["human"]), "model_top_label": dict(c["model"])}
            for s, c in sorted(strata.items())
        },
    }


def stat(r: dict, which: str) -> float | None:
    """A rate's point value, or one end of its Wilson interval; None when undefined."""
    if r["rate"] is None:
        return None
    return {"rate": r["rate"], "lower": r["wilson95"][0], "upper": r["wilson95"][1]}[which]


def decide(
    criteria: dict, collected: dict, synthetic: dict, completeness: dict, repeat: dict
) -> dict:
    """The registered decision rules, applied mechanically.

    A value that cannot be computed (an empty denominator) never passes a GO check and never
    triggers a NO-GO rule.
    """
    go, no_go = criteria["go"]["all_required"], criteria["no_go"]["any_of"]
    fraud = collected["per_class_one_vs_rest"]["fraud"]
    fvs = collected["fraud_versus_spam"]
    legit = collected["confusion_rows_human_columns_model"]["legitimate"]
    legit_fraud = rate(legit["fraud"], collected["denominators"]["legitimate"])
    syn_fraud = synthetic["synthetic_fraud_on_benign"]
    # (name, rate, statistic, "min" | "max", registered threshold)
    go_rules = [
        (
            "fraud recall, Wilson lower",
            fraud["recall"],
            "lower",
            "min",
            go["fraud_recall_wilson_lower_at_least"],
        ),
        (
            "fraud precision, Wilson lower",
            fraud["precision"],
            "lower",
            "min",
            go["fraud_precision_wilson_lower_at_least"],
        ),
        (
            "legitimate flagged fraud, Wilson upper",
            legit_fraud,
            "upper",
            "max",
            go["fraud_false_positive_rate_on_legitimate_wilson_upper_at_most"],
        ),
        (
            "synthetic benign flagged fraud, Wilson upper",
            syn_fraud,
            "upper",
            "max",
            go["synthetic_fraud_rate_on_benign_wilson_upper_at_most"],
        ),
        (
            "fraud labeled spam, rate",
            fvs["fraud_labeled_spam"],
            "rate",
            "max",
            go["fraud_labeled_spam_rate_at_most"],
        ),
        (
            "spam labeled fraud, rate",
            fvs["spam_labeled_fraud"],
            "rate",
            "max",
            go["spam_labeled_fraud_rate_at_most"],
        ),
        (
            "reviewer repeat agreement",
            repeat if repeat["n"] >= 5 else rate(0, 0),
            "rate",
            "min",
            go["reviewer_repeat_agreement_at_least"],
        ),
    ]
    checks = []
    for name, r, which, direction, limit in go_rules:
        value = stat(r, which)
        passed = value is not None and (value >= limit if direction == "min" else value <= limit)
        checks.append({"check": name, "value": value, "threshold": limit, "passed": passed})
    no_go_rules = [
        (
            "fraud recall, Wilson upper below",
            fraud["recall"],
            "upper",
            "below",
            no_go["fraud_recall_wilson_upper_below"],
        ),
        (
            "fraud precision, Wilson upper below",
            fraud["precision"],
            "upper",
            "below",
            no_go["fraud_precision_wilson_upper_below"],
        ),
        (
            "legitimate flagged fraud, Wilson lower above",
            legit_fraud,
            "lower",
            "above",
            no_go["fraud_false_positive_rate_on_legitimate_wilson_lower_above"],
        ),
        (
            "synthetic benign flagged fraud, Wilson lower above",
            syn_fraud,
            "lower",
            "above",
            no_go["synthetic_fraud_rate_on_benign_wilson_lower_above"],
        ),
    ]
    fired = []
    for name, r, which, direction, limit in no_go_rules:
        value = stat(r, which)
        if value is not None and (value < limit if direction == "below" else value > limit):
            fired.append(name)
    mins, den = criteria["minimum_denominators_collected"], collected["denominators"]
    short = [
        key
        for key, have in (
            ("human_fraud", den["fraud"]),
            ("human_spam", den["spam"]),
            ("human_legitimate", den["legitimate"]),
        )
        if have < mins[key]
    ]
    caps = []
    if short:
        caps.append("too few collected labels in: " + ", ".join(short))
    syn_min = criteria.get("minimum_denominators_synthetic", {}).get("human_legitimate")
    if syn_min is not None and synthetic["denominators"]["legitimate"] < syn_min:
        caps.append("too few synthetic benign labels")
    if completeness["unclear_share"] > criteria["completeness"]["max_unclear_share"]:
        caps.append("too many unclear labels")
    failed = [c["check"] for c in checks if not c["passed"]]
    if fired:
        verdict, meaning = "NO-GO", criteria["no_go"]["meaning"]
    elif not failed and not caps:
        verdict, meaning = "GO", criteria["go"]["meaning"]
    else:
        verdict, meaning = "CONDITIONAL", criteria["conditional"]["meaning"]
    return {
        "verdict": verdict,
        "meaning": meaning,
        "no_go_rules_fired": fired,
        "go_checks": checks,
        "go_checks_failed": failed,
        "caps": caps,
    }


def evaluate_solo(
    directory: Path,
    criteria_path: Path,
    score: Callable[[list[str]], list[list[float]]],
    shown_texts: dict[str, str],
    raw_texts: dict[str, str],
    model_info: dict,
) -> dict:
    """Compare completed labels with model outputs. Raises SoloError unless the labels are
    complete and the bundle intact; scores only then, so no output exists while labeling."""
    key, meta, criteria, problems = load_bundle(directory, criteria_path)
    labels, progress = read_labels(directory, key)
    problems = problems + progress["problems"]
    n_rows = len(key)
    labeled_share = len(labels) / n_rows
    if problems:
        raise SoloError("integrity: " + "; ".join(problems))
    if labeled_share < criteria["completeness"]["min_labeled_share"]:
        raise SoloError(f"incomplete: {len(labels)} of {n_rows} rows labeled")
    ids = sorted(i for i, e in key.items() if e["kind"] != "repeat")
    shown = score([shown_texts[i] for i in ids])
    raw = score([raw_texts[i] for i in ids])
    outputs = {
        "model": model_info,
        "score_semantics": "uncalibrated_softmax",
        "labels_order": list(MODEL_LABELS),
        "items": {
            i: {"shown": [round(p, 6) for p in a], "raw": [round(p, 6) for p in b]}
            for i, a, b in zip(ids, shown, raw, strict=True)
        },
    }
    (directory / OUTPUTS).write_text(json.dumps(outputs, indent=1, sort_keys=True) + "\n")
    mapping = criteria["human_to_model_class"]

    def rows_for(origin: str, variant: str) -> list[dict]:
        rows = []
        for i in ids:
            entry, label = key[i], labels.get(i)
            if entry["origin"] != origin or label is None or label not in mapping:
                continue
            rows.append(
                {
                    "human_label": label,
                    "human": mapping[label],
                    "model": top_label(outputs["items"][i][variant]),
                    "stratum": entry["stratum"],
                }
            )
        return rows

    collected, synthetic = (pool_metrics(rows_for(o, "shown")) for o in ("collected", "synthetic"))
    syn_rows = rows_for("synthetic", "shown")
    benign = [r for r in syn_rows if r["human"] == "legitimate"]
    synthetic["synthetic_fraud_on_benign"] = rate(
        sum(r["model"] == "fraud" for r in benign), len(benign)
    )
    synthetic["synthetic_spam_on_benign"] = rate(
        sum(r["model"] == "spam" for r in benign), len(benign)
    )
    unclear = sum(labels.get(i) == "unclear" for i in key)
    completeness = {
        "rows": n_rows,
        "labeled": len(labels),
        "labeled_share": round(labeled_share, 4),
        "unclear": unclear,
        "unclear_share": round(unclear / max(1, len(labels)), 4),
    }
    pairs = [
        (labels.get(i), labels.get(e["repeat_of"])) for i, e in key.items() if e["kind"] == "repeat"
    ]
    usable = [(a, b) for a, b in pairs if a in mapping and b in mapping]
    repeat = rate(sum(a == b for a, b in usable), len(usable))
    repeat["pairs_total"] = len(pairs)
    decision = decide(criteria, collected, synthetic, completeness, repeat)
    return {
        "status": decision["verdict"],
        "decision": decision,
        "disclaimer": (
            "One reviewer, a small sample, cluster-uniform sampling: rates are not prevalence "
            "or production accuracy. Scores are uncalibrated. The independent two-reviewer "
            "label gate is unchanged and still decides what may be called validated."
        ),
        "model": model_info,
        "criteria_version": criteria["criteria_version"],
        "criteria_sha256": meta["criteria_sha256"],
        "completeness": completeness,
        "reviewer_repeat_agreement": repeat,
        "collected": collected,
        "synthetic": synthetic,
        "secondary_raw_text_collected": pool_metrics(rows_for("collected", "raw"))[
            "per_class_one_vs_rest"
        ],
        "items_scored": len(ids),
        "selection": meta["selection"],
    }
