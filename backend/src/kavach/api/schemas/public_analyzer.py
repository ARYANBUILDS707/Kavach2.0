"""Class-only anonymous inference contract; no message or model scores in responses."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PublicSmsInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    text: str = Field(min_length=1, max_length=4096)

    @field_validator("text")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip() or any(0xD800 <= ord(char) <= 0xDFFF for char in value):
            raise ValueError("Invalid text")
        return value


class PublicPrediction(BaseModel):
    prediction: Literal["fraud", "spam", "legitimate"]
    experimental: Literal[True] = True
    truncated: bool
    model_ms: int = Field(ge=0)
    total_ms: int = Field(ge=0)


class PublicPredictionResponse(BaseModel):
    data: PublicPrediction
    request_id: UUID


class PublicAnalyzerStatus(BaseModel):
    enabled: bool
    max_chars: int
    experimental: Literal[True] = True


class PublicStatusResponse(BaseModel):
    data: PublicAnalyzerStatus
    request_id: UUID
