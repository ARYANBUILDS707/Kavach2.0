"""Simulator catalog response (API.md "Live updates and simulator")."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from kavach.simulator.catalog import Scenario


class SampleSummary(BaseModel):
    """An allowlisted audio sample. None is approved yet (TD-17), so the list is empty."""

    id: str
    label: str


class SimulatorCatalog(BaseModel):
    catalog_version: int
    synthetic: Literal[True]
    source: str
    scenarios: list[Scenario]
    samples: list[SampleSummary]


class SimulatorCatalogResponse(BaseModel):
    data: SimulatorCatalog
    request_id: UUID
