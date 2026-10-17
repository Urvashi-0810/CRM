from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class LetterVersion(Base):
    """One saved version of a letter. Never updated or deleted (append-only)."""

    __tablename__ = "letter_versions"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    demand_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("demand_letters.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    # The letter model: {"title": ..., "blocks": [...]}
    content: Mapped[dict] = mapped_column(JSONB, nullable=False)
    missing_fields: Mapped[list | None] = mapped_column(JSONB)
    docx_file_id: Mapped[int] = mapped_column(
        # NO ACTION (checked at end of statement) so deleting a draft can cascade
        # to both its files and its versions in one go.
        BigInteger, ForeignKey("files.id"), nullable=False, unique=True
    )
    prompt_version_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("prompt_versions.id", ondelete="RESTRICT"), index=True
    )
    letterhead_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("letterheads.id", ondelete="RESTRICT"), index=True
    )
    job_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("generation_jobs.id", ondelete="SET NULL"), index=True
    )
    # For source "restored": which version was copied.
    restored_from_no: Mapped[int | None] = mapped_column(Integer)
    created_by: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("demand_id", "version_no", name="uq_letter_versions_demand_version"),
        CheckConstraint(
            "source in ('generated', 'prompt_edit', 'uploaded_edit', 'approval_stamp', 'restored')",
            name="source_valid",
        ),
        CheckConstraint("version_no >= 1", name="version_positive"),
    )
