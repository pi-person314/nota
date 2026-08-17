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
