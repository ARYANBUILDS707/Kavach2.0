"""Authenticated model readiness (FR12). The public `/health` routes stay unchanged (C-07).

Readiness is operational only: `ready` means the pinned model verified, loaded and passed its
self-test. It says nothing about accuracy; the scores are uncalibrated and the model is not
validated on KAVACH data.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict

from kavach.auth.dependencies import require_role
from kavach.auth.service import ActiveSession
from kavach.models.sms_worker import SmsWorkerSupervisor

router = APIRouter(prefix="/api/v1/system", tags=["system"])

DashboardSession = Annotated[ActiveSession, Depends(require_role("viewer", "analyst", "admin"))]


class SmsModelStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: Literal["disabled", "starting", "ready", "unavailable"]
    detail: str  # the supervisor state code, for example `circuit_open`
    reason: str | None  # last failure or startup refusal code; never content
    model_version: str | None
    score_semantics: Literal["uncalibrated_softmax"] = "uncalibrated_softmax"
    validated_on_kavach_data: Literal[False] = False


class ModelsData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sms_classifier: SmsModelStatus


class ModelsResponse(BaseModel):
    data: ModelsData
    request_id: str


@router.get("/models", response_model=ModelsResponse)
def models(request: Request, _: DashboardSession) -> ModelsResponse:
    supervisor: SmsWorkerSupervisor = request.app.state.sms_worker
    status = supervisor.status()
    reason = status["fatal_code"] if status["state"] == "unverified" else status["last_failure"]
    return ModelsResponse(
        data=ModelsData(
            sms_classifier=SmsModelStatus(
                state=status["public_state"],
                detail=status["state"],
                reason=reason,
                model_version=status["model_version"],
            )
        ),
        request_id=str(request.state.request_id),
    )
