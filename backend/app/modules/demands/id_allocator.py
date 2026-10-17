"""Demand ID allocation: always the lowest free number, never a duplicate.

Rules (agreed with the client):
- The ID is reserved when "Add Demand Letter" is clicked.
- Deleting a draft frees its number; the next new letter reuses the lowest free one.
- No two letters can ever hold the same ID.

How:
- A transaction-level advisory lock makes allocations run one at a time, so two
  people clicking at the same moment cannot both pick the same free number.
- The UNIQUE constraint on id_number is the safety net behind the lock.
- The lock is released automatically when the transaction commits or rolls back.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ProblemError
from app.modules.demands.models import MAX_ID_NUMBER

# Any fixed number works; it just has to be the same everywhere we allocate.
ALLOCATOR_LOCK_KEY = 7_420_001

_LOWEST_FREE_SQL = text(
    """
    SELECT CASE
        WHEN NOT EXISTS (SELECT 1 FROM demand_letters WHERE id_number = 1) THEN 1
        ELSE (
            SELECT min(d.id_number) + 1
            FROM demand_letters d
            WHERE NOT EXISTS (
                SELECT 1 FROM demand_letters n WHERE n.id_number = d.id_number + 1
            )
        )
    END
    """
)


async def allocate_id_number(db: AsyncSession) -> int:
    """Return the lowest free id_number. Must be called inside the transaction that
    inserts the demand row (the lock is held until that transaction ends)."""
    await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": ALLOCATOR_LOCK_KEY})
    number = (await db.execute(_LOWEST_FREE_SQL)).scalar_one()
    if number > MAX_ID_NUMBER:
        raise ProblemError(
            503, "demand-ids-exhausted", "All demand IDs are in use",
            "Every ID from AA00001 to ZZ99999 is taken. Contact support.",
        )
    return number
