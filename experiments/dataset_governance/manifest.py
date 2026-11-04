"""Versioned dataset manifest: schema and validation rules (docs/DATASET_GOVERNANCE.md).

The manifest records where each dataset came from, under what terms, what its labels mean,
how they map to KAVACH's task, what may be done with it and what must not. It contains no
message text, no sample rows and no local paths. Validation enforces the policy rather than
documenting it: for example, no source label may map automatically to `phishing`, and a
dataset that is LLM-generated or of unknown origin cannot supply validation or held-out data.

    cd experiments && python -m dataset_governance.manifest [manifest.json]
"""

import json
import sys
from datetime import date
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

MAX_MANIFEST_BYTES = 256 * 1024
MANIFESTS = Path(__file__).parents[1] / "manifests"
V1_MANIFEST = MANIFESTS / "sms_datasets.v1.json"
DEFAULT_MANIFEST = MANIFESTS / "sms_datasets.v2.json"

SHA256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Slug = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{1,31}$")]
HttpsUrl = Annotated[str, StringConstraints(pattern=r"^https://[^\s]+$", max_length=300)]
Note = Annotated[str, StringConstraints(min_length=1, max_length=600)]

TargetLabel = Literal["benign", "spam", "phishing", "needs_review", "excluded"]
Origin = Literal[
    "human_collected",
    "user_reported_forum",
    "llm_generated_or_mixed",
    "derived_from_other_dataset",
]
LabelProvenance = Literal[
    "source_defined",
    "author_assigned_undocumented",
    "llm_assigned_validated_sample",
    "derived_from_other_dataset",
]
Use = Literal["training", "validation", "held_out_evaluation", "overlap_audit_reference"]
Status = Literal["candidate_primary", "candidate_conditional", "audit_reference_only", "excluded"]
Decision = Literal["pending", "approved", "rejected"]
# Origins whose provenance is too unclear for the data that decides model quality.
UNTRUSTED_FOR_EVALUATION = {"llm_generated_or_mixed", "derived_from_other_dataset"}
EVALUATION_USES = {"validation", "held_out_evaluation"}


class Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FileRecord(Frozen):
    name: Annotated[str, StringConstraints(min_length=1, max_length=120, pattern=r"^[^/\\]+$")]
    sha256: SHA256
    size_bytes: int = Field(gt=0)
    rows: int | None = Field(default=None, gt=0)
    # Where the file sits inside the downloaded archive ("!" separates nested archives).
    # Absent for a direct download. Required from manifest version 2.
    path_in_download: Annotated[str, StringConstraints(max_length=300)] | None = None
    # False for archive members that are verified in memory but never written to disk
    # (scripts and documents that the pipeline does not use).
    extract: bool = True
    note: Note | None = None


class LicenseInfo(Frozen):
    spdx: Literal["CC-BY-4.0"]
    evidence_url: HttpsUrl
    caveats: list[Note]


class LabelRule(Frozen):
    target: TargetLabel
    rule: Note
    # `phishing` only with human verification of exactly these labels; M4.1 has none.
    human_verified: bool = False
    review_plan: Note | None = None

    @model_validator(mode="after")
    def check(self) -> Self:
        if self.target == "phishing" and not self.human_verified:
            raise ValueError("no source label may map automatically to phishing")
        if self.target == "needs_review" and not self.review_plan:
            raise ValueError("needs_review requires a review plan")
        return self


class Privacy(Frozen):
    risk: Literal["low", "medium", "high"]
    notes: list[Note]
    required_handling: list[Note]


class Approval(Frozen):
    decision: Decision
    reference: Note | None = None

    @model_validator(mode="after")
    def check(self) -> Self:
        if self.decision == "approved" and not self.reference:
            raise ValueError("an approved decision needs a reference")
        return self


class Dataset(Frozen):
    id: Slug
    title: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    creators: list[Annotated[str, StringConstraints(min_length=1, max_length=80)]] = Field(
        min_length=1
    )
    published: date
    version: Annotated[str, StringConstraints(min_length=1, max_length=120)]
    doi: Annotated[str, StringConstraints(pattern=r"^10\.\d{4,9}/\S+$")]
    source_url: HttpsUrl
    download_url: HttpsUrl
    # Exact hosts a download (and its redirects) may use. Required from manifest version 2.
    allowed_download_hosts: list[Annotated[str, StringConstraints(pattern=r"^[a-z0-9.-]+$")]] = []
    citation: Note
    retrieved_on: date
    files: list[FileRecord] = Field(min_length=1)
    license: LicenseInfo
    origin: Origin
    label_provenance: LabelProvenance
    languages: list[Slug] = Field(min_length=1)
    source_labels: dict[str, int]
    label_mapping: dict[str, LabelRule]
    observed: dict[str, int]
    privacy: Privacy
    status: Status
    permitted_use: list[Use]
    limitations: list[Note] = Field(min_length=1)
    approval: Approval

    @model_validator(mode="after")
    def check_policy(self) -> Self:
        if set(self.source_labels) != set(self.label_mapping):
            raise ValueError(f"{self.id}: every source label needs exactly one mapping rule")
        if any(count <= 0 for count in self.source_labels.values()):
            raise ValueError(f"{self.id}: label counts must be positive")
        for label, rule in self.label_mapping.items():
            if label.lower() == "spam" and rule.target in {"phishing", "benign"}:
                raise ValueError(f"{self.id}: spam is its own class, not {rule.target}")
        if self.origin in UNTRUSTED_FOR_EVALUATION and EVALUATION_USES & set(self.permitted_use):
            raise ValueError(f"{self.id}: {self.origin} data cannot validate or evaluate")
        if self.status == "excluded":
            if self.permitted_use:
                raise ValueError(f"{self.id}: excluded data has no permitted uses")
            if self.approval.decision == "approved":
                raise ValueError(f"{self.id}: excluded data cannot be approved")
        elif self.status == "audit_reference_only":
            if set(self.permitted_use) != {"overlap_audit_reference"}:
                raise ValueError(f"{self.id}: audit-only data may only be an audit reference")
        elif not self.permitted_use:
            raise ValueError(f"{self.id}: a candidate needs at least one permitted use")
        return self


