"""Dashboard numbers: approved letters only, 1 approved letter = 1 order.

The approval date decides the period, counted in India time (the date printed on the letter).
Employers and countries are grouped ignoring case and surrounding spaces, so
"Mosanada " and "mosanada" are one client. Letters with no employer/country (or only the
letter's "[[MISSING: …]]" placeholder) form a "Not filled" row, always listed last; it isn't counted as a client.
"""

from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy import case, func, literal, select
from sqlalchemy.dialects.postgresql import aggregate_order_by
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ProblemError
from app.modules.demands.models import DemandLetter, DemandTrade
from app.modules.demands.schemas import AD_STATUSES
from app.modules.users.models import User

IST = ZoneInfo("Asia/Kolkata")
Period = Literal["this_month", "last_month", "this_year", "custom"]
NOT_FILLED = "Not filled"


@dataclass
class Range:
    period: str
    start: date  # inclusive
    end: date  # inclusive
    label: str


def resolve_period(period: Period, date_from: date | None, date_to: date | None, *, today: date | None = None) -> Range:
    today = today or datetime.now(IST).date()
    if period == "this_month":
        return Range(period, today.replace(day=1), today, today.strftime("%B %Y"))
    if period == "last_month":
        last = today.replace(day=1) - timedelta(days=1)
        return Range(period, last.replace(day=1), last.replace(day=monthrange(last.year, last.month)[1]),
                     last.strftime("%B %Y"))
    if period == "this_year":
        return Range(period, date(today.year, 1, 1), today, str(today.year))
    if date_from is None or date_to is None:
        raise ProblemError(422, "validation-error", "Choose both dates", "A custom range needs a start and an end date.",
                           errors=[{"field": "date_from" if date_from is None else "date_to", "message": "Required."}])
    if date_from > date_to:
        raise ProblemError(422, "validation-error", "The end date is before the start date",
                           errors=[{"field": "date_to", "message": "Must be on or after the start date."}])
    return Range(period, date_from, date_to, f"{date_from:%d %b %Y} – {date_to:%d %b %Y}")


def _shift_months(d: date, months: int) -> date:
    y, m = divmod(d.year * 12 + d.month - 1 + months, 12)
    return date(y, m + 1, min(d.day, monthrange(y, m + 1)[1]))


def previous_range(r: Range) -> Range:
    """The period to compare with: the same stretch of the previous month / year, the month
    before, or (custom) the same number of days just before."""
    if r.period == "this_month":
        start = _shift_months(r.start, -1)
        end = min(_shift_months(r.end, -1), start.replace(day=monthrange(start.year, start.month)[1]))
        label = f"{start:%b} {start.day}" if start == end else f"{start.day}–{end.day} {start:%b}"
    elif r.period == "last_month":
        start = _shift_months(r.start, -1)
        end = start.replace(day=monthrange(start.year, start.month)[1])
        label = f"{start:%B}"
    elif r.period == "this_year":
        start, end = _shift_months(r.start, -12), _shift_months(r.end, -12)
        label = f"same time {start.year}"
    else:
        end = r.start - timedelta(days=1)
        start = end - (r.end - r.start)
        days = (end - start).days + 1
        label = "the day before" if days == 1 else f"previous {days} days"
    return Range("previous", start, end, label)


def _in_range(r: Range):
    start = datetime.combine(r.start, time.min, tzinfo=IST)
    end = datetime.combine(r.end + timedelta(days=1), time.min, tzinfo=IST)
    return (DemandLetter.lifecycle == "approved", DemandLetter.approved_at >= start, DemandLetter.approved_at < end)


def _newest_spelling(cleaned):
    return func.array_agg(aggregate_order_by(cleaned, DemandLetter.approved_at.desc()))[1]


def _cleaned(column):
    """Trimmed text; blank or the letter's "[[MISSING: …]]" placeholder count as not filled."""
    trimmed = func.btrim(column)
    return case((trimmed.ilike("[[missing%"), None), else_=func.nullif(trimmed, ""))


def _group_key(column):
    """Lower-cased cleaned text ("" = not filled), and the cleaned text itself."""
    cleaned = _cleaned(column)
    return func.coalesce(func.lower(cleaned), literal("")), cleaned


