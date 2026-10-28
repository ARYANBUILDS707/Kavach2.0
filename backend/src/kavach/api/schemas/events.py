"""Input schemas only: no ingestion, persistence, inference or identity authorization."""

import re
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationInfo,
    field_validator,
)

Identifier = Annotated[
    str,
    StringConstraints(
        strict=True, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$"
    ),
]
Source = Annotated[
    str,
    StringConstraints(
        strict=True, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$"
    ),
]
SampleReference = Annotated[
    str,
    StringConstraints(
        strict=True, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$"
    ),
]
SenderID = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=64)]
RFC3339 = re.compile(r"^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2})$")


class EventBase(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, frozen=True)

    event_id: Identifier
    subscriber_token: Identifier = Field(repr=False)
    timestamp: AwareDatetime
    source: Source

    @field_validator("subscriber_token")
    @classmethod
    def reject_phone_like_token(cls, value: str) -> str:
        # This is a conservative syntax guard, not proof of pseudonymization or authorization.
        if value.replace("-", "").replace(".", "").isdigit():
            raise ValueError("Use an opaque subscriber token, not a telephone number")
        return value

    @field_validator("timestamp", mode="before")
    @classmethod
    def require_rfc3339(cls, value: object) -> object:
        if isinstance(value, datetime):
            return value
        if not isinstance(value, str) or RFC3339.fullmatch(value) is None:
            raise ValueError("Timestamp must be RFC 3339 with an explicit timezone")
        return value

    @field_validator("timestamp")
    @classmethod
    def validate_event_time(cls, value: datetime, info: ValidationInfo) -> datetime:
        # An injected clock permits exact boundary tests without sleeps or time-sensitive fixtures.
        now = (info.context or {}).get("now", datetime.now(UTC))
        value = value.astimezone(UTC)
        if value > now + timedelta(seconds=60):
            raise ValueError("Timestamp exceeds the allowed future skew")
        if value < now - timedelta(days=7):
            raise ValueError("Timestamp exceeds the allowed event age")
        return value


class SMSEvent(EventBase):
    kind: Literal["sms"] = "sms"
    text: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=4096)] = Field(
        repr=False
    )
    sender_id: SenderID | None = Field(default=None, repr=False)

    @field_validator("text", "sender_id")
    @classmethod
    def reject_blank_content(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("Content must not be blank")
        return value


class CallEvent(EventBase):
    kind: Literal["call"] = "call"
    audio_reference: SampleReference | None = None
