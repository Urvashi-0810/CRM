"""Create Advertisement: approved letters for the advertising team (read-only letters,
ad status/assignee set by hand, exports for Canva and Figma)."""

from datetime import date, datetime, UTC
from typing import Annotated, Literal
from urllib.parse import quote
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, StringConstraints
from app.deps import AppSettings, CurrentUser, DbSession
from app.errors import ProblemError
from app.modules.ads.convert import docx_to_pdf, pdf_to_images, zip_pages
from app.modules.ads.export import build_ads_workbook
from app.modules.demands import service as demands_service
from app.modules.demands.models import DemandLetter, StoredFile
from app.modules.demands.schemas import AdStatus, DemandFilters, DemandPage, DemandSummary, FilterOptions, SortField
from app.modules.letters.service import latest_version
from app.modules.storage import StorageDep, StorageError, demand_folder

router = APIRouter(prefix="/ads", tags=["advertisements"])

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
FORMATS_BY_TOOL = {"canva": ("docx", "pdf"), "figma": ("png", "jpg")}
MEDIA = {"docx": DOCX, "pdf": "application/pdf", "png": "image/png", "jpg": "image/jpeg", "zip": "application/zip"}


def _filters(
    q: Annotated[str | None, Query(max_length=200)] = None,
    country: str | None = None,
    employer: str | None = None,
    ad_status: AdStatus | None = None,
    ad_assigned_to: str | None = None,
    approved_from: date | None = None,
    approved_to: date | None = None,
    sort: SortField = "-approved_at",
) -> DemandFilters:
    # Approved letters only: drafts and letters waiting for approval never show here.
    return DemandFilters(
        lifecycle="approved", q=q, country=country, employer=employer, ad_status=ad_status,
        ad_assigned_to=ad_assigned_to, approved_from=approved_from, approved_to=approved_to, sort=sort,
    )


Filters = Annotated[DemandFilters, Depends(_filters)]


async def _approved(db, demand_id: int) -> DemandLetter:
    demand = await db.get(DemandLetter, demand_id)
    if demand is None or demand.lifecycle != "approved":
        raise ProblemError(404, "demand-not-found", "Approved demand letter not found")
    return demand


@router.get("", response_model=DemandPage)
async def list_ads(
    _: CurrentUser, db: DbSession, filters: Filters,
    limit: Annotated[int, Query(ge=1, le=200)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    items, total = await demands_service.list_demands(db, filters, limit=limit, offset=offset)
    return DemandPage(items=items, total=total, limit=limit, offset=offset)


@router.get("/filter-options", response_model=FilterOptions)
async def filter_options(_: CurrentUser, db: DbSession):
    return await demands_service.filter_options(db)


@router.get("/export", response_class=Response)
async def export_ads(_: CurrentUser, db: DbSession, filters: Filters):
    """Excel file of every row matching the current filters."""
    rows = await demands_service.all_matching(db, filters)
    stamp = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d_%H%M")
    return Response(
        content=build_ads_workbook(rows), media_type=XLSX,
        headers={"Content-Disposition": f'attachment; filename="advertisements_{stamp}.xlsx"'},
    )


class AdUpdate(BaseModel):
    """Only the fields sent are changed. Send "" or null to clear the assignee."""

    ad_status: AdStatus | None = None
    ad_assigned_to: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None


@router.patch("/{demand_id}", response_model=DemandSummary)
async def update_ad(demand_id: int, body: AdUpdate, current: CurrentUser, db: DbSession):
    """Change the ad status and/or who the ad is assigned to. Records who changed it and when.
    The letter itself can't be changed here."""
    demand = await _approved(db, demand_id)
    sent = body.model_fields_set
    if "ad_status" in sent:
        if body.ad_status is None:
            raise ProblemError(422, "validation-error", "Choose an ad status")
        demand.ad_status = body.ad_status
    if "ad_assigned_to" in sent:
        demand.ad_assigned_to = body.ad_assigned_to or None
    if sent:
        demand.ad_updated_by = current.user.id
        demand.ad_updated_at = datetime.now(UTC)
    await db.commit()
    return (await demands_service.get_detail(db, demand_id)).model_dump(exclude={"trades"})


@router.get("/{demand_id}/export")
async def export_for_tool(
    demand_id: int, _: CurrentUser, db: DbSession, storage: StorageDep, settings: AppSettings,
    tool: Literal["canva", "figma"], format: Literal["docx", "pdf", "png", "jpg"],
):
    """The newest version of the letter for Canva (.docx or PDF) or Figma (PNG or JPG, one
    image per page; a .zip when the letter has more than one page)."""
    if format not in FORMATS_BY_TOOL[tool]:
        allowed = " or ".join(f.upper() for f in FORMATS_BY_TOOL[tool])
        raise ProblemError(422, "unsupported-format", f"{tool.title()} takes {allowed}")
    demand = await _approved(db, demand_id)
    version = await latest_version(db, demand_id)
    if version is None:
        raise ProblemError(404, "no-letter-yet", "No letter generated yet")
    docx_file = await db.get(StoredFile, version.docx_file_id)
    base = f"{demand.demand_code}_v{version.version_no}"
    try:
        docx = await storage.read(docx_file.storage_key)
        if format == "docx":
            return _download(docx, "docx", base)
        # One PDF per version: converted once, then reused.
        pdf_key = f"{demand_folder(demand.demand_code)}/exports/{docx_file.id}.pdf"
        if await storage.exists(pdf_key):
            pdf = await storage.read(pdf_key)
        else:
            pdf = await docx_to_pdf(docx, settings.libreoffice_path)
            await storage.write(pdf_key, pdf)
    except StorageError:
        raise ProblemError(503, "storage-unavailable", "File storage is unavailable", "Try again in a moment.")
    if format == "pdf":
        return _download(pdf, "pdf", base)
    pages = await pdf_to_images(pdf, format)
    if len(pages) == 1:
        return _download(pages[0], format, base)
    return _download(zip_pages(pages, base, format), "zip", f"{base}_{format}-pages")


def _download(data: bytes, ext: str, base: str) -> Response:
    return Response(
        content=data, media_type=MEDIA[ext],
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(f'{base}.{ext}')}",
            "X-Content-Type-Options": "nosniff",
        },
    )
