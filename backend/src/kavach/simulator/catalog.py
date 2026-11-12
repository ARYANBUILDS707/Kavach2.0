"""The versioned synthetic scenario catalog (M3.3; API.md "Live updates and simulator").

`scenarios_v1.json` ships with the package and is validated strictly on load. Every scenario
is fictional: SMS text starts with `[SIMULATED]`, links use the reserved `.invalid` domain,
there are no phone numbers, and subscribers are aliases that the runner turns into opaque
run-specific tokens. Event times are offsets from the moment a scenario starts.

Expectations describe the current contract: HTTP outcome per step and, for stored events,
whether the Redis candidate index should hold them (`indexed`) and whether D05 would call
them late (`late`). Both derive from the *provisional* D05 window and lateness (TD-20); the
validator recomputes them, so the catalog cannot drift from the code.

`truth` labels are simulation-only ground truth written by the scenario author. They are
never sent to the API, never stored, and are not model outputs.
"""

import re
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from importlib.resources import files
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from kavach.api.schemas.events import SampleReference, SenderID, Source
from kavach.correlation.candidates import (
    ALLOWED_LATENESS,
    CANDIDATE_HORIZON,
    CORRELATION_WINDOW,
    is_indexable,
    is_late,
)
from kavach.services.ingestion import APPROVED_AUDIO_REFERENCES

CATALOG_FILE = "scenarios_v1.json"
MAX_CATALOG_BYTES = 64 * 1024
MAX_STEPS_PER_SCENARIO = 10
# Offsets must sit at least this far from a D05 boundary, so that pacing and retries during a
# run (seconds, at most a minute) cannot flip an expectation.
BOUNDARY_MARGIN = timedelta(minutes=2)
MAX_EVENT_AGE = timedelta(days=1)
SYNTHETIC_MARKER = "[SIMULATED] "
DIGIT_RUN = re.compile(r"\d{7,}")
URL_HOST = re.compile(r"[a-z][a-z0-9+.-]*://([^/\s?#]+)", re.IGNORECASE)

ScenarioId = Annotated[str, StringConstraints(strict=True, pattern=r"^S\d{2}$")]
StepId = Annotated[str, StringConstraints(strict=True, pattern=r"^[a-z][a-z0-9_]{0,31}$")]
Alias = Annotated[str, StringConstraints(strict=True, pattern=r"^[a-z]{1,16}$")]
EventLabel = Literal["legitimate_sms", "phishing_sms", "legitimate_call", "scam_intent_call"]
ScenarioLabel = Literal[
    "benign", "fraudulent", "coordinated_fraud_journey", "unrelated_events", "protocol_check"
]
ErrorCode = Literal["FORBIDDEN", "EVENT_ID_CONFLICT", "UNKNOWN_AUDIO_REFERENCE"]


def synthetic_text(value: str) -> str:
    if not value.startswith(SYNTHETIC_MARKER):
        raise ValueError(f"SMS text must start with {SYNTHETIC_MARKER.strip()}")
    if DIGIT_RUN.search(value):
        raise ValueError("SMS text must not contain phone-number-like digit runs")
    for host in URL_HOST.findall(value):
        if not host.lower().endswith(".invalid"):
            raise ValueError("Links in SMS text must use the reserved .invalid domain")
    return value


SyntheticText = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=1024)]


class Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class Expectation(Frozen):
    status: Literal[200, 201, 403, 409, 422]
    code: ErrorCode | None = None
    # Stored (201) events only; provisional D05 behavior.
    indexed: bool | None = None
    late: bool | None = None


class SubmitStep(Frozen):
    action: Literal["submit"]
    step: StepId
    kind: Literal["sms", "call"]
    subscriber: Alias
    offset_seconds: int = Field(le=0, ge=-int(MAX_EVENT_AGE.total_seconds()))
    text: SyntheticText | None = Field(default=None, repr=False)
    sender_id: SenderID | None = None
    audio_reference: SampleReference | None = None
    # Only to exercise source scoping: a source the simulator key does not hold.
    source: Source | None = None
    truth: EventLabel
    expect: Expectation

    @model_validator(mode="after")
    def check_fields(self) -> Self:
        if self.kind == "sms":
            if self.text is None or self.audio_reference is not None:
                raise ValueError(f"{self.step}: an SMS needs text and no audio reference")
            synthetic_text(self.text)
        elif self.text is not None or self.sender_id is not None:
            raise ValueError(f"{self.step}: a call has no text or sender")
        return self


class ReplayStep(Frozen):
    """Resubmit an earlier step's exact payload and event ID."""

    action: Literal["replay"]
    step: StepId
    of: StepId
    expect: Expectation


class ConflictStep(Frozen):
    """Reuse an earlier SMS step's event ID with different text."""

    action: Literal["conflict"]
    step: StepId
    of: StepId
    text: SyntheticText = Field(repr=False)
    expect: Expectation

    @model_validator(mode="after")
    def check_text(self) -> Self:
        synthetic_text(self.text)
        return self


Step = Annotated[SubmitStep | ReplayStep | ConflictStep, Field(discriminator="action")]


class CandidatePair(Frozen):
    between: tuple[StepId, StepId]
    # True: each is within the D05 window of the other in the same subscriber's candidate set.
    linked: bool


