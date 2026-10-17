"""Admin-managed AI settings: LLM providers, base prompt, letterhead."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class LlmProviderConfig(Base):
    __tablename__ = "llm_provider_configs"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    provider: Mapped[str] = mapped_column(Text, nullable=False)  # claude | gemini | test
    model: Mapped[str] = mapped_column(Text, nullable=False)
    # Encrypted with APP_SECRET_KEY (Fernet). Never returned by the API.
    api_key_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    key_last4: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    updated_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("provider in ('claude', 'gemini', 'test')", name="provider_valid"),
        Index(
            "uq_llm_provider_configs_one_active",
            "is_active",
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )


class PromptVersion(Base):
    """The client's base prompt. Every save is a new row; exactly one is active."""

    __tablename__ = "prompt_versions"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index(
            "uq_prompt_versions_one_active", "is_active", unique=True, postgresql_where=text("is_active")
        ),
    )


class Letterhead(Base):
    __tablename__ = "letterheads"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    header_file_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("files.id", ondelete="RESTRICT"), nullable=False
    )
    footer_file_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("files.id", ondelete="RESTRICT"), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("uq_letterheads_one_active", "is_active", unique=True, postgresql_where=text("is_active")),
    )


class LlmCall(Base):
    """Every call to an LLM provider, with tokens and cost (for usage and the spend cap)."""

    __tablename__ = "llm_calls"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    # SET NULL: deleting a draft must not erase money already spent.
    job_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("generation_jobs.id", ondelete="SET NULL"), index=True
    )
    demand_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("demand_letters.id", ondelete="SET NULL"), index=True
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    cache_read_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    cache_write_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    # Calculated with the prices in effect at the time of the call; null if the model's
    # price is unknown to the app.
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    provider_request_id: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )

    __table_args__ = (
        CheckConstraint(
            "outcome in ('ok', 'rate_limited', 'overloaded', 'error', 'invalid_output')",
            name="outcome_valid",
        ),
    )


class ReferenceLetter(Base):
    """Admin's library of reference demand letters: their FORMAT guides the AI (never their data).

    A reference letter attached in a chat overrides the library for that letter.
    """

    __tablename__ = "reference_letters"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    file_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("files.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    label: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    uploaded_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (CheckConstraint("length(btrim(label)) between 1 and 200", name="label_length"),)
