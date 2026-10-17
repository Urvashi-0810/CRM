from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Identity, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class LoginSession(Base):
    """A server-side login session.

    The browser only holds a random token in an HttpOnly cookie; we store its SHA-256
    hash, so a database leak does not expose usable session tokens. Keeping sessions
    server-side lets logout and user deactivation take effect immediately.

    The admin unlock (after the separate admin password) is stored on the same row,
    with a short expiry, instead of a second cookie.
    """

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Synchronizer token: must be sent back in the X-CSRF-Token header on every
    # state-changing request.
    csrf_token: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    admin_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
