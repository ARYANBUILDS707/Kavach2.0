"""Manual label audit for the IMC classes (owner decision 6).

What this module does:
- builds a reproducible, stratified, blinded review bundle: one random representative per
  duplicate cluster per class, shuffled across classes, plus control messages with known
  provenance, with the class kept only in a private answer key;
- reads *completed human annotations* and computes class-level audited precision with Wilson
  intervals, and applies the promotion gate.

What it never does: write a label, guess a label, call a model or an LLM, or treat any
automatic judgment as a review. The review templates it writes have empty label columns. If
annotations are missing, partial or unadjudicated, the status is BLOCKED and no class can be
promoted. Nothing here certifies a label; the owner's gate is applied to the numbers that
completed human reviews produce.
"""

import csv
import hashlib
import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from sms_prep.clusters import ClusterInfo
from sms_prep.normalize import feature_normalize
from sms_prep.records import IMC_SCOPE_CLASSES, Record

LABELS = ("phishing", "other_scam", "spam", "benign", "unclear")
GATED_CLASSES = IMC_SCOPE_CLASSES
Z95 = 1.959963984540054
GATE_MINIMUM = 0.95
DEFAULT_PER_CLASS = 200
COMPOSITION_SIZES = {"composition_imc_spam": 100, "composition_uci_spam_link": 100}
CONTROL_SIZES = {"control_uci_ham": 40, "control_uci_spam": 20}
URL_HINT = re.compile(r"https?://|www\.|\b\w+\.(?:com|net|org|info|xyz|top|ly)\b", re.IGNORECASE)
LONG_DIGITS = re.compile(r"\d{6,}")
REVIEWER_COLUMNS = ("item_id", "display_text", "label", "notes", "reviewer")
ADJUDICATION_COLUMNS = ("item_id", "final_label", "adjudicator", "notes")
ADJUDICATION_QUEUE_COLUMNS = ("item_id", "display_text", "label_reviewer_a", "label_reviewer_b")

RUBRIC_VERSION = 2
RUBRIC = """# Label rubric for the KAVACH SMS review (version 2)

You will see short text messages, one per row, in a random order. You are not told where a
message came from or how it was filed. The text was machine-prepared: URLs, emails, phone
numbers and dates appear as `<url>`, `<email>`, `<phone>` and `<datetime>`; names, places and
long digit runs are removed or masked; some messages are truncated or garbled. Judge what is
left, as the recipient would.

## Decide in this order

1. Does the message try to get the recipient to *act*: click a link, call or text a number,
   reply, pay, install something, or hand over credentials or personal or financial data? Or
   does it announce an account, delivery, refund, prize or service problem that such an action
   would "fix"?
   - No: it is `benign` (a genuine alert, receipt, reminder or personal conversation) or
     `spam` (unsolicited promotion, marketing, quiz or nuisance with no account or payment
     pretext). Stop.
   - Yes: go to 2.
2. Does it pose as, or pretend to come from, an organisation or person the recipient may
   trust (bank, card issuer, carrier, courier, government body, utility, employer, platform,
   retailer) to get that action?
   - Yes: `phishing`. A real brand name is not needed and a real brand does not make it safe:
     judge the content. A message that states a problem and pushes an urgent action through a
     link or number is `phishing`.
   - No: go to 3.
3. Is it a fraud attempt anyway, such as a wrong-number opener, a romance or investment
   opener, someone claiming to be a relative with no organisation involved, an advance-fee or
   job scam?
   - Yes: `other_scam`.
   - No: `spam`.

`unclear` is only for text too short, garbled or cut off to apply the steps. It counts as
"not phishing" in the precision, so do not use it to avoid a hard call; guess only if you can
state a reason, otherwise leave `label` empty.

## Edge cases

- Prize, lottery or reward offers: `phishing` if they name or imitate an organisation AND ask
  you to call, click or give details; otherwise `spam`.
- A message that only delivers a one-time code and tells you not to share it is `benign`.
- A near-duplicate of an earlier row is still judged on its own text.
- Messages in a language you cannot read: leave `label` empty and say so in `notes`.

## Fictional examples (not from the data)

- "Your Arvelle Bank card is locked. Verify at <url> within <datetime>." -> `phishing`
- "Arvelle Bank: your statement is ready in the app." -> `benign`
- "Win a holiday! Text WIN to 80000 to enter. T&C apply." -> `spam`
- "Hi, is this Mark? We met at the conference." -> `other_scam` (a typical opener; asks nothing yet)
- "Mum, I lost my phone, send money to this account." -> `other_scam`
- "Parcel ref ZX41 held. Pay the fee at <url> to release it." -> `phishing`
- "See you at 7?" -> `benign`

## Rules of work

Work alone: do not discuss items or compare answers with the other reviewer. Do not look
messages up, open links, or use any automatic classifier or language model to decide. Put your
own reviewer ID in the `reviewer` column of every row you complete (one ID per sheet). Leave a
row blank rather than guess. Disagreements are resolved afterwards by an adjudicator who is
neither reviewer and who records `final_label`.
"""


