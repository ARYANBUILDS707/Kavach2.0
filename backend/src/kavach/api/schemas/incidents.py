"""Incident read DTOs (API.md "SMS MVP-1 contract"). Stored evidence is copied field by field
from an allowlist, never passed through, so no stored key can leak into a response."""

from datetime import datetime
from typing import Any, Literal, Self, get_args
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from kavach.api.schemas.events import RFC3339
from kavach.db.incident_repository import (
    AssessmentRow,
    IncidentFilters,
    IncidentRow,
    LinkedEventRow,
)

Tier = Literal["unknown", "low", "medium", "high", "critical"]
AnalysisStatus = Literal["complete", "partial", "unavailable"]
StageName = Literal["sms_classifier", "transcription", "voice_intent", "synthesis"]
STAGE_NAMES: tuple[str, ...] = get_args(StageName)


class IncidentListQuery(BaseModel):
    """Every accepted query parameter; anything else (including `review_status`) is 422."""

    model_config = ConfigDict(extra="forbid", populate_by_name=False)

    limit: int = Field(25, ge=1, le=100)
    cursor: str | None = Field(None, min_length=1, max_length=512)
    kind: Literal["standalone", "pair"] | None = None
    tier: Tier | None = None
    channel: Literal["sms", "call"] | None = None
    occurred_from: datetime | None = Field(None, alias="from")
    occurred_to: datetime | None = Field(None, alias="to")

    @field_validator("occurred_from", "occurred_to", mode="before")
    @classmethod
    def explicit_offset(cls, value: Any) -> Any:
        if value is not None and (not isinstance(value, str) or not RFC3339.fullmatch(value)):
            raise ValueError("an RFC 3339 timestamp with an explicit offset is required")
        return value

    @model_validator(mode="after")
    def ordered_range(self) -> Self:
        if (
            self.occurred_from is not None
            and self.occurred_to is not None
            and self.occurred_from >= self.occurred_to
        ):
            raise ValueError("from must be before to")
        return self

    def filters(self) -> IncidentFilters:
        return IncidentFilters(
            kind=self.kind,
            tier=self.tier,
            channel=self.channel,
            occurred_from=self.occurred_from,
            occurred_to=self.occurred_to,
        )


class IncidentSummary(BaseModel):
    """Enum fields are CHECK-constrained in the database and validated again here."""

    id: UUID
    kind: Literal["standalone", "pair"]
    occurred_at: datetime
    tier: Tier
    final_score: float | None
    analysis_status: AnalysisStatus
    current_revision: int
    version: int
    latest_review: None = None  # reviews are postponed beyond MVP-1
    updated_at: datetime

    @classmethod
    def of(cls, row: IncidentRow) -> "IncidentSummary":
        return cls(
            id=row.id,
            kind=row.kind,
            occurred_at=row.occurred_at,
            tier=row.tier,
            final_score=row.final_score,
            analysis_status=row.analysis_status,
            current_revision=row.current_revision,
            version=row.version,
            updated_at=row.updated_at,
        )


class PageInfo(BaseModel):
    next_cursor: str | None
    has_more: bool


class IncidentListResponse(BaseModel):
    data: list[IncidentSummary]
    page: PageInfo
    request_id: UUID


class ModelOutput(BaseModel):
    """Native uncalibrated softmax outputs: not probabilities, not `sms_score`, not a tier."""

    labels: dict[str, float]
    top_label: str
    score_semantics: Literal["uncalibrated_softmax"]
    truncated: bool


class Stage(BaseModel):
    status: Literal["complete", "unavailable"]
    reason: str | None
    duration_ms: int
    model_output: ModelOutput | None = None


def stage_of(stored: dict[str, Any]) -> Stage:
    output = stored.get("model_output") if stored.get("status") == "complete" else None
    return Stage(
        status=stored["status"],
        reason=stored.get("reason"),
        duration_ms=stored["duration_ms"],
        model_output=(
            ModelOutput(
                labels=output["labels"],
                top_label=output["top_label"],
                score_semantics=output["score_semantics"],
                truncated=output["truncated"],
            )
            if output is not None
            else None
        ),
    )


def versions_of(stored: dict[str, Any]) -> dict[str, str]:
    return {name: str(stored[name]) for name in STAGE_NAMES if name in stored}


class IncidentEventView(BaseModel):
    """No source, external event ID, subscriber or payload digest, text or sender (API.md)."""

    id: UUID
    channel: Literal["sms", "call"]
    occurred_at: datetime
    received_at: datetime
    analysis_status: AnalysisStatus
    processing_ms: int
    sms_score: float | None
    reason_codes: list[str]
    stages: dict[StageName, Stage]
    model_versions: dict[str, str]

    @classmethod
    def of(cls, row: LinkedEventRow) -> "IncidentEventView":
        stored_stages = row.signals.get("stages", {})
        return cls(
            id=row.id,
            channel=row.channel,
            occurred_at=row.occurred_at,
            received_at=row.received_at,
            analysis_status=row.analysis_status,
            processing_ms=row.processing_ms,
            sms_score=row.sms_score,
            reason_codes=[str(code) for code in row.signals.get("reason_codes", [])],
            stages={
                name: stage_of(stored_stages[name]) for name in STAGE_NAMES if name in stored_stages
            },
            model_versions=versions_of(row.model_versions),
        )


class AssessmentView(BaseModel):
    revision: int
    tier: Tier
    base_score: float | None
    fusion_score: float | None
    final_score: float | None
    analysis_status: AnalysisStatus
    policy_version: str
    model_versions: dict[str, str]
    created_at: datetime

    @classmethod
    def of(cls, row: AssessmentRow) -> "AssessmentView":
        return cls(
            revision=row.revision,
            tier=row.tier,
            base_score=row.base_score,
            fusion_score=row.fusion_score,
            final_score=row.final_score,
            analysis_status=row.analysis_status,
            policy_version=row.policy_version,
            model_versions=versions_of(row.model_versions),
            created_at=row.created_at,
        )


class ReviewPage(BaseModel):
    """Always empty in MVP-1: reviews are postponed."""

    items: list[None] = []
    page: PageInfo = PageInfo(next_cursor=None, has_more=False)


class IncidentDetailData(IncidentSummary):
    events: list[IncidentEventView]
    assessment: AssessmentView
    related_incident_ids: list[UUID]
    reviews: ReviewPage = ReviewPage()


class IncidentDetailResponse(BaseModel):
    data: IncidentDetailData
    request_id: UUID
