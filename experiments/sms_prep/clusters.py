"""Cluster the record store and derive each cluster's split stratum.

Candidate and reference records are clustered together, so a UCI message and its Mishra copy
land in one cluster; synthetic records are additionally joined by template family. A cluster is
the unit of splitting: its members never cross train, validation and test.
"""

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path

from sms_prep.cluster import cluster_texts
from sms_prep.records import Record

CLUSTERED_ROLES = ("candidate", "reference")


@dataclass(frozen=True)
class ClusterInfo:
    cluster_id: str
    record_ids: tuple[str, ...]
    candidate_records: int
    unique_texts: int  # candidate members only: the weight used when splitting
    reference_members: int
    sources: tuple[str, ...]  # candidate sources
    source: str  # stratum source (majority of candidate records)
    label_key: str  # stratum label (majority of candidate records)
    provisional: str
    origin: str
    status: str  # ok | conflict_class | reference_only
    label_key_mixed: bool

    @property
    def stratum(self) -> str:
        return f"{self.source}:{self.label_key}"


def assign_clusters(records: list[Record], threshold: float) -> dict[str, str]:
    """record_id -> cluster_id for candidate and reference records."""
    chosen = [r for r in records if r.role in CLUSTERED_ROLES]
    result = cluster_texts([r.text for r in chosen], threshold, [r.group or None for r in chosen])
    return {r.record_id: c for r, c in zip(chosen, result.cluster_ids, strict=True)}


def majority(counter: Counter) -> str:
    top = max(counter.values())
    return sorted(k for k, v in counter.items() if v == top)[0]


def build_cluster_infos(records: list[Record], assignment: dict[str, str]) -> list[ClusterInfo]:
    from dataset_governance.fingerprints import normalize_text

    members: dict[str, list[Record]] = defaultdict(list)
    for record in records:
        if record.record_id in assignment:
            members[assignment[record.record_id]].append(record)
    infos = []
    for cluster_id in sorted(members):
        group = members[cluster_id]
        candidates = [r for r in group if r.role == "candidate"]
        reference = len(group) - len(candidates)
        if not candidates:
            infos.append(
                ClusterInfo(cluster_id, tuple(sorted(r.record_id for r in group)), 0, 0,
                            reference, (), "", "", "excluded", "collected", "reference_only", False)
            )  # fmt: skip
            continue
        provisional = Counter(r.provisional for r in candidates)
        label_keys = Counter(r.label_key for r in candidates)
        sources = Counter(r.source for r in candidates)
        status = "ok" if len(provisional) == 1 else "conflict_class"
        infos.append(
            ClusterInfo(
                cluster_id,
                tuple(sorted(r.record_id for r in group)),
                len(candidates),
                len({normalize_text(r.text) for r in candidates}),
                reference,
                tuple(sorted(sources)),
                majority(sources),
                majority(label_keys),
                majority(provisional),
                "synthetic" if candidates[0].origin == "synthetic" else "collected",
                status,
                len(label_keys) > 1 and len(provisional) == 1,
            )
        )
    return infos


def write_clusters(path: Path, infos: list[ClusterInfo]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(asdict(i), sort_keys=True) for i in infos]
    data = ("\n".join(lines) + "\n").encode()
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def read_clusters(path: Path) -> list[ClusterInfo]:
    infos = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                d = json.loads(line)
                d["record_ids"] = tuple(d["record_ids"])
                d["sources"] = tuple(d["sources"])
                infos.append(ClusterInfo(**d))
    return infos
