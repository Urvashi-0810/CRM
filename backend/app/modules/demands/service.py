from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import Select, and_, delete, func, insert, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.errors import ProblemError
from app.modules.demands.id_allocator import allocate_id_number
from app.modules.demands.models import DemandLetter, DemandTrade, IdempotencyKey
from app.modules.letters.models import LetterVersion
from app.modules.demands.schemas import (
    DemandDetail,
    DemandFilters,
    DemandSummary,
    DemandUpdate,
    FilterOptions,
    TradeIn,
    TradeOut,
    UserRef,
)
from app.modules.storage import Storage, StorageError, demand_folder
from app.modules.users.models import User

IST = ZoneInfo("Asia/Kolkata")

Creator = aliased(User, name="creator")
Approver = aliased(User, name="approver")
Submitter = aliased(User, name="submitter")
AdUpdater = aliased(User, name="ad_updater")


def etag_of(demand: DemandLetter) -> str:
    return f'"{demand.id}-v{demand.row_version}"'


def _not_found() -> ProblemError:
    return ProblemError(404, "demand-not-found", "Demand letter not found")


# ---------- reading ----------


def _base_query() -> Select:
    latest_version = (
        select(func.max(LetterVersion.version_no))
        .where(LetterVersion.demand_id == DemandLetter.id)
        .correlate(DemandLetter)
        .scalar_subquery()
    )
    return (
        select(
            DemandLetter, Creator.display_name, Approver.display_name, latest_version,
            Submitter.display_name, AdUpdater.display_name,
        )
        .join(Creator, Creator.id == DemandLetter.created_by)
        .outerjoin(Approver, Approver.id == DemandLetter.approved_by)
        .outerjoin(Submitter, Submitter.id == DemandLetter.submitted_by)
        .outerjoin(AdUpdater, AdUpdater.id == DemandLetter.ad_updated_by)
    )


def _to_summary(
    demand: DemandLetter, creator_name: str, approver_name: str | None, latest_version_no: int | None,
    submitter_name: str | None = None, ad_updater_name: str | None = None,
) -> dict:
    return dict(
        latest_version_no=latest_version_no,
        id=demand.id,
        demand_code=demand.demand_code,
        lifecycle=demand.lifecycle,
        progress_status=demand.progress_status,
        country=demand.country,
        employer=demand.employer,
        vacancy=demand.vacancy,
        target_timeline=demand.target_timeline,
        assign_to=demand.assign_to,
        approved_at=demand.approved_at,
        approved_by=UserRef(id=demand.approved_by, display_name=approver_name)
        if demand.approved_by
        else None,
        submitted_at=demand.submitted_at,
        submitted_by=UserRef(id=demand.submitted_by, display_name=submitter_name)
        if demand.submitted_by
        else None,
        ad_status=demand.ad_status,
        ad_assigned_to=demand.ad_assigned_to,
        ad_updated_at=demand.ad_updated_at,
        ad_updated_by=UserRef(id=demand.ad_updated_by, display_name=ad_updater_name)
        if demand.ad_updated_by
        else None,
        created_at=demand.created_at,
        created_by=UserRef(id=demand.created_by, display_name=creator_name),
        updated_at=demand.updated_at,
        etag=etag_of(demand),
    )


def _ist_day_start(day) -> datetime:
    return datetime.combine(day, time.min, tzinfo=IST)


def _apply_filters(query: Select, f: DemandFilters) -> Select:
    query = query.where(DemandLetter.lifecycle == f.lifecycle)
    if f.q and f.q.strip():
        like = f"%{f.q.strip()}%"
        query = query.where(
            or_(
                DemandLetter.demand_code.ilike(like),
                DemandLetter.employer.ilike(like),
                DemandLetter.country.ilike(like),
                DemandLetter.assign_to.ilike(like),
                DemandLetter.target_timeline.ilike(like),
            )
        )
    if f.country:
        query = query.where(DemandLetter.country == f.country)
    if f.employer:
        query = query.where(DemandLetter.employer == f.employer)
    if f.progress_status:
        query = query.where(DemandLetter.progress_status == f.progress_status)
    if f.assign_to:
        query = query.where(DemandLetter.assign_to == f.assign_to)
    if f.ad_status:
        query = query.where(DemandLetter.ad_status == f.ad_status)
    if f.ad_assigned_to:
        query = query.where(DemandLetter.ad_assigned_to == f.ad_assigned_to)
    # Dates are calendar days in India time, inclusive on both ends.
    if f.approved_from:
        query = query.where(DemandLetter.approved_at >= _ist_day_start(f.approved_from))
    if f.approved_to:
        query = query.where(DemandLetter.approved_at < _ist_day_start(f.approved_to + timedelta(days=1)))
    return query


