from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Username = Annotated[
    str, StringConstraints(strip_whitespace=True, pattern=r"^[A-Za-z0-9._-]{3,50}$")
]
DisplayName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
JobTitle = Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)]
# Upper bound only; the minimum length is a setting, checked in the service.
Password = Annotated[str, StringConstraints(min_length=1, max_length=256)]


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    display_name: str
    role: str
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None


class NameChangeRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    requested_name: str
    status: Literal["pending", "approved", "rejected"]
    created_at: datetime
    reviewed_at: datetime | None
    reviewed_by: int | None


class NameChangeRequestWithUser(NameChangeRequestOut):
    username: str
    current_name: str
    reviewed_by_name: str | None = None


class MeOut(BaseModel):
    id: int
    username: str
    display_name: str
    role: str
    pending_name_change: NameChangeRequestOut | None
    admin_active: bool
    admin_until: datetime | None
    # Send this back in the X-CSRF-Token header on every POST/PUT/PATCH/DELETE.
    csrf_token: str


class NameChangeCreate(BaseModel):
    requested_name: DisplayName


class ItemList[T](BaseModel):
    items: list[T] = Field(default_factory=list)


class PasswordChange(BaseModel):
    current_password: Password
    new_password: Password
