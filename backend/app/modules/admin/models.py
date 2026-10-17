from datetime import datetime

from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Numeric, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class AppSettings(Base):
    """Application-wide settings. Exactly one row (id = true).

    Milestone 1 stores only the admin password hash; later milestones add the
    spend cap and other admin settings here.
    """

    __tablename__ = "app_settings"

    id: Mapped[bool] = mapped_column(Boolean, primary_key=True, server_default=text("true"))
    admin_password_hash: Mapped[str | None] = mapped_column(Text)
    # Monthly AI spend cap (USD). The month is the calendar month in UTC, matching the
    # provider's own billing month. Turned off = no limit from the app.
    spend_cap_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    spend_cap_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    updated_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint("id", name="single_row"),
        CheckConstraint("spend_cap_usd is null or spend_cap_usd >= 0", name="spend_cap_not_negative"),
    )