async def build(db: AsyncSession, r: Range) -> dict:
    where = _in_range(r)
    vacancies = func.coalesce(func.sum(func.coalesce(DemandLetter.vacancy, 0)), 0)

    client_key, client_name = _group_key(DemandLetter.employer)

    # Shown name: the spelling on the newest order.
    by_client_rows = (await db.execute(
        select(client_key, _newest_spelling(client_name), func.count(), vacancies).where(*where).group_by(client_key)
    )).all()
    names = {key: (name or NOT_FILLED) for key, name, *_ in by_client_rows}
    by_client = sorted(
        ({"employer": names[key], "orders": n, "vacancies": int(v)} for key, _, n, v in by_client_rows),
        key=lambda c: (c["employer"] == NOT_FILLED, -c["orders"], -c["vacancies"], c["employer"].lower()),
    )

    month = func.to_char(func.timezone("Asia/Kolkata", DemandLetter.approved_at), "YYYY-MM")
    monthly = (await db.execute(
        select(client_key, month, func.count()).where(*where, _cleaned(DemandLetter.employer).is_not(None))
        .group_by(client_key, month).having(func.count() >= 2)
    )).all()
    repeat: dict[str, dict] = {}
    for key, ym, n in monthly:
        entry = repeat.setdefault(key, {"employer": names[key], "repeat_months": 0, "orders_in_repeat_months": 0, "months": []})
        entry["repeat_months"] += 1
        entry["orders_in_repeat_months"] += n
        entry["months"].append({"month": ym, "orders": n})
    for entry in repeat.values():
        entry["months"].sort(key=lambda m: m["month"])
    repeat_clients = sorted(repeat.values(), key=lambda c: (-c["repeat_months"], -c["orders_in_repeat_months"], c["employer"].lower()))

    country_key, country_name = _group_key(DemandLetter.country)
    by_country = sorted(
        ({"country": name or NOT_FILLED, "orders": n, "vacancies": int(v)} for _, name, n, v in (await db.execute(
            select(country_key, _newest_spelling(country_name), func.count(), vacancies).where(*where).group_by(country_key)
        )).all()),
        key=lambda c: (c["country"] == NOT_FILLED, -c["orders"], -c["vacancies"], c["country"].lower()),
    )

    status_counts = dict((await db.execute(
        select(DemandLetter.ad_status, func.count()).where(*where).group_by(DemandLetter.ad_status)
    )).all())
    ad_status = [{"status": s, "orders": status_counts.get(s, 0)} for s in AD_STATUSES]

    prev = previous_range(r)
    return {
        "period": {"period": r.period, "date_from": r.start, "date_to": r.end, "label": r.label},
        "previous": {"date_from": prev.start, "date_to": prev.end, "label": prev.label},
        "totals": await _totals(db, r),
        "previous_totals": await _totals(db, prev),
        "trend": await _trend(db, r),
        "pipeline": await _pipeline(db),
        "positions": await _positions(db, r),
        "team": await _team(db, r),
        "by_client": by_client,
        "repeat_clients": repeat_clients,
        "by_country": by_country,
        "ad_status": ad_status,
    }


def _vacancy_sum():
    return func.coalesce(func.sum(func.coalesce(DemandLetter.vacancy, 0)), 0)


async def _totals(db: AsyncSession, r: Range) -> dict:
    where = _in_range(r)
    client = func.lower(_cleaned(DemandLetter.employer))
    orders, vacancies, clients = (await db.execute(
        select(func.count(), _vacancy_sum(), func.count(func.distinct(client))).where(*where)
    )).one()
    # New client = their first approved order ever falls in this period.
    first = (
        select(client.label("k"), func.min(DemandLetter.approved_at).label("first"))
        .where(DemandLetter.lifecycle == "approved", client.is_not(None)).group_by(client).subquery()
    )
    start = datetime.combine(r.start, time.min, tzinfo=IST)
    end = datetime.combine(r.end + timedelta(days=1), time.min, tzinfo=IST)
    new_clients = (await db.execute(
        select(func.count()).select_from(first).where(first.c.first >= start, first.c.first < end)
    )).scalar_one()
    return {"orders": orders, "vacancies": int(vacancies), "clients": clients, "new_clients": new_clients}


async def _trend(db: AsyncSession, r: Range) -> dict:
    """Orders and vacancies per day (periods up to ~2 months) or per month (longer)."""
    daily = (r.end - r.start).days <= 62
    bucket = func.to_char(func.timezone("Asia/Kolkata", DemandLetter.approved_at), "YYYY-MM-DD" if daily else "YYYY-MM")
    found = {b: (n, int(v)) for b, n, v in (await db.execute(
        select(bucket, func.count(), _vacancy_sum()).where(*_in_range(r)).group_by(bucket)
    )).all()}
    points, day = [], r.start
    while day <= r.end:
        key = day.isoformat() if daily else day.strftime("%Y-%m")
        if not points or points[-1]["bucket"] != key:
            n, v = found.get(key, (0, 0))
            points.append({"bucket": key, "orders": n, "vacancies": v})
        day += timedelta(days=1)
    return {"unit": "day" if daily else "month", "points": points}


async def _pipeline(db: AsyncSession) -> dict:
    """Right now, whatever the period."""
    counts = dict((await db.execute(select(DemandLetter.lifecycle, func.count()).group_by(DemandLetter.lifecycle))).all())
    oldest = (await db.execute(
        select(func.min(DemandLetter.submitted_at)).where(DemandLetter.lifecycle == "pending")
    )).scalar_one()
    return {"drafts": counts.get("draft", 0), "waiting_approval": counts.get("pending", 0),
            "approved_all_time": counts.get("approved", 0), "oldest_waiting_since": oldest}


async def _positions(db: AsyncSession, r: Range, limit: int = 10) -> list[dict]:
    """Most demanded positions: people asked for across the period's orders."""
    trimmed = func.btrim(DemandTrade.trade)
    key = func.lower(trimmed)
    name = func.array_agg(aggregate_order_by(trimmed, DemandLetter.approved_at.desc()))[1]
    people = func.sum(DemandTrade.quantity)
    rows = (await db.execute(
        select(name, people, func.count(func.distinct(DemandTrade.demand_id)))
        .join(DemandLetter, DemandLetter.id == DemandTrade.demand_id)
        .where(*_in_range(r), trimmed != "")
        .group_by(key).order_by(people.desc(), key).limit(limit)
    )).all()
    return [{"position": n, "people": int(q), "orders": o} for n, q, o in rows]


async def _team(db: AsyncSession, r: Range) -> list[dict]:
    """Approved letters per person who created them."""
    rows = (await db.execute(
        select(User.display_name, func.count(), _vacancy_sum())
        .join(User, User.id == DemandLetter.created_by).where(*_in_range(r))
        .group_by(User.id, User.display_name).order_by(func.count().desc(), User.display_name)
    )).all()
    return [{"name": n, "orders": o, "vacancies": int(v)} for n, o, v in rows]