def wilson_interval(successes: int, n: int, z: float = Z95) -> tuple[float, float]:
    if n <= 0 or not 0 <= successes <= n:
        raise ValueError("Need 0 <= successes <= n and n > 0")
    p = successes / n
    denominator = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denominator
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return max(0.0, centre - margin), min(1.0, centre + margin)


def min_correct_for_gate(n: int, minimum: float = GATE_MINIMUM, z: float = Z95) -> int | None:
    """Fewest correct positives out of n whose Wilson lower bound reaches `minimum`."""
    for k in range(n + 1):
        if n > 0 and wilson_interval(k, n, z)[0] >= minimum:
            return k
    return None


def smallest_passable_sample(minimum: float = GATE_MINIMUM, z: float = Z95) -> int:
    n = 1
    while wilson_interval(n, n, z)[0] < minimum:
        n += 1
    return n


def cohen_kappa(pairs: list[tuple[str, str]]) -> float | None:
    n = len(pairs)
    if n == 0:
        return None
    observed = sum(a == b for a, b in pairs) / n
    first, second = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    expected = sum(first[x] * second[x] for x in first) / (n * n)
    return 1.0 if expected == 1 else (observed - expected) / (1 - expected)


def item_id(seed: int, record_id: str) -> str:
    return "R" + hashlib.sha256(f"item|{seed}|{record_id}".encode()).hexdigest()[:10]


def order_key(seed: int, reviewer: str, item: str) -> str:
    return hashlib.sha256(f"order|{seed}|{reviewer}|{item}".encode()).hexdigest()


def display_text(text: str) -> str:
    """What a reviewer sees: feature-normalized, long digit runs masked."""
    shown = feature_normalize(text)
    return LONG_DIGITS.sub("<digits>", shown)


@dataclass(frozen=True)
class ReviewItem:
    item_id: str
    record_id: str
    kind: str  # gated | composition_* | control_*
    klass: str  # the answer-key class; never shown to reviewers
    cluster_id: str


def representatives(
    records: list[Record], infos: list[ClusterInfo], wanted: str, source: str
) -> list[tuple[str, Record]]:
    """(cluster_id, representative record) per ok cluster of a stratum, sorted by cluster ID."""
    by_id = {r.record_id: r for r in records}
    pool = []
    for info in infos:
        if info.status != "ok" or info.source != source or info.label_key != wanted:
            continue
        members = [by_id[rid] for rid in info.record_ids if by_id[rid].role == "candidate"]
        members = [m for m in members if m.source == source and m.label_key == wanted]
        if members:
            pool.append((info.cluster_id, min(members, key=lambda m: m.record_id)))
    return sorted(pool, key=lambda p: p[0])


def draw(pool: list[tuple[str, Record]], n: int, seed: int, tag: str) -> list[tuple[str, Record]]:
    keyed = sorted(
        pool, key=lambda p: hashlib.sha256(f"draw|{seed}|{tag}|{p[0]}".encode()).hexdigest()
    )
    return keyed[: min(n, len(keyed))]


