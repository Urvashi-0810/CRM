from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Identity, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ChatMessage(Base):
    """One message in a letter's chat. One chat = one demand letter."""

    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    demand_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("demand_letters.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sender: Mapped[str] = mapped_column(Text, nullable=False)  # user | assistant
    # user: text · assistant: questions | letter | answer | refusal | error
    # event: approval, upload, restore notes shown in the chat
    kind: Mapped[str] = mapped_column(Text, nullable=False, server_default="text")
    author_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    body: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    # Assistant extras: {"questions": [...], "missing_fields": [...], "version_no": 2}
    data: Mapped[dict | None] = mapped_column(JSONB)
    job_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("generation_jobs.id", ondelete="SET NULL", use_alter=True), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("sender in ('user', 'assistant')", name="sender_valid"),
        CheckConstraint(
            "kind in ('text', 'questions', 'letter', 'answer', 'refusal', 'error', 'event')",
            name="kind_valid"
        ),
    )
