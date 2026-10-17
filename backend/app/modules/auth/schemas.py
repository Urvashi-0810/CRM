from pydantic import BaseModel

from app.modules.users.schemas import Password, UserOut


class LoginRequest(BaseModel):
    username: str
    password: Password


class LoginResponse(BaseModel):
    user: UserOut
    csrf_token: str
