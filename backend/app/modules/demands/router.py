from datetime import date, datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Header, Query, Response, status

from app.deps import CurrentUser, DbSession
from app.modules.demands import service
from app.modules.demands.export import build_workbook
from app.modules.demands.schemas import (
    DemandDetail,
    DemandFilters,
    DemandPage,
    DemandUpdate,
    FilterOptions,
    Lifecycle,
    SortField,
    TradeIn,
)
from app.modules.storage import StorageDep

router = APIRouter(prefix="/demands", tags=["demands"])



def _filters(
    lifecycle: Lifecycle = "approved",
    q: Annotated[str | None, Query(max_length=200)] = None,
    country: str | None = None,
    employer: str | None = None,
    progress_status: str | None = None,
    assign_to: str | None = None,
    approved_from: date | None = None,
    approved_to: date | None = None,
    sort: SortField = "-approved_at",
) -> DemandFilters:
    return DemandFilters(
        lifecycle=lifecycle, q=q, country=country, employer=employer,
        progress_status=progress_status, assign_to=assign_to,
        approved_from=approved_from, approved_to=approved_to, sort=sort,
    )


Filters = Annotated[DemandFilters, Depends(_filters)]
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _with_etag(response: Response, detail: DemandDetail) -> DemandDetail:
    response.headers["ETag"] = detail.etag
    return detail


@router.post("", response_model=DemandDetail, status_code=status.HTTP_201_CREATED)
async def add_demand_letter(
    current: CurrentUser,
    db: DbSession,
    storage: StorageDep,
    response: Response,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
):
    """"Add Demand Letter": reserves the lowest free demand ID and creates an empty draft.

    Send an Idempotency-Key header (e.g. a UUID per click) so a double click or a
    network retry returns the same draft instead of reserving a second ID.
    """
    demand_id, created = await service.create_draft(
        db, storage, user_id=current.user.id, idempotency_key=idempotency_key
    )
    if not created:
        response.status_code = status.HTTP_200_OK
    response.headers["Location"] = f"/api/v1/demands/{demand_id}"
    return _with_etag(response, await service.get_detail(db, demand_id))


@router.get("", response_model=DemandPage)
async def list_demands(
    _: CurrentUser,
    db: DbSession,
    filters: Filters,
    limit: Annotated[int, Query(ge=1, le=200)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """The demand list (lifecycle=approved, default), the drafts section (lifecycle=draft) or
    the letters waiting for an admin (lifecycle=pending)."""
    items, total = await service.list_demands(db, filters, limit=limit, offset=offset)
    return DemandPage(items=items, total=total, limit=limit, offset=offset)


# Declared before /{demand_id} so these words are never read as an id.
@router.get("/filter-options", response_model=FilterOptions)
async def filter_options(_: CurrentUser, db: DbSession):
    """Values for the filter dropdowns (from approved letters)."""
    return await service.filter_options(db)


@router.get("/export", response_class=Response)
async def export_demands(_: CurrentUser, db: DbSession, filters: Filters):
    """Excel file of every letter matching the current filters."""
    rows = await service.all_matching(db, filters)
    stamp = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d_%H%M")
    name = f"demand-letters_{stamp}.xlsx" if filters.lifecycle == "approved" else f"drafts_{stamp}.xlsx"
    return Response(
        content=build_workbook(rows, filters.lifecycle),
        media_type=XLSX,
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.get("/{demand_id}", response_model=DemandDetail)
async def get_demand(demand_id: int, _: CurrentUser, db: DbSession, response: Response):
    return _with_etag(response, await service.get_detail(db, demand_id))


@router.patch("/{demand_id}", response_model=DemandDetail)
async def update_demand(
    demand_id: int,
    body: DemandUpdate,
    _: CurrentUser,
    db: DbSession,
    response: Response,
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
):
    """Edit country, employer, vacancy, target timeline, assign to.

    Send If-Match with the ETag you loaded; 412 means someone changed it meanwhile.
    """
    return _with_etag(response, await service.update_fields(db, demand_id, if_match, body))


@router.put("/{demand_id}/trades", response_model=DemandDetail)
async def replace_trades(
    demand_id: int,
    body: list[TradeIn],
    _: CurrentUser,
    db: DbSession,
    response: Response,
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
):
    """Replace the whole list of trades (positions). Needs If-Match like PATCH."""
    return _with_etag(response, await service.replace_trades(db, demand_id, if_match, body))


@router.delete("/{demand_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_draft(demand_id: int, _: CurrentUser, db: DbSession, storage: StorageDep):
    """Delete a draft (its folder first, then the row, freeing the ID). Approved → 409."""
    await service.delete_draft(db, storage, demand_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
