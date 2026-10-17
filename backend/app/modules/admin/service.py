import math
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.errors import ProblemError
from app.modules.admin.models import AppSettings
from app.modules.auth.models import LoginSession
from app.modules.users.models import User
from app.modules.users.service import check_password_strength
from app.security import hash_password, verify_password


async def get_app_settings(db: AsyncSession, *, for_update: bool = False) -> AppSettings | None:
    query = select(AppSettings).where(AppSettings.id.is_(True))
    if for_update:
        query = query.with_for_update()
    return (await db.execute(query)).scalar_one_or_none()


async def admin_password_configured(db: AsyncSession) -> bool:
    row = await get_app_settings(db)
    return bool(row and row.admin_password_hash)


async def unlock_admin(
    db: AsyncSession, settings: Settings, session: LoginSession, user: User, password: str
) -> datetime:
    """Check the admin password and unlock the admin page for this login session."""
    now = datetime.now(UTC)

    if user.admin_locked_until and user.admin_locked_until > now:
        seconds = math.ceil((user.admin_locked_until - now).total_seconds())
        raise ProblemError(
            429, "admin-locked", "Too many wrong admin passwords",
            f"Try again in {math.ceil(seconds / 60)} minute(s).",
            headers={"Retry-After": str(seconds)},
        )

    app_settings = await get_app_settings(db)
    if not app_settings or not app_settings.admin_password_hash:
        raise ProblemError(
            503, "admin-password-not-set", "Admin password has not been set up",
            "Run the bootstrap script on the server to set it.",
        )

    if not verify_password(app_settings.admin_password_hash, password):
        user.admin_failed_attempts += 1
        if user.admin_failed_attempts >= settings.admin_max_failed_attempts:
            user.admin_locked_until = now + timedelta(minutes=settings.admin_lockout_minutes)
            user.admin_failed_attempts = 0
        await db.commit()
        raise ProblemError(401, "admin-password-wrong", "Wrong admin password")

    user.admin_failed_attempts = 0
    user.admin_locked_until = None
    session.admin_until = now + timedelta(minutes=settings.admin_session_minutes)
    await db.commit()
    return session.admin_until


async def lock_admin(db: AsyncSession, session: LoginSession) -> None:
    session.admin_until = None
    await db.commit()


async def change_admin_password(
    db: AsyncSession, settings: Settings, *, user_id: int, current: str, new: str
) -> None:
    app_settings = await get_app_settings(db, for_update=True)
    if not app_settings or not verify_password(app_settings.admin_password_hash, current):
        raise ProblemError(401, "admin-password-wrong", "Current admin password is wrong")
    check_password_strength(settings, new, "new_password")
    app_settings.admin_password_hash = hash_password(new)
    app_settings.updated_by = user_id
    await db.commit()


async def set_admin_password(db: AsyncSession, password: str) -> None:
    """Used by the bootstrap script (no current password needed)."""
    app_settings = await get_app_settings(db, for_update=True)
    if app_settings is None:
        app_settings = AppSettings(id=True)
        db.add(app_settings)
    app_settings.admin_password_hash = hash_password(password)
    await db.commit()