class SimulatorExclusion(Frozen):
    catalog: Annotated[str, StringConstraints(min_length=1, max_length=120)]
    catalog_version: int = Field(ge=1)
    rule: Note


class PromotionGate(Frozen):
    """An IMC class becomes `phishing` only when independently reviewed precision clears this."""

    statistic: Literal["wilson_lower_bound"]
    confidence: float = Field(gt=0.5, lt=1)
    minimum: float = Field(gt=0, le=1)
    reviewers_per_item: int = Field(ge=2)
    target_sample_per_class: int = Field(ge=30)
    status_when_incomplete: Literal["BLOCKED"]
    note: Note


SyntheticUse = Literal["training", "validation", "synthetic_stress_test"]


class SyntheticSet(Frozen):
    """Authored data, kept apart from collected data and from the real-world test set."""

    id: Slug
    title: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    generator: Note
    generator_version: int = Field(ge=1)
    seed: int
    label: Literal["benign"]
    corpus_sha256: SHA256
    records: int = Field(gt=0)
    template_families: int = Field(gt=0)
    purpose: Note
    rules: list[Note] = Field(min_length=1)
    reporting: Note
    permitted_use: list[SyntheticUse] = Field(min_length=1)
    approval: Approval


class Policy(Frozen):
    raw_data_in_git: Literal[False]
    raw_text_in_logs_or_reports: Literal[False]
    storage: Note
    reports: Note
    held_out_set: Note
    simulator_exclusion: SimulatorExclusion
    promotion_gate: PromotionGate | None = None
    real_world_test_excludes_synthetic: bool = False


class Task(Frozen):
    id: Slug
    name: Note
    definition: Note
    target_labels: list[TargetLabel]
    scored_label: Literal["phishing"]
    languages_first: list[Slug]


class Decisions(Frozen):
    d04_sms: Decision
    d04_reference: Note | None = None
    open_questions: list[Note]


class Manifest(Frozen):
    manifest_version: int = Field(ge=1)
    created: date
    task: Task
    policy: Policy
    datasets: list[Dataset] = Field(min_length=1)
    synthetic_sets: list[SyntheticSet] = []
    coverage_gaps: list[Note]
    decisions: Decisions

    @model_validator(mode="after")
    def check_manifest(self) -> Self:
        ids = [d.id for d in self.datasets]
        if len(ids) != len(set(ids)):
            raise ValueError("dataset IDs must be unique")
        if self.decisions.d04_sms == "approved":
            if not self.decisions.d04_reference:
                raise ValueError("an approved D04 decision needs a reference")
            candidates = [d for d in self.datasets if d.status.startswith("candidate_")]
            if any(d.approval.decision != "approved" for d in candidates):
                raise ValueError("D04 is approved only when every candidate dataset is")
        for dataset in self.datasets:
            if self.decisions.d04_sms != "approved" and dataset.approval.decision == "approved":
                raise ValueError(f"{dataset.id}: approved before D04")
        if "needs_review" not in self.task.target_labels:
            raise ValueError("the task must keep a needs_review label")
        if self.manifest_version >= 2:
            self.check_v2()
        return self

    def check_v2(self) -> None:
        if self.policy.promotion_gate is None:
            raise ValueError("version 2 needs a promotion gate")
        if not self.policy.real_world_test_excludes_synthetic:
            raise ValueError("the real-world test set must exclude synthetic data")
        if not self.synthetic_sets:
            raise ValueError("version 2 needs the synthetic hard-negative set")
        for synthetic in self.synthetic_sets:
            if synthetic.approval.decision != "approved" and self.decisions.d04_sms == "approved":
                raise ValueError(f"{synthetic.id}: D04 is approved only when every set is")
        for dataset in self.datasets:
            if dataset.status == "excluded":
                continue
            if not dataset.allowed_download_hosts:
                raise ValueError(f"{dataset.id}: needs allowed download hosts")
            if any(f.path_in_download is None for f in dataset.files):
                raise ValueError(f"{dataset.id}: every file needs its path in the download")


def load_manifest(path: Path = DEFAULT_MANIFEST) -> Manifest:
    raw = path.read_bytes()
    if len(raw) > MAX_MANIFEST_BYTES:
        raise ValueError("The dataset manifest is too large")
    return Manifest.model_validate_json(raw)


def check_simulator_exclusion(manifest: Manifest) -> None:
    """The declared catalog version must be the packaged one, so a catalog change forces review."""
    from dataset_governance.fingerprints import simulator_catalog

    declared = manifest.policy.simulator_exclusion.catalog_version
    actual = simulator_catalog()["catalog_version"]
    if declared != actual:
        raise ValueError(f"manifest excludes simulator catalog v{declared}; packaged is v{actual}")


def main(argv: list[str]) -> int:
    path = Path(argv[1]) if len(argv) > 1 else DEFAULT_MANIFEST
    try:
        manifest = load_manifest(path)
        check_simulator_exclusion(manifest)
    except (ValueError, OSError, json.JSONDecodeError) as error:
        print(f"Manifest invalid: {error}", file=sys.stderr)
        return 1
    print(
        f"{path.name}: valid; {len(manifest.datasets)} datasets, D04 {manifest.decisions.d04_sms}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
