from fastapi import APIRouter, Response, status

from app.deps import AppSettings, CurrentUser, DbSession
from app.modules.auth import service
from app.modules.auth.schemas import LoginRequest, LoginResponse
from app.modules.users.schemas import UserOut
from app.security import clear_session_cookie, set_session_cookie

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest, response: Response, db: DbSession, settings: AppSettings):
    user, token, csrf = await service.login(db, settings, body.username, body.password)
    set_session_cookie(response, settings, token)
    return LoginResponse(user=UserOut.model_validate(user), csrf_token=csrf)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(current: CurrentUser, db: DbSession, settings: AppSettings):
    await service.logout(db, current.session)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_session_cookie(response, settings)
    return response
