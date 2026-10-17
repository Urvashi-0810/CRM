from fastapi import APIRouter, Response, status

from app.deps import AppSettings, CurrentUser, DbSession
from app.modules.users import service
from app.modules.users.schemas import (
    ItemList,
    MeOut,
    NameChangeCreate,
    NameChangeRequestOut,
    PasswordChange,
)

router = APIRouter(prefix="/me", tags=["my profile"])


@router.get("", response_model=MeOut)
async def get_me(current: CurrentUser, db: DbSession):
    user = current.user
    pending = await service.get_pending_request(db, user.id)
    return MeOut(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        role=user.role,
        pending_name_change=NameChangeRequestOut.model_validate(pending) if pending else None,
        admin_active=current.admin_active,
        admin_until=current.session.admin_until if current.admin_active else None,
        csrf_token=current.session.csrf_token,
    )


@router.get("/name-change-requests", response_model=ItemList[NameChangeRequestOut])
async def list_my_requests(current: CurrentUser, db: DbSession):
    items = await service.list_own_requests(db, current.user.id)
    return ItemList[NameChangeRequestOut](
        items=[NameChangeRequestOut.model_validate(r) for r in items]
    )


@router.post(
    "/name-change-requests",
    response_model=NameChangeRequestOut,
    status_code=status.HTTP_201_CREATED,
)
async def request_name_change(
    body: NameChangeCreate, current: CurrentUser, db: DbSession, response: Response
):
    request = await service.create_name_change_request(db, current.user, body.requested_name)
    response.headers["Location"] = "/api/v1/me/name-change-requests"
    return NameChangeRequestOut.model_validate(request)


@router.put("/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    body: PasswordChange, current: CurrentUser, db: DbSession, settings: AppSettings
):
    """Change your own password. Your other logged-in browsers are logged out."""
    await service.change_own_password(
        db,
        settings,
        user=current.user,
        current_session_id=current.session.id,
        current_password=body.current_password,
        new_password=body.new_password,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
