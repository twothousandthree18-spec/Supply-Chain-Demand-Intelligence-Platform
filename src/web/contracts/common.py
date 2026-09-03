"""Phase 6 typed data contracts — common envelope/values.

These are the on-the-wire contracts between the data layer (services) and the
frontend. They enforce the Phase 5 provenance and undefined-value rules:
every metric carries its provenance and an explicit 'undefined' flag so the UI
can render literal "—" rather than a fabricated zero.
"""

from enum import Enum
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class Provenance(str, Enum):
    OBSERVED = "observed"
    DERIVED = "derived"
    SIMULATED = "simulated"


class MetricValue(BaseModel):
    """A scalar metric with provenance and an explicit undefined marker.

    value is None whenever the metric is undefined (zero denominator, no rows,
    absent target) so the consumer renders "—".
    """

    value: float | int | None = None
    unit: str | None = None
    provenance: Provenance = Provenance.DERIVED
    undefined: bool = False

    @classmethod
    def blank(cls, provenance: Provenance = Provenance.DERIVED) -> "MetricValue":
        return cls(value=None, provenance=provenance, undefined=True)


class Pagination(BaseModel):
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=200)
    total: int = Field(ge=0)


class Page(BaseModel, Generic[T]):
    """Server-side pagination envelope used by large result sets."""

    pagination: Pagination
    items: list[T] = Field(default_factory=list)


class ProvenanceContract(BaseModel):
    """Traceable values the shell surfaces (health/meta)."""

    observed_units: int | None = None
    forecast_final_grain: int | None = None
    inventory_grain: int | None = None
    scenario_result_rows: int | None = None
    evaluation_rows: int | None = None
    selected_model: str | None = None
    ets_sarima_pilot_series: int | None = None