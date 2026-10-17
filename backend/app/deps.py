"""Shared FastAPI dependencies: current login, CSRF check and admin unlock."""

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_db
from app.errors import ProblemError
from app.modules.auth.models import LoginSession
from app.modules.users.models import User
from app.security import hash_token, session_cookie_name

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

DbSession = Annotated[AsyncSession, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]


@dataclass
class CurrentLogin:
    session: LoginSession
    user: User

    @property
    def admin_active(self) -> bool:
        until = self.session.admin_until
        return until is not None and until > datetime.now(UTC)


def _not_logged_in() -> ProblemError:
    return ProblemError(401, "not-authenticated", "Not logged in", "Please log in again.")


async def get_current_login(request: Request, db: DbSession, settings: AppSettings) -> CurrentLogin:
    token = request.cookies.get(session_cookie_name(settings))
    if not token:
        raise _not_logged_in()

    now = datetime.now(UTC)
    row = (
        await db.execute(
            select(LoginSession, User)
            .join(User, User.id == LoginSession.user_id)
            .where(LoginSession.token_hash == hash_token(token))
        )
    ).one_or_none()
    if row is None:
        raise _not_logged_in()

    login_session, user = row
    if login_session.expires_at <= now or not user.is_active:
        await db.delete(login_session)
        await db.commit()
        raise _not_logged_in()

    # CSRF protection for anything that changes data.
    if request.method not in SAFE_METHODS:
        sent = request.headers.get("X-CSRF-Token", "")
        if not secrets.compare_digest(sent, login_session.csrf_token):
            raise ProblemError(
                403,
                "csrf-token-invalid",
                "Security token missing or invalid",
                "Reload the page and try again.",
            )

    return CurrentLogin(session=login_session, user=user)


CurrentUser = Annotated[CurrentLogin, Depends(get_current_login)]


async def require_admin(current: CurrentUser) -> CurrentLogin:
    if not current.admin_active:
        raise ProblemError(
            403,
            "admin-session-required",
            "Admin access required",
            "Enter the admin password to open the admin page.",
        )
    return current


AdminUser = Annotated[CurrentLogin, Depends(require_admin)]
