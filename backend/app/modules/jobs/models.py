from datetime import datetime

from sqlalchemy import (
    BigInteger,
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


class GenerationJob(Base):
    """Slow work done by the worker (AI calls, building the .docx).

    This table is both the queue and the status the browser polls. A worker claims a
    job with SELECT ... FOR UPDATE SKIP LOCKED and keeps a lease on it; if the worker
    dies, the lease expires and another worker picks the job up again.
    """

    __tablename__ = "generation_jobs"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    demand_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("demand_letters.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False, server_default="chat")
    state: Mapped[str] = mapped_column(Text, nullable=False, server_default="queued")
    # The user message this job answers.
    message_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("chat_messages.id", ondelete="CASCADE"), nullable=False
    )
    requested_by: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    result_message_id: Mapped[int | None] = mapped_column(BigInteger)
    result_version_no: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("kind in ('chat')", name="kind_valid"),
        CheckConstraint(
            "state in ('queued', 'running', 'succeeded', 'failed')", name="state_valid"
        ),
        # At most one active job per letter (double click / two tabs).
        Index(
            "uq_generation_jobs_one_active",
            "demand_id",
            unique=True,
            postgresql_where=text("state in ('queued', 'running')"),
        ),
        Index("ix_generation_jobs_pick", "state", "created_at"),
    )
