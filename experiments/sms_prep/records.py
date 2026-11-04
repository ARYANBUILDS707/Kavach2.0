"""The private record store: one record per source row, with provenance and original labels.

Records hold raw message text and therefore live only under the ignored data directory
(`data/m4/`). Nothing printed, logged or committed by this package contains `text`.

Roles decide what a record may be used for:
  candidate                 eligible for clustering, auditing and splitting
  reference                 audit reference only (Mishra & Soni): clustered, never split
  experimental_non_english  kept aside; the first baseline is English only
  excluded_unlabeled        no usable label
"""

import csv
import hashlib
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from sms_prep.synthetic import SyntheticMessage

IMC = "imc25_smishing_reports"
UCI = "uci_sms_spam_collection"
MISHRA = "mishra_soni_2022"
SYNTHETIC = "kavach_synthetic_hard_negatives"
SOURCE_PREFIX = {IMC: "imc", UCI: "uci", MISHRA: "mishra", SYNTHETIC: "synthetic"}
IMC_PHISHING_CANDIDATE_CLASSES = ("banking", "delivery", "government", "telecom", "others")
IMC_SCOPE_CLASSES = (*IMC_PHISHING_CANDIDATE_CLASSES, "wrong number", "hey mum/dad")
MAX_TEXT_CHARS = 5000

csv.field_size_limit(sys.maxsize)


@dataclass(frozen=True)
class Record:
    record_id: str
    dataset: str
    source: str
    row: int
    source_label: str
    text: str = field(repr=False)
    role: str
    label_key: str
    provisional: str  # benign | spam | needs_review | excluded
    origin: str  # collected | synthetic
    language: str = ""
    group: str = ""  # template family for synthetic records

    def public(self) -> dict:
        """Everything except the text: safe for reports."""
        data = asdict(self)
        del data["text"]
        return data


def make_id(dataset: str, row: int) -> str:
    return hashlib.sha256(f"{dataset}|{row}".encode()).hexdigest()[:16]


def imc_record(row: int, fields: dict[str, str]) -> Record:
    scam = fields["scam_type"].strip().lower()
    english = fields["language"] == "English"
    if not scam:
        role, label_key, provisional = "excluded_unlabeled", "(empty)", "excluded"
    elif not english:
        role, label_key, provisional = "experimental_non_english", scam, "excluded"
    elif scam == "spam":
        role, label_key, provisional = "candidate", "spam", "spam"
    elif scam in IMC_SCOPE_CLASSES:
        role, label_key, provisional = "candidate", scam, "needs_review"
    else:
        role, label_key, provisional = "excluded_unlabeled", scam, "excluded"
    return Record(
        make_id(IMC, row), IMC, "imc", row, scam or "(empty)", fields["text"][:MAX_TEXT_CHARS],
        role, label_key, provisional, "collected", fields["language"],
    )  # fmt: skip


def load_imc(path: Path) -> list[Record]:
    with path.open(encoding="utf-8", newline="") as handle:
        return [imc_record(i, r) for i, r in enumerate(csv.DictReader(handle))]


def load_uci(path: Path) -> list[Record]:
    records = []
    for row, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines()):
        label, _, text = line.partition("\t")
        label = label.strip().lower()
        if label not in {"ham", "spam"}:
            raise ValueError("Unexpected UCI label")
        provisional = "benign" if label == "ham" else "spam"
        records.append(
            Record(make_id(UCI, row), UCI, "uci", row, label, text[:MAX_TEXT_CHARS], "candidate",
                   label, provisional, "collected", "English")
        )  # fmt: skip
    return records


def load_mishra(path: Path) -> list[Record]:
    provisional = {"ham": "benign", "spam": "spam", "smishing": "needs_review"}
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return [
        Record(make_id(MISHRA, i), MISHRA, "mishra", i, r["LABEL"].strip().lower(),
               r["TEXT"][:MAX_TEXT_CHARS], "reference", r["LABEL"].strip().lower(),
               provisional[r["LABEL"].strip().lower()], "collected", "English")
        for i, r in enumerate(rows)
    ]  # fmt: skip


def synthetic_records(messages: list[SyntheticMessage]) -> list[Record]:
    return [
        Record(make_id(SYNTHETIC, i), SYNTHETIC, "synthetic", i, "benign", m.text, "candidate",
               "synthetic_benign", "benign", "synthetic", "English", group=m.template_id)
        for i, m in enumerate(messages)
    ]  # fmt: skip


def write_records(path: Path, records: list[Record]) -> str:
    """Write JSONL (private) and return its SHA-256."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(asdict(r), sort_keys=True, ensure_ascii=False) for r in records]
    data = ("\n".join(lines) + "\n").encode()
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def read_records(path: Path) -> list[Record]:
    with path.open(encoding="utf-8") as handle:
        return [Record(**json.loads(line)) for line in handle if line.strip()]
