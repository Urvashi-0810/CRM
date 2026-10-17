from datetime import datetime

from pydantic import BaseModel

from app.modules.users.schemas import DisplayName, JobTitle, Password, Username


class AdminSessionStatus(BaseModel):
    active: bool
    expires_at: datetime | None
    password_configured: bool


class AdminUnlock(BaseModel):
    admin_password: Password


class AdminPasswordChange(BaseModel):
    current_password: Password
    new_password: Password


class UserCreate(BaseModel):
    username: Username
    display_name: DisplayName
    role: JobTitle = ""
    initial_password: Password


class UserUpdate(BaseModel):
    role: JobTitle | None = None
    is_active: bool | None = None


class PasswordReset(BaseModel):
    new_password: Password
