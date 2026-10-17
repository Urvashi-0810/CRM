from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    PrimaryKeyConstraint,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

# Demand codes: 2 letters + 5 digits. AA00001 .. AA99999, AB00001, ... ZZ99999.
PER_PREFIX = 99_999
MAX_ID_NUMBER = 26 * 26 * PER_PREFIX  # 67,599,324

# The code is computed by PostgreSQL from id_number, so the two can never disagree.
DEMAND_CODE_SQL = (
    "chr(65 + ((id_number - 1) / 99999) / 26)"
    " || chr(65 + ((id_number - 1) / 99999) % 26)"
    " || lpad((((id_number - 1) % 99999) + 1)::text, 5, '0')"
)


def format_demand_code(id_number: int) -> str:
    """Python twin of DEMAND_CODE_SQL (used in tests and scripts)."""
    if not 1 <= id_number <= MAX_ID_NUMBER:
        raise ValueError("id_number out of range")
    prefix, seq = divmod(id_number - 1, PER_PREFIX)
    return f"{chr(65 + prefix // 26)}{chr(65 + prefix % 26)}{seq + 1:05d}"


class DemandLetter(Base):
    """One demand letter: a draft, then sent for approval ("pending"), then approved by an
    admin and shown in the demand list."""

    __tablename__ = "demand_letters"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    # Position in the ID sequence. Lowest free number is reused when a draft is deleted.
    id_number: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    demand_code: Mapped[str] = mapped_column(
        Text, Computed(DEMAND_CODE_SQL, persisted=True), nullable=False, unique=True
    )
    lifecycle: Mapped[str] = mapped_column(Text, nullable=False, server_default="draft")
    # Recruitment progress; comes from the tracker in a later phase.
    progress_status: Mapped[str] = mapped_column(Text, nullable=False, server_default="Start")

    country: Mapped[str | None] = mapped_column(Text)
    employer: Mapped[str | None] = mapped_column(Text)
    vacancy: Mapped[int | None] = mapped_column(Integer)
    target_timeline: Mapped[str | None] = mapped_column(Text)
    assign_to: Mapped[str | None] = mapped_column(Text)

    created_by: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    approved_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    # Who sent it for approval, and when. Cleared when an admin sends it back.
    submitted_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # Bumped on every change; sent to the browser as the ETag so a stale save is refused.
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    # Fields a person edited by hand ("country", "employer", "vacancy", "trades").
    # The AI fills the others after each generation, but never overwrites these.
    manual_fields: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default="{}"
    )

    __table_args__ = (
        CheckConstraint("lifecycle in ('draft', 'pending', 'approved')", name="lifecycle_valid"),
        CheckConstraint(
            "lifecycle <> 'pending' or (submitted_at is not null and submitted_by is not null)",
            name="pending_has_submitter",
        ),
        CheckConstraint(
            "(lifecycle = 'approved') = (approved_at is not null and approved_by is not null)",
            name="approval_fields_match_lifecycle",
        ),
        CheckConstraint(f"id_number between 1 and {MAX_ID_NUMBER}", name="id_number_range"),
        CheckConstraint("vacancy is null or vacancy >= 0", name="vacancy_not_negative"),
        Index("ix_demand_letters_lifecycle_approved_at", "lifecycle", "approved_at"),
    )


class DemandTrade(Base):
    """One position in a demand letter (trade + quantity, optionally per project)."""

    __tablename__ = "demand_trades"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    demand_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("demand_letters.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project: Mapped[str | None] = mapped_column(Text)
    trade: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("length(btrim(trade)) > 0", name="trade_not_blank"),
    )


class StoredFile(Base):
    """Metadata for a file kept in storage (the bytes live in folders / Cloud Storage)."""

    __tablename__ = "files"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    # Null for admin files (reference letters, letterhead) that belong to no letter.
    demand_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("demand_letters.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    original_filename: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(Text, nullable=False)
    uploaded_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    # The chat message the file was attached to (chat uploads only).
    message_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("chat_messages.id", ondelete="CASCADE"), index=True
    )
    # Text/tables/image list read from the file, cached so it is read only once.
    extracted: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "kind in ('inquiry', 'jd', 'custom_reference', 'edited_upload', 'generated_docx',"
            " 'extracted_image', 'admin_reference', 'letterhead_header', 'letterhead_footer')",
            name="kind_valid",
        ),
        CheckConstraint("size_bytes >= 0", name="size_not_negative"),
    )


class IdempotencyKey(Base):
    """Remembers "Add Demand Letter" requests so a double click or retry reuses the same draft."""

    __tablename__ = "idempotency_keys"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    key: Mapped[str] = mapped_column(Text, nullable=False)
    demand_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("demand_letters.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )

    __table_args__ = (
        PrimaryKeyConstraint("user_id", "key"),
        CheckConstraint("length(key) between 8 and 200", name="key_length"),
    )
