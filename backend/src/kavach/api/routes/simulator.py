"""Read-only simulator catalog for admins (API.md, C-03). Scenarios are submitted through the
ordinary event endpoints; this route never creates events or scores."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from kavach.api.schemas.simulator import SimulatorCatalog, SimulatorCatalogResponse
from kavach.auth.dependencies import reject_mixed_credentials, require_role
from kavach.auth.service import ActiveSession
from kavach.simulator.catalog import load_catalog

router = APIRouter(prefix="/api/v1/simulator", tags=["simulator"])


@router.get(
    "/scenarios",
    response_model=SimulatorCatalogResponse,
    dependencies=[Depends(reject_mixed_credentials)],
)
def get_scenarios(
    request: Request, session: Annotated[ActiveSession, Depends(require_role("admin"))]
) -> SimulatorCatalogResponse:
    catalog = load_catalog()
    return SimulatorCatalogResponse(
        data=SimulatorCatalog(
            catalog_version=catalog.catalog_version,
            synthetic=catalog.synthetic,
            source=catalog.source,
            scenarios=catalog.scenarios,
            # No audio sample manifest is approved (TD-17); calls are metadata-only.
            samples=[],
        ),
        request_id=request.state.request_id,
    )
