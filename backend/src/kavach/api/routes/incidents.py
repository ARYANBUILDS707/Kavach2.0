"""Incident reads for viewers, analysts and admins (API.md "SMS MVP-1 contract"): thin adapters
over IncidentReadService. Session only; ingestion keys never read incidents."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import ValidationError

from kavach.api.schemas.errors import error_responses
from kavach.api.schemas.incidents import (
    AssessmentView,
    IncidentDetailData,
    IncidentDetailResponse,
    IncidentEventView,
    IncidentListQuery,
    IncidentListResponse,
    IncidentSummary,
    PageInfo,
)
from kavach.auth.dependencies import reject_mixed_credentials, require_reader, unavailable
from kavach.auth.service import ActiveSession
from kavach.core.errors import ApiError
from kavach.services.incidents import IncidentReadService, IncidentsUnavailable, InvalidCursor

router = APIRouter(
    prefix="/api/v1/incidents",
    tags=["incidents"],
    dependencies=[Depends(reject_mixed_credentials)],
)

# Every incident read is counted against the D08 read limit.
DashboardSession = Annotated[ActiveSession, Depends(require_reader("viewer", "analyst", "admin"))]


def incident_service(request: Request) -> IncidentReadService:
    service: IncidentReadService | None = request.app.state.incidents
    if service is None:
        raise unavailable("Incident reads are not configured")
    return service


IncidentServiceDep = Annotated[IncidentReadService, Depends(incident_service)]


def invalid_request() -> ApiError:
    # Same safe message as other validation failures: no field values are echoed.
    return ApiError(422, "VALIDATION_ERROR", "Request validation failed")


def list_query(request: Request) -> IncidentListQuery:
    """Unknown (including `review_status`) and repeated parameters are rejected, not ignored."""
    items = request.query_params.multi_items()
    if len({name for name, _ in items}) != len(items):
        raise invalid_request()
    try:
        return IncidentListQuery.model_validate(dict(items))
    except ValidationError:
        raise invalid_request() from None


def documented_query_parameters() -> list[dict[str, Any]]:
    """OpenAPI entries for the parameters `list_query` parses itself, from the same model."""
    schema = IncidentListQuery.model_json_schema(by_alias=True)
    parameters = []
    for name, field in schema["properties"].items():
        options = [option for option in field.get("anyOf", [field]) if option != {"type": "null"}]
        [value] = options
        value = {k: v for k, v in value.items() if k != "title"}
        if "default" in field and field["default"] is not None:
            value["default"] = field["default"]
        parameters.append({"name": name, "in": "query", "required": False, "schema": value})
    return parameters


def not_found() -> ApiError:
    # Missing, expired and malformed IDs are indistinguishable.
    return ApiError(404, "NOT_FOUND", "Request could not be served")


@router.get(
    "",
    response_model=IncidentListResponse,
    responses=error_responses(400, 401, 422, 429, 503),
    openapi_extra={"parameters": documented_query_parameters()},
)
def list_incidents(
    request: Request,
    _: DashboardSession,
    service: IncidentServiceDep,
    query: Annotated[IncidentListQuery, Depends(list_query)],
) -> IncidentListResponse:
    try:
        page = service.list(query.filters(), query.limit, query.cursor)
    except InvalidCursor:
        raise ApiError(400, "INVALID_CURSOR", "The page cursor is not valid here") from None
    except IncidentsUnavailable:
        raise unavailable("Incidents are temporarily unavailable") from None
    return IncidentListResponse(
        data=[IncidentSummary.of(row) for row in page.items],
        page=PageInfo(next_cursor=page.next_cursor, has_more=page.next_cursor is not None),
        request_id=request.state.request_id,
    )


@router.get(
    "/{incident_id}",
    response_model=IncidentDetailResponse,
    responses=error_responses(401, 404, 429, 503),
)
def get_incident(
    incident_id: str, request: Request, _: DashboardSession, service: IncidentServiceDep
) -> IncidentDetailResponse:
    try:
        parsed = UUID(incident_id)
    except ValueError:
        raise not_found() from None
    try:
        detail = service.detail(parsed)
    except IncidentsUnavailable:
        raise unavailable("Incidents are temporarily unavailable") from None
    if detail is None:
        raise not_found()
    summary = IncidentSummary.of(detail.incident)
    return IncidentDetailResponse(
        data=IncidentDetailData(
            **summary.model_dump(),
            events=[IncidentEventView.of(event) for event in detail.events],
            assessment=AssessmentView.of(detail.assessment),
            related_incident_ids=detail.related_incident_ids,
        ),
        request_id=request.state.request_id,
    )
