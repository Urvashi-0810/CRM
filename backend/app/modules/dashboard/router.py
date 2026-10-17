"""Dashboard: orders (approved letters), vacancies, clients, repeat clients, countries,
ad status, for a chosen period."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Response

from app.deps import CurrentUser, DbSession
from app.modules.dashboard import service
from app.modules.dashboard.export import build_dashboard_workbook

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _range(period: service.Period = "this_month", date_from: date | None = None, date_to: date | None = None) -> service.Range:
    return service.resolve_period(period, date_from, date_to)


PeriodRange = Annotated[service.Range, Depends(_range)]


@router.get("")
async def dashboard(_: CurrentUser, db: DbSession, r: PeriodRange):
    """period = this_month (default) | last_month | this_year | custom (with date_from and date_to,
    inclusive, India time)."""
    return await service.build(db, r)


@router.get("/export", response_class=Response)
async def export_dashboard(_: CurrentUser, db: DbSession, r: PeriodRange):
    data = await service.build(db, r)
    name = f"dashboard_{r.start:%Y-%m-%d}_to_{r.end:%Y-%m-%d}.xlsx"
    return Response(content=build_dashboard_workbook(data), media_type=XLSX,
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})
