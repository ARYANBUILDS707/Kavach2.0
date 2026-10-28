"""Minimal public health aliases for the foundation phase."""

from fastapi import APIRouter, Request

from kavach.api.schemas.health import HealthData, HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
@router.get("/api/v1/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    """Report that the HTTP process responds, never that fraud analysis is ready."""
    return HealthResponse(data=HealthData(), request_id=request.state.request_id)
