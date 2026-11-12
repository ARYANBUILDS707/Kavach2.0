"""Small synthetic fixtures for the data-governance tests. No real data: texts are random
letter strings (so unrelated records never look alike) plus deliberately planted duplicates."""

import random
import string

from sms_prep.clusters import assign_clusters, build_cluster_infos
from sms_prep.records import Record, make_id, synthetic_records
from sms_prep.synthetic import generate


def gibberish(rng: random.Random, length: int = 70) -> str:
    return "".join(rng.choice(string.ascii_lowercase + "   ") for _ in range(length)).strip()


def record(
    dataset: str, source: str, row: int, label: str, text: str, *, role: str = "candidate",
    provisional: str | None = None, label_key: str | None = None, origin: str = "collected",
    group: str = "", language: str = "English",
) -> Record:  # fmt: skip
    default = {"ham": "benign", "spam": "spam"}.get(label, "needs_review")
    return Record(
        make_id(dataset, row),
        dataset,
        source,
        row,
        label,
        text,
        role,
        label_key or label,
        provisional or default,
        origin,
        language,
        group,
    )


def fixture_records(seed: int = 7) -> list[Record]:
    rng = random.Random(seed)
    records: list[Record] = []
    row = {"imc": 0, "uci": 0, "mishra": 0}

    def add(source: str, label: str, count: int, **kw: object) -> list[str]:
        dataset = {"imc": "imc25_smishing_reports", "uci": "uci_sms_spam_collection",
                   "mishra": "mishra_soni_2022"}[source]  # fmt: skip
        texts = []
        for _ in range(count):
            text = gibberish(rng)
            texts.append(text)
            records.append(record(dataset, source, row[source], label, text, **kw))
            row[source] += 1
        return texts

    banking = add("imc", "banking", 300)
    add("imc", "delivery", 120)
    add("imc", "wrong number", 90)
    add("imc", "hey mum/dad", 40)
    add("imc", "spam", 90, provisional="spam", label_key="spam")
    ham = add("uci", "ham", 150)
    spam = add("uci", "spam", 60)
    # planted exact duplicates and near-duplicates inside IMC banking
    for i in range(10):
        records.append(record("imc25_smishing_reports", "imc", row["imc"], "banking", banking[i]))
        row["imc"] += 1
        records.append(
            record("imc25_smishing_reports", "imc", row["imc"], "banking", banking[i] + " ok")
        )
        row["imc"] += 1
    # Mishra copies of UCI texts (reference only)
    for text in ham[:20] + spam[:10]:
        records.append(
            record("mishra_soni_2022", "mishra", row["mishra"], "ham", text, role="reference",
                   provisional="benign")
        )  # fmt: skip
        row["mishra"] += 1
    records += synthetic_records(generate(seed=3, per_template=4))
    return records


def fixture_clusters(seed: int = 7, threshold: float = 0.7):
    records = fixture_records(seed)
    assignment = assign_clusters(records, threshold)
    return records, assignment, build_cluster_infos(records, assignment)
