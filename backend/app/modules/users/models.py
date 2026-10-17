from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class User(Base):
    """A team member. The profile (name, role) lives here: one user = one profile."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    username: Mapped[str] = mapped_column(Text, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    # Job title, set by the admin (e.g. "Operations Lead"). Not a permission.
    role: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    # Users are deactivated, never deleted (other records point at them).
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Wrong admin-password attempts are counted per user (not per login), so
    # logging in again does not reset the count.
    admin_failed_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    admin_locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        # Usernames are unique regardless of letter case ("Priya" == "priya").
        Index("uq_users_username_lower", func.lower(username), unique=True),
        CheckConstraint("length(username) between 3 and 50", name="username_length"),
        CheckConstraint("length(btrim(display_name)) between 1 and 100", name="display_name_length"),
        CheckConstraint("length(role) <= 100", name="role_length"),
    )


class NameChangeRequest(Base):
    """A user's request to change their display name; the admin approves or rejects it."""

    __tablename__ = "name_change_requests"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    requested_name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    reviewed_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("status in ('pending', 'approved', 'rejected')", name="status_valid"),
        CheckConstraint(
            "length(btrim(requested_name)) between 1 and 100", name="requested_name_length"
        ),
        CheckConstraint(
            "(status = 'pending') = (reviewed_at is null)", name="reviewed_matches_status"
        ),
        # At most one pending request per user.
        Index(
            "uq_name_change_requests_one_pending",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
    )
