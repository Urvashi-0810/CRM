from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]
Lifecycle = Literal["draft", "approved"]
SortField = Literal[
    "approved_at", "-approved_at", "created_at", "-created_at", "demand_code", "-demand_code",
    "employer", "-employer", "country", "-country", "vacancy", "-vacancy",
]


class TradeIn(BaseModel):
    project: ShortText | None = None
    trade: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    quantity: int = Field(gt=0, le=100_000)

    @field_validator("project")
    @classmethod
    def blank_to_none(cls, v: str | None) -> str | None:
        return v or None


class TradeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    project: str | None
    trade: str
    quantity: int


class DemandUpdate(BaseModel):
    """Only the fields sent are changed. Send null (or "") to clear a text field."""

    country: ShortText | None = None
    employer: ShortText | None = None
    vacancy: int | None = Field(default=None, ge=0, le=1_000_000)
    target_timeline: ShortText | None = None
    assign_to: ShortText | None = None


class UserRef(BaseModel):
    id: int
    display_name: str


class DemandSummary(BaseModel):
    """One row of the demand list (or of the drafts section)."""

    id: int
    demand_code: str
    lifecycle: Lifecycle
    progress_status: str
    country: str | None
    employer: str | None
    vacancy: int | None
    target_timeline: str | None
    assign_to: str | None
    approved_at: datetime | None
    approved_by: UserRef | None  # current name, as decided
    created_at: datetime
    created_by: UserRef
    updated_at: datetime
    etag: str
    latest_version_no: int | None = None  # None = no letter generated yet


class DemandDetail(DemandSummary):
    trades: list[TradeOut]


class DemandPage(BaseModel):
    items: list[DemandSummary]
    total: int
    limit: int
    offset: int


class FilterOptions(BaseModel):
    countries: list[str]
    employers: list[str]
    assignees: list[str]
    statuses: list[str]


class DemandFilters(BaseModel):
    """Query parameters shared by the list and the Excel export."""

    lifecycle: Lifecycle = "approved"
    q: str | None = None
    country: str | None = None
    employer: str | None = None
    progress_status: str | None = None
    assign_to: str | None = None
    approved_from: date | None = None
    approved_to: date | None = None
    sort: SortField = "-approved_at"
