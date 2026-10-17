from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.config import Settings
from app.errors import ProblemError
from app.modules.auth.models import LoginSession
from app.modules.users.models import NameChangeRequest, User
from app.security import hash_password, verify_password


def check_password_strength(settings: Settings, password: str, field: str = "password") -> None:
    if len(password) < settings.password_min_length:
        raise ProblemError(
            422,
            "validation-error",
            "Some fields are invalid",
            "Fix the listed fields and try again.",
            errors=[
                {
                    "field": field,
                    "message": f"Must be at least {settings.password_min_length} characters.",
                }
            ],
        )


# ---------- name-change requests (user side) ----------


async def get_pending_request(db: AsyncSession, user_id: int) -> NameChangeRequest | None:
    return (
        await db.execute(
            select(NameChangeRequest).where(
                NameChangeRequest.user_id == user_id, NameChangeRequest.status == "pending"
            )
        )
    ).scalar_one_or_none()


async def list_own_requests(db: AsyncSession, user_id: int) -> list[NameChangeRequest]:
    return list(
        (
            await db.execute(
                select(NameChangeRequest)
                .where(NameChangeRequest.user_id == user_id)
                .order_by(NameChangeRequest.created_at.desc(), NameChangeRequest.id.desc())
            )
        ).scalars()
    )


async def create_name_change_request(
    db: AsyncSession, user: User, requested_name: str
) -> NameChangeRequest:
    if requested_name == user.display_name:
        raise ProblemError(
            422, "name-unchanged", "That is already your name",
            "Enter a different name to request a change.",
        )
    if await get_pending_request(db, user.id):
        raise ProblemError(
            409, "name-change-already-pending", "A name change is already waiting for approval",
            "Wait for the admin to approve or reject your current request.",
        )
    request = NameChangeRequest(user_id=user.id, requested_name=requested_name)
    db.add(request)
    try:
        await db.commit()
    except IntegrityError:
        # Two requests submitted at the same moment: the unique index stops the second.
        await db.rollback()
        raise ProblemError(
            409, "name-change-already-pending", "A name change is already waiting for approval"
        )
    await db.refresh(request)
    return request


# ---------- users (admin side) ----------


async def list_users(db: AsyncSession) -> list[User]:
    return list((await db.execute(select(User).order_by(func.lower(User.display_name)))).scalars())


async def create_user(
    db: AsyncSession,
    settings: Settings,
    *,
    username: str,
    display_name: str,
    role: str,
    initial_password: str,
) -> User:
    check_password_strength(settings, initial_password, "initial_password")
    exists = (
        await db.execute(select(User.id).where(func.lower(User.username) == username.lower()))
    ).scalar_one_or_none()
    if exists:
        raise ProblemError(
            409, "username-taken", "Username already in use",
            f'Choose a different username than "{username}".',
        )
    user = User(
        username=username,
        display_name=display_name,
        role=role,
        password_hash=hash_password(initial_password),
    )
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise ProblemError(409, "username-taken", "Username already in use")
    await db.refresh(user)
    return user


async def get_user_or_404(db: AsyncSession, user_id: int) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise ProblemError(404, "user-not-found", "User not found")
    return user


async def update_user(
    db: AsyncSession,
    *,
    acting_user_id: int,
    user_id: int,
    role: str | None,
    is_active: bool | None,
) -> User:
    user = await get_user_or_404(db, user_id)
    if is_active is False and user.id == acting_user_id:
        raise ProblemError(
            409, "cannot-deactivate-self", "You cannot deactivate your own account",
            "Ask another team member with the admin password to do it.",
        )
    if role is not None:
        user.role = role
    if is_active is not None and is_active != user.is_active:
        user.is_active = is_active
        if not is_active:
            # Log the user out everywhere, immediately.
            await db.execute(delete(LoginSession).where(LoginSession.user_id == user.id))
    await db.commit()
    await db.refresh(user)
    return user


# ---------- name-change requests (admin side) ----------


async def list_requests_with_users(db: AsyncSession, status: str | None) -> list[dict]:
    reviewer = aliased(User)
    query = (
        select(NameChangeRequest, User, reviewer.display_name)
        .join(User, User.id == NameChangeRequest.user_id)
        .outerjoin(reviewer, reviewer.id == NameChangeRequest.reviewed_by)
        .order_by(NameChangeRequest.created_at.desc(), NameChangeRequest.id.desc())
    )
    if status:
        query = query.where(NameChangeRequest.status == status)
    rows = (await db.execute(query)).all()
    return [
        {
            "id": req.id,
            "user_id": req.user_id,
            "requested_name": req.requested_name,
            "status": req.status,
            "created_at": req.created_at,
            "reviewed_at": req.reviewed_at,
            "reviewed_by": req.reviewed_by,
            "username": user.username,
            "current_name": user.display_name,
            "reviewed_by_name": reviewer_name,
        }
        for req, user, reviewer_name in rows
    ]


async def review_request(
    db: AsyncSession, *, request_id: int, reviewer_id: int, approve: bool
) -> NameChangeRequest:
    request = (
        await db.execute(
            select(NameChangeRequest).where(NameChangeRequest.id == request_id).with_for_update()
        )
    ).scalar_one_or_none()
    if request is None:
        raise ProblemError(404, "name-change-request-not-found", "Request not found")
    if request.status != "pending":
        raise ProblemError(
            409, "name-change-not-pending", "This request was already reviewed",
            f"It is already {request.status}.",
        )
    request.status = "approved" if approve else "rejected"
    request.reviewed_by = reviewer_id
    request.reviewed_at = datetime.now(UTC)
    if approve:
        user = await db.get(User, request.user_id)
        user.display_name = request.requested_name
    await db.commit()
    await db.refresh(request)
    return request


# ---------- passwords ----------


async def change_own_password(
    db: AsyncSession,
    settings: Settings,
    *,
    user: User,
    current_session_id: int,
    current_password: str,
    new_password: str,
) -> None:
    """User changes their own password; every other login session is ended."""
    if not verify_password(user.password_hash, current_password):
        raise ProblemError(
            401, "current-password-wrong", "Current password is wrong",
            "Enter the password you use to log in now.",
        )
    check_password_strength(settings, new_password, "new_password")
    if new_password == current_password:
        raise ProblemError(
            422, "validation-error", "Some fields are invalid",
            "Fix the listed fields and try again.",
            errors=[{"field": "new_password", "message": "Must be different from the current password."}],
        )
    user.password_hash = hash_password(new_password)
    await db.execute(
        delete(LoginSession).where(
            LoginSession.user_id == user.id, LoginSession.id != current_session_id
        )
    )
    await db.commit()


async def admin_reset_password(
    db: AsyncSession, settings: Settings, *, user_id: int, new_password: str
) -> User:
    """Admin sets a new password for a user (e.g. forgotten password).

    The user's existing sessions are ended, so only the new password works from now on.
    """
    user = await get_user_or_404(db, user_id)
    check_password_strength(settings, new_password, "new_password")
    user.password_hash = hash_password(new_password)
    await db.execute(delete(LoginSession).where(LoginSession.user_id == user.id))
    await db.commit()
    await db.refresh(user)
    return user
