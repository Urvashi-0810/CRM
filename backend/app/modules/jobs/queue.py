"""The job queue: PostgreSQL rows claimed with FOR UPDATE SKIP LOCKED, held with a lease."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

MAX_JOB_ATTEMPTS = 3

_CLAIM = text(
    """
    UPDATE generation_jobs
    SET state = 'running',
        attempts = attempts + 1,
        lease_until = now() + make_interval(secs => :lease),
        started_at = coalesce(started_at, now())
    WHERE id = (
        SELECT id FROM generation_jobs
        WHERE state = 'queued' OR (state = 'running' AND lease_until < now())
        ORDER BY created_at
        FOR UPDATE SKIP LOCKED
        LIMIT 1
    )
    RETURNING id, attempts
    """
)


async def claim_next(db: AsyncSession, lease_seconds: int) -> int | None:
    """Claim the oldest waiting job (or one whose worker died). Returns its id."""
    row = (await db.execute(_CLAIM, {"lease": lease_seconds})).first()
    if row is None:
        await db.commit()
        return None
    job_id, attempts = row
    if attempts > MAX_JOB_ATTEMPTS:
        # Crashed repeatedly: give up so it doesn't loop forever.
        await db.execute(
            text(
                "UPDATE generation_jobs SET state = 'failed', lease_until = NULL, finished_at = now(), "
                "error = 'Stopped after repeated failures.' WHERE id = :id"
            ),
            {"id": job_id},
        )
        await db.execute(
            text(
                "INSERT INTO chat_messages (demand_id, sender, kind, body, job_id) "
                "SELECT demand_id, 'assistant', 'error', "
                "'Something went wrong while preparing the reply. Please send your message again.', id "
                "FROM generation_jobs WHERE id = :id"
            ),
            {"id": job_id},
        )
        await db.commit()
        return None
    await db.commit()
    return job_id


async def extend_lease(db: AsyncSession, job_id: int, lease_seconds: int) -> None:
    await db.execute(
        text("UPDATE generation_jobs SET lease_until = :until WHERE id = :id AND state = 'running'"),
        {"until": datetime.now(UTC) + timedelta(seconds=lease_seconds), "id": job_id},
    )
    await db.commit()
