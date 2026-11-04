"""Deterministic, group-aware train/validation/test splitting and the held-out access guard.

Clusters (exact + near-duplicate groups, and template families for synthetic data) are the unit:
every record of a cluster gets the same split. Clusters are stratified by `source:label`, so
each stratum keeps roughly the target proportions of *unique texts*, and the result depends only
on the seed and the cluster IDs, never on input order.

Label approval is deliberately not an input. The assignment covers every cluster whose
provisional label is usable; a class that later fails the label audit simply drops out of all
three splits, and no remaining cluster moves. That is what lets the test set be frozen before
the audit finishes and before any model exists.

Grouped splitting prevents duplicate and near-duplicate leakage. It does not solve source or
era confounding: positives and negatives still come from different datasets.
"""

import hashlib
import json
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sms_prep.clusters import ClusterInfo
from sms_prep.records import Record

SPLIT_ALGORITHM_VERSION = 1
SPLITS = ("train", "validation", "test")
DEFAULT_PROPORTIONS = {"train": 0.70, "validation": 0.15, "test": 0.15}
DEFAULT_SEED = 20261105
FINAL_EVALUATION = "final_evaluation"
ALLOWED_PURPOSES = {
    "train": {"training"},
    "validation": {"tuning", "validation", "threshold_selection"},
    "test": {FINAL_EVALUATION},
}


def eligible(info: ClusterInfo) -> bool:
    return info.status == "ok" and info.provisional != "excluded" and info.candidate_records > 0


def tiebreak(seed: int, cluster_id: str) -> str:
    return hashlib.sha256(f"{seed}|{cluster_id}".encode()).hexdigest()


def assign_splits(
    infos: list[ClusterInfo],
    seed: int = DEFAULT_SEED,
    proportions: dict[str, float] | None = None,
) -> dict[str, str]:
    """cluster_id -> split for every eligible cluster."""
    proportions = proportions or DEFAULT_PROPORTIONS
    if set(proportions) != set(SPLITS) or abs(sum(proportions.values()) - 1) > 1e-9:
        raise ValueError("Proportions must cover train, validation and test and sum to 1")
    strata: dict[str, list[ClusterInfo]] = defaultdict(list)
    for info in infos:
        if eligible(info):
            strata[info.stratum].append(info)
    assignment = {}
    for stratum in sorted(strata):
        members = strata[stratum]
        total = sum(i.unique_texts for i in members)
        remaining = {s: total * proportions[s] for s in SPLITS}
        for info in sorted(members, key=lambda i: (-i.unique_texts, tiebreak(seed, i.cluster_id))):
            split = max(SPLITS, key=lambda s: (remaining[s], -SPLITS.index(s)))
            assignment[info.cluster_id] = split
            remaining[split] -= info.unique_texts
    return assignment


@dataclass(frozen=True)
class Assignment:
    record_id: str
    cluster_id: str
    split: str
    stratum: str
    dataset: str
    origin: str


def record_assignments(
    records: list[Record], infos: list[ClusterInfo], cluster_split: dict[str, str]
) -> list[Assignment]:
    by_cluster = {i.cluster_id: i for i in infos}
    cluster_of = {rid: i.cluster_id for i in infos for rid in i.record_ids}
    rows = []
    for record in records:
        cluster_id = cluster_of.get(record.record_id)
        if record.role != "candidate" or cluster_id not in cluster_split:
            continue
        info = by_cluster[cluster_id]
        rows.append(
            Assignment(record.record_id, cluster_id, cluster_split[cluster_id], info.stratum,
                       record.dataset, record.origin)
        )  # fmt: skip
    return sorted(rows, key=lambda a: a.record_id)


def write_assignments(path: Path, rows: list[Assignment]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(a.__dict__, sort_keys=True) for a in rows]
    data = ("\n".join(lines) + "\n").encode()
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def read_assignments(path: Path) -> list[Assignment]:
    with path.open(encoding="utf-8") as handle:
        return [Assignment(**json.loads(line)) for line in handle if line.strip()]


class HeldOutGuard:
    """Read access to the split assignments with a purpose check and a use log for the test set.

    This is a procedural control, not a security boundary: whoever holds the files can read
    them. It makes the right path the easy one, refuses to serve the test set for training or
    tuning, ties it to a verified frozen file, and leaves a log of every final evaluation.
    """

    def __init__(
        self,
        assignments_path: Path,
        expected_sha256: str,
        log_path: Path,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        data = assignments_path.read_bytes()
        if hashlib.sha256(data).hexdigest() != expected_sha256:
            raise PermissionError("The split file differs from the frozen split metadata")
        self.rows = [Assignment(**json.loads(x)) for x in data.decode().splitlines() if x.strip()]
        self.sha256 = expected_sha256
        self.log_path = log_path
        self.clock = clock

    def record_ids(self, split: str, purpose: str, model_version: str | None = None) -> list[str]:
        if split not in SPLITS or purpose not in ALLOWED_PURPOSES[split]:
            raise PermissionError(f"The {split} split cannot be read for {purpose!r}")
        ids = [a.record_id for a in self.rows if a.split == split]
        if split == "test":
            if not model_version:
                raise PermissionError("A test evaluation must name the model version")
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            entry = {
                "at": self.clock().isoformat(),
                "purpose": purpose,
                "model_version": model_version,
                "split_sha256": self.sha256,
                "records": len(ids),
            }
            with self.log_path.open("a", encoding="utf-8") as log:
                log.write(json.dumps(entry, sort_keys=True) + "\n")
        return ids
