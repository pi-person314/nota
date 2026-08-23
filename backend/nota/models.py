"""SQLAlchemy ORM models for users, scores, undo/redo snapshots, and command history."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    # Nullable to allow OAuth-only accounts with no local password.
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    scores: Mapped[list["Score"]] = relationship(back_populates="user")


class Score(Base):
    __tablename__ = "scores"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    part_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_starred: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    from_pdf: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Path (relative or absolute) to the canonical MusicXML file on disk.
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)

    # Metadata extracted once at upload time; kept on the row so the
    # command orchestrator can build its system prompt without re-parsing
    # the score on every request.
    measure_count: Mapped[int] = mapped_column(Integer, nullable=False)
    has_pickup: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    parts_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    time_signatures_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    last_opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    last_modified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    user: Mapped["User"] = relationship(back_populates="scores")


class Snapshot(Base):
    """A single undo- or redo-stack entry for a score.

    `stack` distinguishes which stack the entry currently belongs to
    ('undo' or 'redo'); entries move between stacks as the user undoes and
    redoes changes. `id` ordering (autoincrement) determines recency within
    a stack.
    """

    __tablename__ = "snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    score_id: Mapped[str] = mapped_column(String(32), ForeignKey("scores.id"), nullable=False)
    xml: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)  # zlib-compressed MusicXML
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    stack: Mapped[str] = mapped_column(String(8), nullable=False)  # 'undo' | 'redo'
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class CommandLog(Base):
    """Record of a single voice/text command, powering conversation history
    and the frontend's history chips.
    """

    __tablename__ = "command_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    score_id: Mapped[str] = mapped_column(String(32), ForeignKey("scores.id"), nullable=False)
    transcript: Mapped[str] = mapped_column(Text, nullable=False)
    tools_called_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    confirmation: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class PasswordResetToken(Base):
    """A single outstanding password-reset request.

    Only a sha256 hash of the raw token is stored, mirroring how passwords
    themselves are never stored in recoverable form — a database leak alone
    can't be used to reset anyone's password. `used_at` is stamped instead
    of deleting the row, so a replayed link can be told apart from one that
    never existed. Multiple outstanding tokens per user are allowed;
    requesting a new one does not invalidate older ones, which instead die
    on their own `expires_at`.
    """

    __tablename__ = "password_reset_tokens"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class UsageCounter(Base):
    """Per-user, per-day, per-endpoint-kind counter backing the daily usage
    quotas on LLM-backed endpoints (voice/text commands, transcription).

    `day` is stored as a UTC "YYYY-MM-DD" string rather than a `DateTime`
    column, so the daily reset boundary always falls at midnight UTC no
    matter what timezone the server process happens to be running in, and
    so the natural per-day key is a plain string rather than a date-range
    query. `kind` distinguishes independent quotas (e.g. "command" vs.
    "transcribe") sharing the same table; the three columns together are
    unique so there is exactly one counter row per user, per day, per kind.
    """

    __tablename__ = "usage_counters"
    __table_args__ = (
        UniqueConstraint("user_id", "day", "kind", name="uq_usage_counters_user_day_kind"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id"), nullable=False)
    day: Mapped[str] = mapped_column(String(10), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