def select_items(
    records: list[Record], infos: list[ClusterInfo], seed: int, per_class: int
) -> list[ReviewItem]:
    items = []

    def add(kind: str, klass: str, picks: list[tuple[str, Record]]) -> None:
        items.extend(
            ReviewItem(item_id(seed, r.record_id), r.record_id, kind, klass, cluster_id)
            for cluster_id, r in picks
        )

    def pool(label: str, source: str, link: bool | None = None) -> list[tuple[str, Record]]:
        found = representatives(records, infos, label, source)
        if link is None:
            return found
        return [p for p in found if bool(URL_HINT.search(p[1].text)) is link]

    for klass in GATED_CLASSES:
        add("gated", klass, draw(pool(klass, "imc"), per_class, seed, klass))
    plan = [
        ("composition_imc_spam", "imc_spam", pool("spam", "imc"), "cs"),
        ("composition_uci_spam_link", "uci_spam_link", pool("spam", "uci", True), "cu"),
        ("control_uci_ham", "uci_ham", pool("ham", "uci"), "ch"),
        ("control_uci_spam", "uci_spam", pool("spam", "uci", False), "cp"),
    ]
    sizes = {**COMPOSITION_SIZES, **CONTROL_SIZES}
    for kind, klass, candidates, tag in plan:
        add(kind, klass, draw(candidates, sizes[kind], seed, tag))
    seen: set[str] = set()
    unique = []
    for item in items:
        if item.record_id not in seen:
            seen.add(item.record_id)
            unique.append(item)
    return unique


