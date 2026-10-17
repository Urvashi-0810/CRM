from typing import Literal

from fastapi import APIRouter, Response, status

from app.deps import AdminUser, AppSettings, CurrentUser, DbSession
from app.modules.admin import service
from app.modules.admin.schemas import (
    AdminPasswordChange,
    AdminSessionStatus,
    AdminUnlock,
    PasswordReset,
    UserCreate,
    UserUpdate,
)
from app.modules.users import service as users_service
from app.modules.users.schemas import (
    ItemList,
    NameChangeRequestOut,
    NameChangeRequestWithUser,
    UserOut,
)

router = APIRouter(prefix="/admin", tags=["admin"])


# ---------- admin unlock (the second password) ----------


@router.get("/session", response_model=AdminSessionStatus)
async def admin_session_status(current: CurrentUser, db: DbSession):
    return AdminSessionStatus(
        active=current.admin_active,
        expires_at=current.session.admin_until if current.admin_active else None,
        password_configured=await service.admin_password_configured(db),
    )


@router.post("/session", status_code=status.HTTP_204_NO_CONTENT)
async def unlock_admin(body: AdminUnlock, current: CurrentUser, db: DbSession, settings: AppSettings):
    await service.unlock_admin(db, settings, current.session, current.user, body.admin_password)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/session", status_code=status.HTTP_204_NO_CONTENT)
async def lock_admin(current: CurrentUser, db: DbSession):
    await service.lock_admin(db, current.session)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_admin_password(
    body: AdminPasswordChange, admin: AdminUser, db: DbSession, settings: AppSettings
):
    await service.change_admin_password(
        db, settings, user_id=admin.user.id, current=body.current_password, new=body.new_password
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------- users ----------


@router.get("/users", response_model=ItemList[UserOut])
async def list_users(_: AdminUser, db: DbSession):
    users = await users_service.list_users(db)
    return ItemList[UserOut](items=[UserOut.model_validate(u) for u in users])


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: UserCreate, _: AdminUser, db: DbSession, settings: AppSettings, response: Response
):
    user = await users_service.create_user(
        db,
        settings,
        username=body.username,
        display_name=body.display_name,
        role=body.role,
        initial_password=body.initial_password,
    )
    response.headers["Location"] = f"/api/v1/admin/users/{user.id}"
    return UserOut.model_validate(user)


@router.patch("/users/{user_id}", response_model=UserOut)
async def update_user(user_id: int, body: UserUpdate, admin: AdminUser, db: DbSession):
    user = await users_service.update_user(
        db,
        acting_user_id=admin.user.id,
        user_id=user_id,
        role=body.role,
        is_active=body.is_active,
    )
    return UserOut.model_validate(user)


@router.put("/users/{user_id}/password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_user_password(
    user_id: int, body: PasswordReset, _: AdminUser, db: DbSession, settings: AppSettings
):
    """Set a new password for a user who forgot theirs. Logs that user out everywhere."""
    await users_service.admin_reset_password(
        db, settings, user_id=user_id, new_password=body.new_password
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------- name-change requests ----------


@router.get("/name-change-requests", response_model=ItemList[NameChangeRequestWithUser])
async def list_name_change_requests(
    _: AdminUser,
    db: DbSession,
    status: Literal["pending", "approved", "rejected"] | None = None,
):
    items = await users_service.list_requests_with_users(db, status)
    return ItemList[NameChangeRequestWithUser](
        items=[NameChangeRequestWithUser(**i) for i in items]
    )


@router.post("/name-change-requests/{request_id}/approve", response_model=NameChangeRequestOut)
async def approve_name_change(request_id: int, admin: AdminUser, db: DbSession):
    request = await users_service.review_request(
        db, request_id=request_id, reviewer_id=admin.user.id, approve=True
    )
    return NameChangeRequestOut.model_validate(request)


@router.post("/name-change-requests/{request_id}/reject", response_model=NameChangeRequestOut)
async def reject_name_change(request_id: int, admin: AdminUser, db: DbSession):
    request = await users_service.review_request(
        db, request_id=request_id, reviewer_id=admin.user.id, approve=False
    )
    return NameChangeRequestOut.model_validate(request)
