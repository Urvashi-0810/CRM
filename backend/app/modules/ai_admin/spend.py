"""Monthly AI spend cap and usage report. Months are calendar months in UTC (as decided),
matching the AI provider's own billing month (Claude's caps reset at 00:00 UTC on the 1st)."""

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ProblemError
from app.modules.admin.models import AppSettings
from app.modules.ai_admin.models import LlmCall


def month_bounds(month: date | None = None) -> tuple[datetime, datetime]:
    today = datetime.now(UTC)
    first = (month or today.date()).replace(day=1)
    start = datetime(first.year, first.month, 1, tzinfo=UTC)
    end = datetime(first.year + (first.month == 12), first.month % 12 + 1, 1, tzinfo=UTC)
    return start, end


async def month_spend(db: AsyncSession, month: date | None = None) -> Decimal:
    start, end = month_bounds(month)
    total = (await db.execute(
        select(func.coalesce(func.sum(LlmCall.cost_usd), 0))
        .where(LlmCall.created_at >= start, LlmCall.created_at < end)
    )).scalar_one()
    return Decimal(total)


async def cap_settings(db: AsyncSession) -> tuple[bool, Decimal | None]:
    row = (await db.execute(select(AppSettings).where(AppSettings.id.is_(True)))).scalar_one_or_none()
    if row is None:
        return False, None
    return row.spend_cap_enabled, row.spend_cap_usd


def _reset_text() -> str:
    _, end = month_bounds()
    return f"{end:%d %B %Y}, 00:00 UTC (05:30 India time)"


async def ensure_within_cap(db: AsyncSession) -> None:
    """Raise 429 if the monthly cap is on and reached."""
    enabled, cap = await cap_settings(db)
    if not enabled or cap is None:
        return
    spent = await month_spend(db)
    if spent >= cap:
        raise ProblemError(
            429, "spend-cap-reached", "Monthly AI budget reached",
            f"This month's AI spend (${spent:.2f}) has reached the limit of ${cap:.2f} set by the admin. "
            f"It resets on {_reset_text()}, or the admin can raise the limit.",
            headers={"Retry-After": str(max(1, int((month_bounds()[1] - datetime.now(UTC)).total_seconds())))},
        )


async def usage_report(db: AsyncSession, month: date | None = None) -> dict:
    start, end = month_bounds(month)
    in_month = (LlmCall.created_at >= start, LlmCall.created_at < end)
    by_model = (await db.execute(
        select(
            LlmCall.provider, LlmCall.model,
            func.count(), func.count().filter(LlmCall.outcome == "ok"),
            func.coalesce(func.sum(LlmCall.input_tokens), 0), func.coalesce(func.sum(LlmCall.output_tokens), 0),
            func.coalesce(func.sum(LlmCall.cache_read_tokens), 0), func.coalesce(func.sum(LlmCall.cost_usd), 0),
            func.count().filter(LlmCall.cost_usd.is_(None) & (LlmCall.outcome == "ok")),
        ).where(*in_month).group_by(LlmCall.provider, LlmCall.model).order_by(LlmCall.provider, LlmCall.model)
    )).all()
    day = func.date_trunc("day", LlmCall.created_at.op("AT TIME ZONE")("UTC"))
    by_day = (await db.execute(
        select(day, func.count(), func.coalesce(func.sum(LlmCall.cost_usd), 0))
        .where(*in_month).group_by(day).order_by(day)
    )).all()
    total = sum((Decimal(r[7]) for r in by_model), Decimal(0))
    enabled, cap = await cap_settings(db)
    return {
        "month": f"{start:%Y-%m}",
        "period": {"from": start, "to": end},
        "total_cost_usd": f"{total:.4f}",
        "calls": sum(r[2] for r in by_model),
        "successful_calls": sum(r[3] for r in by_model),
        "unpriced_calls": sum(r[8] for r in by_model),
        "cap": {"enabled": enabled, "monthly_usd": f"{cap:.2f}" if cap is not None else None,
                "used_fraction": float(total / cap) if (cap and cap > 0) else None},
        "by_model": [
            {"provider": r[0], "model": r[1], "calls": r[2], "successful_calls": r[3],
             "input_tokens": r[4], "output_tokens": r[5], "cache_read_tokens": r[6],
             "cost_usd": f"{Decimal(r[7]):.4f}", "unpriced_calls": r[8]}
            for r in by_model
        ],
        "by_day": [{"day": f"{r[0]:%Y-%m-%d}", "calls": r[1], "cost_usd": f"{Decimal(r[2]):.4f}"} for r in by_day],
    }
