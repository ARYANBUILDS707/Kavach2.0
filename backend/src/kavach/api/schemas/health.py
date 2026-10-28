"""Liveness does not imply model or dependency readiness."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class HealthData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"] = "ok"
    scope: Literal["liveness"] = "liveness"
    analysis_ready: Literal[False] = False


class HealthResponse(BaseModel):
    data: HealthData
    request_id: UUID