_SORT_COLUMNS = {
    "approved_at": DemandLetter.approved_at,
    "created_at": DemandLetter.created_at,
    "submitted_at": DemandLetter.submitted_at,
    "demand_code": DemandLetter.demand_code,
    "employer": DemandLetter.employer,
    "country": DemandLetter.country,
    "vacancy": DemandLetter.vacancy,
}


def _apply_sort(query: Select, sort: str) -> Select:
    descending = sort.startswith("-")
    column = _SORT_COLUMNS[sort.lstrip("-")]
    ordered = column.desc().nulls_last() if descending else column.asc().nulls_last()
    return query.order_by(ordered, DemandLetter.id.desc())


def validate_date_range(f: DemandFilters) -> None:
    if f.approved_from and f.approved_to and f.approved_from > f.approved_to:
        raise ProblemError(
            422, "validation-error", "Some fields are invalid",
            "Fix the listed fields and try again.",
            errors=[{"field": "approved_to", "message": "Must be on or after the start date."}],
        )


async def list_demands(
    db: AsyncSession, f: DemandFilters, *, limit: int, offset: int
) -> tuple[list[DemandSummary], int]:
    validate_date_range(f)
    filtered = _apply_filters(_base_query(), f)
    total = (
        await db.execute(select(func.count()).select_from(filtered.order_by(None).subquery()))
    ).scalar_one()
    rows = (await db.execute(_apply_sort(filtered, f.sort).limit(limit).offset(offset))).all()
    return [DemandSummary(**_to_summary(*row)) for row in rows], total


async def all_matching(db: AsyncSession, f: DemandFilters) -> list[DemandSummary]:
    """Every row matching the filters (for the Excel export)."""
    validate_date_range(f)
    rows = (await db.execute(_apply_sort(_apply_filters(_base_query(), f), f.sort))).all()
    return [DemandSummary(**_to_summary(*row)) for row in rows]


async def filter_options(db: AsyncSession) -> FilterOptions:
    async def distinct(column) -> list[str]:
        result = await db.execute(
            select(column)
            .where(DemandLetter.lifecycle == "approved", column.is_not(None), column != "")
            .distinct()
            .order_by(column)
        )
        return list(result.scalars())

    return FilterOptions(
        countries=await distinct(DemandLetter.country),
        employers=await distinct(DemandLetter.employer),
        assignees=await distinct(DemandLetter.assign_to),
        statuses=await distinct(DemandLetter.progress_status),
        ad_assignees=await distinct(DemandLetter.ad_assigned_to),
    )


async def get_detail(db: AsyncSession, demand_id: int) -> DemandDetail:
    row = (await db.execute(_base_query().where(DemandLetter.id == demand_id))).one_or_none()
    if row is None:
        raise _not_found()
    trades = (
        await db.execute(
            select(DemandTrade)
            .where(DemandTrade.demand_id == demand_id)
            .order_by(DemandTrade.sort_order)
        )
    ).scalars()
    return DemandDetail(
        **_to_summary(*row), trades=[TradeOut.model_validate(t) for t in trades]
    )


# ---------- creating ----------


async def create_draft(
    db: AsyncSession, storage: Storage, *, user_id: int, idempotency_key: str | None
) -> tuple[int, bool]:
    """Reserve the lowest free demand ID and create an empty draft.

    Returns (demand_id, created). With an Idempotency-Key that was already used,
    the existing draft is returned and created is False.
    """
    if idempotency_key is not None:
        idempotency_key = idempotency_key.strip()
        if not 8 <= len(idempotency_key) <= 200:
            raise ProblemError(
                400, "idempotency-key-invalid", "Invalid Idempotency-Key header",
                "Send a unique value of 8 to 200 characters, e.g. a UUID.",
            )
        # If another request with the same key is in flight, this insert waits for it.
        claimed = (
            await db.execute(
                pg_insert(IdempotencyKey)
                .values(user_id=user_id, key=idempotency_key)
                .on_conflict_do_nothing(index_elements=["user_id", "key"])
                .returning(IdempotencyKey.key)
            )
        ).scalar_one_or_none()
        if claimed is None:
            await db.rollback()
            existing = await db.get(IdempotencyKey, (user_id, idempotency_key))
            if existing is None or existing.demand_id is None:
                raise ProblemError(
                    409, "idempotency-key-reused", "This request was already handled",
                    "The draft it created no longer exists. Click \"Add Demand Letter\" again.",
                )
            return existing.demand_id, False

    number = await allocate_id_number(db)
    demand_id = (
        await db.execute(
            insert(DemandLetter)
            .values(id_number=number, created_by=user_id)
            .returning(DemandLetter.id)
        )
    ).scalar_one()
    if idempotency_key is not None:
        await db.execute(
            update(IdempotencyKey)
            .where(IdempotencyKey.user_id == user_id, IdempotencyKey.key == idempotency_key)
            .values(demand_id=demand_id)
        )
    code = (
        await db.execute(select(DemandLetter.demand_code).where(DemandLetter.id == demand_id))
    ).scalar_one()
    # Create the folder before committing: if storage is broken, no ID is reserved.
    try:
        await storage.ensure_folder(demand_folder(code))
    except StorageError:
        await db.rollback()
        raise ProblemError(
            503, "storage-unavailable", "File storage is unavailable",
            "The draft was not created. Try again in a moment.",
        )
    await db.commit()
    return demand_id, True