def expected_outcome(step: SubmitStep, catalog_source: str) -> tuple[int, str | None]:
    """The response the current contract requires for a new submission (API.md order)."""
    if step.source is not None and step.source != catalog_source:
        return 403, "FORBIDDEN"
    if step.audio_reference is not None and step.audio_reference not in APPROVED_AUDIO_REFERENCES:
        return 422, "UNKNOWN_AUDIO_REFERENCE"
    return 201, None


def clear_of(offset: timedelta, boundary: timedelta) -> bool:
    return abs(offset + boundary) >= BOUNDARY_MARGIN


class Scenario(Frozen):
    id: ScenarioId
    version: int = Field(ge=1)
    name: Annotated[str, StringConstraints(min_length=1, max_length=80)]
    description: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    expected_summary: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    truth: ScenarioLabel
    # Decisions an expectation depends on that are not formally approved yet.
    provisional: list[Literal["D05"]]
    steps: list[Step] = Field(min_length=1, max_length=MAX_STEPS_PER_SCENARIO)
    candidate_pairs: list[CandidatePair]

    def submit_step(self, step_id: str) -> SubmitStep:
        for step in self.steps:
            if step.step == step_id and isinstance(step, SubmitStep):
                return step
        raise KeyError(step_id)

    def stored_steps(self) -> list[SubmitStep]:
        return [s for s in self.steps if isinstance(s, SubmitStep) and s.expect.status == 201]

    def check_consistency(self, catalog_source: str) -> None:
        seen: dict[str, Step] = {}
        anchor = datetime(2026, 1, 1, tzinfo=UTC)
        needs_d05 = bool(self.candidate_pairs)
        for step in self.steps:
            if step.step in seen:
                raise ValueError(f"{self.id}: duplicate step {step.step}")
            expect = step.expect
            if isinstance(step, SubmitStep):
                wanted = expected_outcome(step, catalog_source)
            else:
                target = seen.get(step.of)
                if not isinstance(target, SubmitStep) or target.expect.status != 201:
                    raise ValueError(f"{self.id}: {step.step} must follow a stored submit step")
                if isinstance(step, ConflictStep) and (
                    target.kind != "sms" or target.text == step.text
                ):
                    raise ValueError(f"{self.id}: {step.step} must change an SMS text")
                wanted = (200, None) if isinstance(step, ReplayStep) else (409, "EVENT_ID_CONFLICT")
            if (expect.status, expect.code) != wanted:
                raise ValueError(f"{self.id}: {step.step} must expect {wanted}")
            if not isinstance(step, SubmitStep) or expect.status != 201:
                if expect.indexed is not None or expect.late is not None:
                    raise ValueError(f"{self.id}: {step.step} is not stored; no index expectation")
            else:
                offset = timedelta(seconds=step.offset_seconds)
                if not (clear_of(offset, ALLOWED_LATENESS) and clear_of(offset, CANDIDATE_HORIZON)):
                    raise ValueError(f"{self.id}: {step.step} is too close to a D05 boundary")
                event_time = anchor + offset
                if expect.indexed != is_indexable(event_time, anchor) or expect.late != is_late(
                    event_time, anchor
                ):
                    raise ValueError(f"{self.id}: {step.step} has wrong indexed/late expectations")
                needs_d05 = needs_d05 or expect.late or not expect.indexed
            seen[step.step] = step
        for pair in self.candidate_pairs:
            first, second = (self.submit_step(s) for s in pair.between)
            if first.expect.status != 201 or second.expect.status != 201 or first is second:
                raise ValueError(f"{self.id}: candidate pairs need two stored events")
            gap = abs(first.offset_seconds - second.offset_seconds)
            linked = (
                first.subscriber == second.subscriber
                and bool(first.expect.indexed and second.expect.indexed)
                and gap <= CORRELATION_WINDOW.total_seconds()
            )
            if linked != pair.linked:
                raise ValueError(f"{self.id}: candidate pair {pair.between} is mislabeled")
        if needs_d05 and "D05" not in self.provisional:
            raise ValueError(f"{self.id}: expectations depend on D05 and must say so")


class ScenarioCatalog(Frozen):
    catalog_version: int = Field(ge=1)
    synthetic: Literal[True]
    # The single source every scenario submits as (the simulator key's scope).
    source: Source
    scenarios: list[Scenario] = Field(min_length=1)

    @model_validator(mode="after")
    def check_scenarios(self) -> Self:
        ids = [scenario.id for scenario in self.scenarios]
        if ids != sorted(set(ids)):
            raise ValueError("Scenario IDs must be unique and in order")
        for scenario in self.scenarios:
            try:
                scenario.check_consistency(self.source)
            except KeyError as missing:
                raise ValueError(f"{scenario.id}: unknown step {missing}") from None
        return self

    def scenario(self, scenario_id: str) -> Scenario:
        for scenario in self.scenarios:
            if scenario.id == scenario_id:
                return scenario
        raise KeyError(scenario_id)


def parse_catalog(raw: bytes) -> ScenarioCatalog:
    if len(raw) > MAX_CATALOG_BYTES:
        raise ValueError("The scenario catalog is too large")
    return ScenarioCatalog.model_validate_json(raw)


@lru_cache(maxsize=1)
def load_catalog() -> ScenarioCatalog:
    """The packaged catalog, validated once per process."""
    return parse_catalog((files("kavach.simulator") / CATALOG_FILE).read_bytes())
