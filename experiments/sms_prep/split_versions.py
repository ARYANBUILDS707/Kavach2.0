"""Registry of split versions. A version is never edited: a change is a new version.

v1 is the frozen M4.2 split (grouping at Jaccard 0.7); its files keep their original paths so
its recorded hashes stay valid. v2 groups at campaign level (Jaccard 0.4), the threshold the
owner approved on 5 November 2026 for a *proposed* split, subject to the checks in
`split_report`. Its files live in their own directory and never touch v1's.
"""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SplitVersion:
    version: int
    threshold: float
    work_subdir: str  # under data/m4/work; "" is the original v1 location
    meta_name: str
    report_name: str
    grouping: str

    def work_dir(self, data_dir: Path) -> Path:
        return data_dir / "work" / self.work_subdir if self.work_subdir else data_dir / "work"

    def assignments(self, data_dir: Path) -> Path:
        return self.work_dir(data_dir) / "assignments.jsonl"

    def clusters(self, data_dir: Path) -> Path:
        return self.work_dir(data_dir) / "clusters.jsonl"


VERSIONS = {
    1: SplitVersion(
        1, 0.7, "", "sms_split.v1.meta.json", "m4_2_data_quality.json",
        "exact + near-duplicate texts (character 5-gram Jaccard >= 0.7) "
        "+ synthetic template families",
    ),
    2: SplitVersion(
        2, 0.4, "split_v2", "sms_split.v2.meta.json", "m4_2_split_v2_report.json",
        "campaign-level: texts linked at character 5-gram Jaccard >= 0.4 (the level at which hand "
        "checks still found reworded variants of one campaign) + synthetic template families",
    ),
}  # fmt: skip
