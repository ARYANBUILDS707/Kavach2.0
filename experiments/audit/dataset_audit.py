"""Recompute the manifest's `observed` values from local copies of the four datasets.

    backend/.venv/bin/python experiments/audit/dataset_audit.py \
        --uci DIR/SMSSpamCollection --mishra DIR/Dataset_5971.csv \
        --munoz DIR/Dataset_10191.csv --imc DIR/final_dataset_output.csv

It checks each file's SHA-256 against the manifest, then recomputes the counts and compares
them with the recorded values. It prints counts only: never message text, and it writes
nothing. Exit 0 means every checksum and every recorded value was reproduced.
"""

import argparse
import csv
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from dataset_governance.fingerprints import (  # noqa: E402
    NEAR_DUPLICATE_JACCARD,
    jaccard,
    normalize_text,
    shingles,
)
from dataset_governance.manifest import DEFAULT_MANIFEST, Manifest, load_manifest  # noqa: E402

csv.field_size_limit(sys.maxsize)
PHONE_LIKE = re.compile(r"(?<!\d)(?:\+?\d[\d\s().-]{8,}\d)(?!\d)")
EMAIL_LIKE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
URL_LIKE = re.compile(r"https?://|www\.|\b\w+\.(?:com|net|org|in|co\.uk|info|xyz|top|ly)\b", re.I)

Rows = list[tuple[str, str]]  # (source label, text)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_labeled_csv(path: Path, label: str, text: str) -> Rows:
    with path.open(encoding="utf-8", newline="") as handle:
        return [(r[label].strip().lower(), r[text]) for r in csv.DictReader(handle)]


def read_uci(path: Path) -> Rows:
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        label, _, text = line.partition("\t")
        rows.append((label.strip().lower(), text))
    return rows


def duplicate_counts(rows: Rows) -> dict[str, int]:
    texts = [text for _, text in rows]
    normalized = Counter(normalize_text(t) for t in texts)
    labels = defaultdict(set)
    for label, text in rows:
        labels[normalize_text(text)].add(label)
    return {
        "rows": len(rows),
        "unique_normalized_texts": len(normalized),
        "exact_duplicate_rows": sum(c - 1 for c in Counter(texts).values()),
        "normalized_duplicate_rows": sum(c - 1 for c in normalized.values()),
        "texts_with_conflicting_labels": sum(len(v) > 1 for v in labels.values()),
        "rows_phone_like_text": sum(bool(PHONE_LIKE.search(t)) for t in texts),
        "rows_email_like_text": sum(bool(EMAIL_LIKE.search(t)) for t in texts),
    }


def unique(rows: Iterable[tuple[str, str]], label: str | None = None) -> set[str]:
    return {normalize_text(t) for lab, t in rows if label is None or lab == label}


def near_duplicates(source: Rows, reference: Rows) -> int:
    """Unique source texts with a non-identical reference text at Jaccard >= 0.8."""
    ref = {n: shingles(n) for n in unique(reference)}
    names = list(ref)
    index = defaultdict(list)
    for i, name in enumerate(names):
        for shingle in ref[name]:
            index[shingle].append(i)
    found = 0
    for text in unique(source):
        if text in ref:
            continue
        mine = shingles(text)
        votes = Counter(i for s in mine for i in index.get(s, ()))
        if any(
            jaccard(mine, ref[names[i]]) >= NEAR_DUPLICATE_JACCARD for i, _ in votes.most_common(8)
        ):
            found += 1
    return found