def write_csv(path: Path, columns: tuple[str, ...], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def build_bundle(
    records: list[Record],
    infos: list[ClusterInfo],
    directory: Path,
    seed: int,
    per_class: int = DEFAULT_PER_CLASS,
) -> dict:
    """Write blank review sheets for two reviewers, the private answer key and the rubric."""
    by_id = {r.record_id: r for r in records}
    items = select_items(records, infos, seed, per_class)
    directory.mkdir(parents=True, exist_ok=True)
    for reviewer in ("A", "B"):
        rows = [
            {"item_id": i.item_id, "display_text": display_text(by_id[i.record_id].text),
             "label": "", "notes": "", "reviewer": ""}
            for i in sorted(items, key=lambda i: order_key(seed, reviewer, i.item_id))
        ]  # fmt: skip
        write_csv(directory / f"review_{reviewer}.csv", REVIEWER_COLUMNS, rows)
    write_csv(directory / "adjudication.csv", ADJUDICATION_COLUMNS, [])
    key = {
        i.item_id: {"record_id": i.record_id, "kind": i.kind, "class": i.klass,
                    "cluster_id": i.cluster_id}
        for i in items
    }  # fmt: skip
    (directory / "answer_key.json").write_text(json.dumps(key, indent=1, sort_keys=True) + "\n")
    (directory / "RUBRIC.md").write_text(RUBRIC)
    counts = Counter(i.klass for i in items if i.kind == "gated")
    available = {k: len(representatives(records, infos, k, "imc")) for k in GATED_CLASSES}
    meta = {
        "seed": seed,
        "per_class_target": per_class,
        "items": len(items),
        "reviewers": 2,
        "reviews_required": 2 * len(items),
        "gated_items_by_class": dict(counts),
        "gated_clusters_available_by_class": available,
        "composition_and_control_items": len(items) - sum(counts.values()),
        "smallest_sample_that_can_pass": smallest_passable_sample(),
        "min_correct_for_gate": {k: min_correct_for_gate(v) for k, v in counts.items()},
        "rubric_version": RUBRIC_VERSION,
        "answer_key_sha256": hashlib.sha256(
            (directory / "answer_key.json").read_bytes()
        ).hexdigest(),
    }
    (directory / "bundle_meta.json").write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n")
    return meta


# --- evaluating completed annotations ------------------------------------------------------


REQUIRED_REVIEW_COLUMNS = {"item_id", "label", "reviewer"}
REQUIRED_ADJUDICATION_COLUMNS = {"item_id", "final_label", "adjudicator"}
# A UCI ham message must be called benign. A UCI spam message may be spam, phishing (if it names an
# organisation, which the rubric allows) or another scam, but never benign.
CONTROL_EXPECTED = {
    "control_uci_ham": {"benign"},
    "control_uci_spam": {"spam", "phishing", "other_scam", "unclear"},
}
CONTROL_ACCURACY_WARNING = 0.90


def read_sheet(path: Path) -> tuple[list[dict[str, str]], set[str]] | None:
    """Rows and column names, or None if the file is absent. Tolerates a spreadsheet BOM."""
    if not path.exists():
        return None
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        return rows, {c.strip() for c in (reader.fieldnames or [])}


def has_annotations(directory: Path) -> bool:
    """True if any review or adjudication cell has been filled in (never overwrite then)."""
    for name in ("review_A.csv", "review_B.csv"):
        sheet = read_sheet(directory / name)
        for row in sheet[0] if sheet else []:
            if any((row.get(c) or "").strip() for c in ("label", "reviewer", "notes")):
                return True
    adjudication = read_sheet(directory / "adjudication.csv")
    return bool(adjudication and adjudication[0])


@dataclass
class ParsedSheet:
    labels: dict[str, str]
    reviewers: set[str]
    duplicate_rows: int = 0
    unknown_rows: int = 0
    missing: bool = False
    missing_columns: bool = False


def parse_review_sheet(path: Path, key_ids: set[str]) -> ParsedSheet:
    sheet = read_sheet(path)
    if sheet is None:
        return ParsedSheet({}, set(), missing=True)
    rows, columns = sheet
    if not REQUIRED_REVIEW_COLUMNS <= columns:
        return ParsedSheet({}, set(), missing_columns=True)
    parsed = ParsedSheet({}, set())
    seen: set[str] = set()
    ambiguous: set[str] = set()
    for row in rows:
        item = (row.get("item_id") or "").strip()
        if item not in key_ids:
            parsed.unknown_rows += bool(item)
            continue
        if item in seen:
            parsed.duplicate_rows += 1
            ambiguous.add(item)
        seen.add(item)
        label = (row.get("label") or "").strip().lower()
        reviewer = (row.get("reviewer") or "").strip()
        if label in LABELS and reviewer:
            parsed.labels[item] = label
            parsed.reviewers.add(reviewer)
    for item in ambiguous:  # a repeated item has no single answer
        parsed.labels.pop(item, None)
    return parsed


def parse_adjudication(path: Path, key_ids: set[str]) -> tuple[dict[str, tuple[str, str]], int]:
    """item -> (final label, adjudicator) for valid rows, and the number of unusable rows."""
    sheet = read_sheet(path)
    if sheet is None:
        return {}, 0
    rows, columns = sheet
    if not REQUIRED_ADJUDICATION_COLUMNS <= columns:
        return {}, max(1, len(rows))
    decided: dict[str, tuple[str, str]] = {}
    unusable = 0
    for row in rows:
        item = (row.get("item_id") or "").strip()
        final = (row.get("final_label") or "").strip().lower()
        who = (row.get("adjudicator") or "").strip()
        if item in key_ids and final in LABELS and who and item not in decided:
            decided[item] = (final, who)
        else:
            unusable += 1
    return decided, unusable


def reviewer_quality(key: dict, sheets: dict[str, ParsedSheet]) -> dict:
    """How each reviewer treated the known-provenance controls. Informational; not the gate."""
    quality: dict = {"warnings": []}
    for name, parsed in sheets.items():
        scored = [
            (item, CONTROL_EXPECTED[v["kind"]])
            for item, v in key.items()
            if v["kind"] in CONTROL_EXPECTED and item in parsed.labels
        ]
        correct = sum(parsed.labels[item] in expected for item, expected in scored)
        composition = Counter(
            parsed.labels[item]
            for item, v in key.items()
            if v["kind"].startswith("composition") and item in parsed.labels
        )
        accuracy = correct / len(scored) if scored else None
        quality[name] = {
            "controls_answered": len(scored),
            "control_accuracy": accuracy,
            "composition_label_counts": dict(composition),
        }
        if accuracy is not None and len(scored) >= 10 and accuracy < CONTROL_ACCURACY_WARNING:
            quality["warnings"].append(
                f"{name}: control accuracy {accuracy:.0%} is below {CONTROL_ACCURACY_WARNING:.0%}"
            )
    return quality


def answer_key_intact(directory: Path) -> bool:
    meta = directory / "bundle_meta.json"
    if not meta.exists():
        return False
    recorded = json.loads(meta.read_text()).get("answer_key_sha256")
    return recorded == hashlib.sha256((directory / "answer_key.json").read_bytes()).hexdigest()


def write_adjudication_queue(directory: Path) -> int:
    """List the items the two reviewers disagree on, for the adjudicator to resolve.

    The queue shows the (masked) text and the two labels, not who gave them, and is rewritten
    from the sheets each time. It decides nothing: `adjudication.csv` holds the final labels.
    """
    key_ids = set(json.loads((directory / "answer_key.json").read_text()))
    a = parse_review_sheet(directory / "review_A.csv", key_ids)
    b = parse_review_sheet(directory / "review_B.csv", key_ids)
    sheet = read_sheet(directory / "review_A.csv")
    text = {r["item_id"].strip(): r.get("display_text", "") for r in sheet[0]} if sheet else {}
    rows = [
        {"item_id": i, "display_text": text.get(i, ""), "label_reviewer_a": a.labels[i],
         "label_reviewer_b": b.labels[i]}
        for i in sorted(key_ids & set(a.labels) & set(b.labels))
        if a.labels[i] != b.labels[i]
    ]  # fmt: skip
    write_csv(directory / "adjudication_queue.csv", ADJUDICATION_QUEUE_COLUMNS, rows)
    return len(rows)


def evaluate_audit(
    directory: Path, minimum: float = GATE_MINIMUM, cluster_sizes: dict[str, int] | None = None
) -> dict:
    """Class decisions from completed annotations.

    BLOCKED unless: the answer key is intact; both sheets are well formed, each with one distinct
    reviewer ID and no duplicate or unknown rows; every item has two reviews; and every
    disagreement has a final label from an adjudicator who is neither reviewer. The gate itself
    (a Wilson lower bound on adjudicated precision) is unaffected by those checks.
    `cluster_sizes` only adds a record-weighted precision as a sensitivity figure.
    """
    key = json.loads((directory / "answer_key.json").read_text())
    key_ids = set(key)
    intact = answer_key_intact(directory)
    names = ("review_A.csv", "review_B.csv")
    sheets = {n: parse_review_sheet(directory / n, key_ids) for n in names}
    a, b = sheets["review_A.csv"], sheets["review_B.csv"]
    decided, unusable_adjudication = parse_adjudication(directory / "adjudication.csv", key_ids)
    gated = {i: v for i, v in key.items() if v["kind"] == "gated"}
    missing_a, missing_b = sorted(key_ids - set(a.labels)), sorted(key_ids - set(b.labels))
    disagreements = sorted(
        i for i in key if i in a.labels and i in b.labels and a.labels[i] != b.labels[i]
    )
    unadjudicated = [i for i in disagreements if i not in decided]
    reviewer_ids = a.reviewers | b.reviewers
    independent = (
        len(a.reviewers) == 1 and len(b.reviewers) == 1 and not (a.reviewers & b.reviewers)
    )
    adjudicators_ok = all(decided[i][1] not in reviewer_ids for i in disagreements if i in decided)
    problems = {
        "duplicate_item_rows": a.duplicate_rows + b.duplicate_rows,
        "unknown_item_rows": a.unknown_rows + b.unknown_rows,
        "sheets_with_several_reviewer_ids": sorted(
            n for n in names if len(sheets[n].reviewers) > 1
        ),
        "sheets_missing_columns": sorted(n for n in names if sheets[n].missing_columns),
        "sheets_missing": sorted(n for n in names if sheets[n].missing),
        "unusable_adjudication_rows": unusable_adjudication,
    }
    sheet_ok = not (
        problems["duplicate_item_rows"]
        or problems["unknown_item_rows"]
        or problems["sheets_with_several_reviewer_ids"]
        or problems["sheets_missing_columns"]
        or problems["sheets_missing"]
        or problems["unusable_adjudication_rows"]
    )
    complete = (
        intact
        and sheet_ok
        and independent
        and adjudicators_ok
        and not missing_a
        and not missing_b
        and not unadjudicated
        and bool(key)
    )
    progress = {
        "items": len(key),
        "reviewer_a_completed": len(a.labels),
        "reviewer_b_completed": len(b.labels),
        "disagreements": len(disagreements),
        "disagreements_unadjudicated": len(unadjudicated),
        "reviewers_distinct_ids": independent,
        "adjudicators_independent": adjudicators_ok,
        "answer_key_intact": intact,
        "sheet_problems": problems,
    }
    final_labels = {
        i: decided[i][0] if i in decided and a.labels.get(i) != b.labels.get(i) else a.labels.get(i)
        for i in key
    }

    def kappa_for(ids: list[str]) -> float | None:
        pairs = [(a.labels[i], b.labels[i]) for i in ids if i in a.labels and i in b.labels]
        return cohen_kappa(pairs)

    classes = {}
    for klass in GATED_CLASSES:
        ids = [i for i, v in gated.items() if v["class"] == klass]
        needed = min_correct_for_gate(len(ids), minimum) if ids else None
        entry: dict = {"sampled": len(ids), "min_correct_needed": needed}
        if not complete:
            entry |= {"status": "BLOCKED", "reason": "human review incomplete or not valid"}
        else:
            correct = sum(final_labels[i] == "phishing" for i in ids)
            low, high = wilson_interval(correct, len(ids)) if ids else (0.0, 0.0)
            entry |= {
                "status": "PASS" if ids and low >= minimum else "FAIL",
                "correct": correct,
                "precision": correct / len(ids) if ids else None,
                "wilson_95_low": low,
                "wilson_95_high": high,
                "label_counts": dict(Counter(final_labels[i] for i in ids)),
            }
            if cluster_sizes and ids:
                weights = {i: cluster_sizes.get(gated[i]["cluster_id"], 1) for i in ids}
                good = sum(weights[i] for i in ids if final_labels[i] == "phishing")
                entry["record_weighted_precision"] = good / sum(weights.values())
            if entry["status"] == "FAIL" and needed is None:
                entry["reason"] = "sample too small to reach the gate"
        classes[klass] = entry
    if not complete:
        approval = "BLOCKED"
    elif any(c["status"] == "PASS" for c in classes.values()):
        approval = "APPROVED_CLASSES"
    else:
        approval = "NO_CLASS_PASSED"
    return {
        "label_approval": approval,
        "gate": {
            "statistic": "wilson_lower_bound",
            "confidence": 0.95,
            "minimum": minimum,
            # Owner decision, 5 November 2026: the gate uses cluster-weighted precision (one
            # reviewed representative per near-duplicate cluster). Record-weighted precision is
            # reported beside it as a sensitivity figure and never decides a class.
            "precision_basis": "cluster_weighted",
            "record_weighted_precision": "reported_separately_not_gating",
        },
        "progress": progress,
        "cohen_kappa_all_items": kappa_for(list(key)) if complete else None,
        "cohen_kappa_gated_items": kappa_for(list(gated)) if complete else None,
        "reviewer_quality": reviewer_quality(key, sheets),
        "classes": classes,
        "promoted_to_phishing": sorted(k for k, v in classes.items() if v["status"] == "PASS"),
    }