# ---------- updating ----------


async def _lock_for_change(db: AsyncSession, demand_id: int, if_match: str | None) -> DemandLetter:
    if not if_match:
        raise ProblemError(
            428, "precondition-required", "If-Match header required",
            "Reload the letter before saving changes.",
        )
    demand = (
        await db.execute(
            select(DemandLetter).where(DemandLetter.id == demand_id).with_for_update()
        )
    ).scalar_one_or_none()
    if demand is None:
        raise _not_found()
    if if_match.strip() not in ("*", etag_of(demand)):
        raise ProblemError(
            412, "demand-changed", "This letter was changed by someone else",
            "Reload to see the latest version, then make your change again.",
        )
    return demand


def _bump(demand: DemandLetter) -> None:
    demand.row_version += 1
    demand.updated_at = datetime.now(UTC)


async def update_fields(
    db: AsyncSession, demand_id: int, if_match: str | None, changes: DemandUpdate
) -> DemandDetail:
    demand = await _lock_for_change(db, demand_id, if_match)
    manual = set(demand.manual_fields or [])
    for field, value in changes.model_dump(exclude_unset=True).items():
        if isinstance(value, str):
            value = value or None  # "" clears the field
        if getattr(demand, field) != value and field in ("country", "employer", "vacancy"):
            manual.add(field)  # the AI won't overwrite a field a person changed
        setattr(demand, field, value)
    demand.manual_fields = sorted(manual)
    _bump(demand)
    await db.commit()
    return await get_detail(db, demand_id)


async def replace_trades(
    db: AsyncSession, demand_id: int, if_match: str | None, trades: list[TradeIn]
) -> DemandDetail:
    if len(trades) > 500:
        raise ProblemError(422, "too-many-trades", "Too many trade rows", "The limit is 500.")
    demand = await _lock_for_change(db, demand_id, if_match)
    await db.execute(delete(DemandTrade).where(DemandTrade.demand_id == demand_id))
    for position, trade in enumerate(trades):
        db.add(
            DemandTrade(
                demand_id=demand_id,
                project=trade.project,
                trade=trade.trade,
                quantity=trade.quantity,
                sort_order=position,
            )
        )
    demand.manual_fields = sorted(set(demand.manual_fields or []) | {"trades"})
    _bump(demand)
    await db.commit()
    return await get_detail(db, demand_id)


# ---------- deleting ----------


async def delete_draft(db: AsyncSession, storage: Storage, demand_id: int) -> None:
    """Delete a draft: its folder first, then the database row (which frees the ID).

    - If removing the folder fails, nothing else happens: the draft and its ID stay.
    - If the folder is removed but the database delete then fails, the draft row stays
      with no files; deleting again finishes the job (a missing folder counts as removed).
    """
    demand = (
        await db.execute(
            select(DemandLetter).where(DemandLetter.id == demand_id).with_for_update()
        )
    ).scalar_one_or_none()
    if demand is None:
        raise _not_found()
    if demand.lifecycle == "approved":
        raise ProblemError(
            409, "approved-letter-not-deletable", "Approved letters cannot be deleted",
            "Only drafts (yet to be approved) can be deleted.",
        )
    from app.modules.jobs.models import GenerationJob

    busy = (await db.execute(
        select(GenerationJob.id).where(
            GenerationJob.demand_id == demand_id, GenerationJob.state.in_(("queued", "running"))
        )
    )).first()
    if busy:
        await db.rollback()
        raise ProblemError(
            409, "job-in-progress", "The AI is still working on this draft",
            "Wait until the current reply is ready, then delete.",
        )

    try:
        await storage.delete_folder(demand_folder(demand.demand_code))
    except StorageError:
        await db.rollback()
        raise ProblemError(
            503, "storage-delete-failed", "Could not delete the draft's files",
            "Nothing was deleted and the demand ID is still reserved. Try again.",
        )

    try:
        await db.delete(demand)
        await db.commit()
    except DBAPIError:
        await db.rollback()
        raise ProblemError(
            500, "draft-delete-incomplete", "The draft's files were removed but the draft was not",
            "Delete it again to finish.",
        )