def compute(uci: Rows, mishra: Rows, munoz: Rows, imc: list[dict[str, str]]) -> dict[str, dict]:
    uci_u, mishra_u, munoz_u = unique(uci), unique(mishra), unique(munoz)
    imc_rows = [("", r["text"]) for r in imc]
    imc_u = unique(imc_rows)
    english = [r["text"] for r in imc if r["language"] == "English"]
    mishra_smishing = unique(mishra, "smishing")
    uci_spam = unique(uci, "spam")
    imc_counts = duplicate_counts(imc_rows)
    imc_counts.pop("texts_with_conflicting_labels")
    scam_by_text = defaultdict(set)
    for r in imc:
        if r["language"] == "English":
            scam_by_text[normalize_text(r["text"])].add(r["scam_type"])
    return {
        "imc25_smishing_reports": imc_counts
        | {
            "rows_english": len(english),
            "rows_non_english": len(imc) - len(english),
            "unique_normalized_texts_english": len({normalize_text(t) for t in english}),
            "english_unique_texts_with_conflicting_scam_type": sum(
                len(v) > 1 for v in scam_by_text.values()
            ),
            "english_rows_with_url_placeholder": sum("<url>" in t.lower() for t in english),
            "overlap_unique_with_uci": len(imc_u & uci_u),
            "overlap_unique_with_mishra": len(imc_u & mishra_u),
            "overlap_unique_with_munoz": len(imc_u & munoz_u),
        },
        "uci_sms_spam_collection": duplicate_counts(uci)
        | {
            "rows_non_ascii": sum(any(ord(c) > 127 for c in t) for _, t in uci),
            "rows_url_like_text": sum(bool(URL_LIKE.search(t)) for _, t in uci),
            "overlap_unique_with_mishra": len(uci_u & mishra_u),
            "overlap_unique_with_munoz": len(uci_u & munoz_u),
        },
        "mishra_soni_2022": duplicate_counts(mishra)
        | {
            "overlap_unique_with_uci": len(mishra_u & uci_u),
            "smishing_rows": sum(lab == "smishing" for lab, _ in mishra),
            "smishing_unique_texts": len(mishra_smishing),
            "smishing_unique_in_uci_as_spam": len(mishra_smishing & uci_spam),
            "smishing_unique_not_in_uci": len(mishra_smishing - uci_u),
            "spam_unique_not_in_uci": len(unique(mishra, "spam") - uci_u),
            "ham_unique_not_in_uci": len(unique(mishra, "ham") - uci_u),
        },
        "munoz_islam_2025": duplicate_counts(munoz)
        | {
            "overlap_unique_with_mishra": len(munoz_u & mishra_u),
            "overlap_unique_with_uci": len(munoz_u & uci_u),
            "near_duplicates_of_mishra_unique_texts": near_duplicates(munoz, mishra),
            "near_duplicates_of_uci_unique_texts": near_duplicates(munoz, uci),
            "smishing_unique_texts": len(unique(munoz, "smishing")),
            "smishing_unique_exact_in_mishra_smishing": len(
                unique(munoz, "smishing") & mishra_smishing
            ),
            "ham_rows_also_in_mishra": sum(
                lab == "ham" and normalize_text(t) in mishra_u for lab, t in munoz
            ),
        },
    }


def verify(manifest: Manifest, paths: dict[str, Path]) -> list[str]:
    problems = []
    expected = {f.name: f.sha256 for d in manifest.datasets for f in d.files}
    for name, path in paths.items():
        if path.name not in expected:
            problems.append(f"{path.name}: not listed in the manifest")
        elif sha256(path) != expected[path.name]:
            problems.append(f"{path.name}: SHA-256 differs from the manifest ({name})")
    return problems


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    for name in ("uci", "mishra", "munoz", "imc"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--json", action="store_true", help="print the recomputed values")
    args = parser.parse_args(argv)
    manifest = load_manifest(args.manifest)
    paths = {
        "uci": args.uci,
        "mishra": args.mishra,
        "munoz": args.munoz,
        "imc": args.imc,
    }
    problems = verify(manifest, paths)
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    with args.imc.open(encoding="utf-8", newline="") as handle:
        imc = list(csv.DictReader(handle))
    results = compute(
        read_uci(args.uci),
        read_labeled_csv(args.mishra, "LABEL", "TEXT"),
        read_labeled_csv(args.munoz, "LABEL", "TEXT"),
        imc,
    )
    mismatches = 0
    for dataset in manifest.datasets:
        recomputed = results[dataset.id]
        for key, recorded in dataset.observed.items():
            actual = recomputed.get(key)
            if actual != recorded:
                mismatches += 1
                print(f"MISMATCH {dataset.id}.{key}: manifest {recorded}, recomputed {actual}")
        print(f"{dataset.id}: {len(dataset.observed)} recorded values checked")
    if args.json:
        print(json.dumps(results, indent=2, sort_keys=True))
    print("All checksums and recorded values reproduced." if not mismatches else "FAILED")
    return 1 if mismatches else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
