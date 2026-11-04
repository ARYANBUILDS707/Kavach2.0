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

RUBRIC = """# Label rubric for the KAVACH SMS review

You will see short text messages, one per row, in a random order. Judge each message on its
own, as the recipient would. You are not told where it came from. Digit runs, emails and
phone numbers are masked.

Choose exactly one label:

- `phishing`: the message tries to make the recipient click a link, call or reply to a
  number, pay, or reveal credentials or personal or financial data, while posing as a bank,
  carrier, delivery company, government body, employer or other trusted party.
- `other_scam`: a fraud attempt that does NOT fit the phishing definition above, for example
  a wrong-number opener that asks for nothing yet, or someone posing as a relative asking for
  money with no link or credentials requested. Do not use it for phishing.
- `spam`: unsolicited promotion, a prize or competition offer, a marketing message or a
  nuisance message with no impersonation or credential request.
- `benign`: a legitimate message: personal conversation, a genuine notification or alert.
- `unclear`: you cannot tell. Use sparingly; it counts as "not phishing" in the precision.

Rules: work alone and do not compare answers with the other reviewer; do not look messages
up or open links; do not use any automatic classifier or language model to decide; leave
`label` empty rather than guess. Put your reviewer ID in the `reviewer` column of every row.
Disagreements are resolved afterwards by an adjudicator who records `final_label`.
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
        "answer_key_sha256": hashlib.sha256(
            (directory / "answer_key.json").read_bytes()
        ).hexdigest(),
    }
    (directory / "bundle_meta.json").write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n")
    return meta


# --- evaluating completed annotations ------------------------------------------------------


def read_sheet(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def labels_by_item(rows: list[dict[str, str]]) -> tuple[dict[str, str], set[str]]:
    """item_id -> label for valid completed rows, plus the reviewer IDs seen."""
    labels, reviewers = {}, set()
    for row in rows:
        label = (row.get("label") or "").strip().lower()
        if label in LABELS and (row.get("reviewer") or "").strip():
            labels[row["item_id"]] = label
            reviewers.add(row["reviewer"].strip())
    return labels, reviewers


def evaluate_audit(directory: Path, minimum: float = GATE_MINIMUM) -> dict:
    """Class decisions from completed annotations. BLOCKED unless every gated item has two
    independent reviews and every disagreement has an adjudicated final label."""
    key = json.loads((directory / "answer_key.json").read_text())
    a_labels, a_ids = labels_by_item(read_sheet(directory / "review_A.csv"))
    b_labels, b_ids = labels_by_item(read_sheet(directory / "review_B.csv"))
    adjudicated = {}
    for row in read_sheet(directory / "adjudication.csv"):
        final = (row.get("final_label") or "").strip().lower()
        if final in LABELS and (row.get("adjudicator") or "").strip():
            adjudicated[row["item_id"]] = final
    gated = {i: v for i, v in key.items() if v["kind"] == "gated"}
    missing_a = sorted(set(key) - set(a_labels))
    missing_b = sorted(set(key) - set(b_labels))
    disagreements = sorted(
        i for i in key if i in a_labels and i in b_labels and a_labels[i] != b_labels[i]
    )
    unadjudicated = [i for i in disagreements if i not in adjudicated]
    independent = bool(a_ids) and bool(b_ids) and not (a_ids & b_ids)
    complete = not missing_a and not missing_b and not unadjudicated and independent and bool(key)
    progress = {
        "items": len(key),
        "reviewer_a_completed": len(a_labels),
        "reviewer_b_completed": len(b_labels),
        "disagreements": len(disagreements),
        "disagreements_unadjudicated": len(unadjudicated),
        "reviewers_distinct_ids": independent,
    }
    final_labels = {
        i: adjudicated.get(i, a_labels.get(i))
        if a_labels.get(i) != b_labels.get(i)
        else a_labels.get(i)
        for i in key
    }
    kappa = cohen_kappa(
        [(a_labels[i], b_labels[i]) for i in key if i in a_labels and i in b_labels]
    )
    classes = {}
    for klass in GATED_CLASSES:
        ids = [i for i, v in gated.items() if v["class"] == klass]
        needed = min_correct_for_gate(len(ids), minimum) if ids else None
        entry = {"sampled": len(ids), "min_correct_needed": needed}
        if not complete:
            entry |= {"status": "BLOCKED", "reason": "human review incomplete"}
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
            if entry["status"] == "FAIL" and needed is None:
                entry["reason"] = "sample too small to reach the gate"
        classes[klass] = entry
    approval = (
        "BLOCKED"
        if not complete
        else (
            "APPROVED_CLASSES"
            if any(c["status"] == "PASS" for c in classes.values())
            else "NO_CLASS_PASSED"
        )
    )
    return {
        "label_approval": approval,
        "gate": {"statistic": "wilson_lower_bound", "confidence": 0.95, "minimum": minimum},
        "progress": progress,
        "cohen_kappa_all_items": kappa if complete else None,
        "classes": classes,
        "promoted_to_phishing": sorted(k for k, v in classes.items() if v["status"] == "PASS"),
    }
