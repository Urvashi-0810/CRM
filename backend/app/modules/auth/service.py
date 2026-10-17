from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.errors import ProblemError
from app.modules.auth.models import LoginSession
from app.modules.users.models import User
from app.security import (
    hash_password,
    hash_token,
    new_token,
    password_needs_rehash,
    verify_password,
)


async def login(
    db: AsyncSession, settings: Settings, username: str, password: str
) -> tuple[User, str, str]:
    """Check credentials and create a session. Returns (user, session_token, csrf_token)."""
    user = (
        await db.execute(select(User).where(func.lower(User.username) == username.strip().lower()))
    ).scalar_one_or_none()

    # Always run a hash check (even for unknown users) so timing reveals nothing.
    ok = verify_password(user.password_hash if user else None, password)
    if not ok or user is None or not user.is_active:
        raise ProblemError(
            401, "invalid-credentials", "Wrong username or password",
            "Check your username and password. Ask your admin if your account was deactivated.",
        )

    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)

    now = datetime.now(UTC)
    token, csrf = new_token(), new_token()
    db.add(
        LoginSession(
            token_hash=hash_token(token),
            user_id=user.id,
            csrf_token=csrf,
            expires_at=now + timedelta(hours=settings.session_ttl_hours),
        )
    )
    user.last_login_at = now
    # Housekeeping: drop this user's expired sessions.
    await db.execute(
        delete(LoginSession).where(LoginSession.user_id == user.id, LoginSession.expires_at <= now)
    )
    await db.commit()
    return user, token, csrf


async def logout(db: AsyncSession, session: LoginSession) -> None:
    await db.delete(session)
    await db.commit()
