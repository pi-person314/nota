"""Shared storage layer for score files and undo/redo snapshots.

This module is the contract shared by the Flask web app and the MCP tool
server: both read and write score XML and manage undo/redo history through
these functions, never by touching the filesystem or database directly.

Deliberately framework-free (no Flask imports) so the MCP server — a
separate process — can import it standalone. When imported without an
explicit `configure()` call (e.g. by the MCP server process), it lazily
configures itself from the `DATABASE_URL` and `SCORE_STORAGE_DIR`
environment variables, falling back to the same defaults as the rest of
the app.
"""

from __future__ import annotations

import json
import os
import zlib
from datetime import datetime, timezone

from . import db, models

MAX_SNAPSHOTS_PER_SCORE = 50

_storage_dir: str | None = None
_initialized = False


class ScoreNotFoundError(Exception):
    """Raised when an operation targets a score_id with no matching Score row."""

    def __init__(self, score_id: str):
        super().__init__(f"No score with id {score_id}")
        self.score_id = score_id


def configure(database_url: str | None = None, score_storage_dir: str | None = None) -> None:
    """Explicitly configure the storage layer.

    Callers that own process startup (the Flask app factory, test
    fixtures) should call this once with their resolved config. Safe to
    call more than once (e.g. between tests) — each call re-initializes
    the database engine and storage directory.
    """
    global _storage_dir, _initialized

    if database_url is not None:
        db.init_db(database_url)
    if score_storage_dir is not None:
        _storage_dir = score_storage_dir
        os.makedirs(_storage_dir, exist_ok=True)

    _initialized = True


def _ensure_initialized() -> None:
    if _initialized:
        return
    configure(
        database_url=os.environ.get("DATABASE_URL", "sqlite:///nota.db"),
        score_storage_dir=os.environ.get("SCORE_STORAGE_DIR", "./data/scores"),
    )


def ensure_initialized() -> None:
    """Public entry point for other standalone modules (e.g. MCP tool
    implementations that query `db`/`models` directly for score metadata)
    to trigger the same lazy, environment-variable-based initialization
    used internally by every function in this module. A no-op if
    `configure()` or any storage function already ran.
    """
    _ensure_initialized()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def path_for(score_id: str) -> str | None:
    """Return the filesystem path for a score, or None if no such score exists."""
    _ensure_initialized()
    with db.session_scope() as session:
        score = session.get(models.Score, score_id)
        if score is None:
            return None
        return score.file_path


def read_xml(score_id: str) -> str:
    """Read and return the current MusicXML content for a score."""
    path = path_for(score_id)
    if path is None:
        raise ScoreNotFoundError(score_id)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def write_xml(score_id: str, xml: str) -> None:
    """Overwrite the live MusicXML content for a score."""
    path = path_for(score_id)
    if path is None:
        raise ScoreNotFoundError(score_id)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(xml)


def _thumbnail_path_for(file_path: str) -> str:
    """Derive a thumbnail sidecar path from a score's stored file path."""
    return os.path.splitext(file_path)[0] + ".thumb.json"


def write_thumbnail(score_id: str, svg: str, page_count: int | None) -> None:
    """Persist a rendered thumbnail as a JSON sidecar next to the score's
    live MusicXML file.
    """
    path = path_for(score_id)
    if path is None:
        raise ScoreNotFoundError(score_id)
    thumb_path = _thumbnail_path_for(path)
    os.makedirs(os.path.dirname(thumb_path) or ".", exist_ok=True)
    with open(thumb_path, "w", encoding="utf-8") as f:
        json.dump({"svg": svg, "page_count": page_count}, f)


def read_thumbnail(score_id: str) -> dict | None:
    """Return the stored thumbnail dict for a score, or None if no
    thumbnail has been saved (or the saved file is unreadable/corrupt).
    """
    path = path_for(score_id)
    if path is None:
        raise ScoreNotFoundError(score_id)
    thumb_path = _thumbnail_path_for(path)
    if not os.path.exists(thumb_path):
        return None
    try:
        with open(thumb_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def has_thumbnail(score_id: str) -> bool:
    """Cheap existence check for a score's thumbnail sidecar file.

    Returns False (never raises) if the score itself doesn't exist.
    """
    path = path_for(score_id)
    if path is None:
        return False
    return has_thumbnail_at(path)


def has_thumbnail_at(file_path: str) -> bool:
    """Existence check for the thumbnail sidecar of a score whose live
    file path is already known, avoiding a database lookup.
    """
    return os.path.exists(_thumbnail_path_for(file_path))


def touch_modified(score_id: str) -> None:
    """Update last_modified_at to now."""
    _ensure_initialized()
    with db.session_scope() as session:
        score = session.get(models.Score, score_id)
        if score is not None:
            score.last_modified_at = _now()


def touch_opened(score_id: str) -> None:
    """Update last_opened_at to now."""
    _ensure_initialized()
    with db.session_scope() as session:
        score = session.get(models.Score, score_id)
        if score is not None:
            score.last_opened_at = _now()


def _evict_oldest(session, score_id: str, stack: str, keep: int) -> None:
    """Delete all but the `keep` most recent snapshots on the given stack."""
    ids = [
        row.id
        for row in session.query(models.Snapshot.id)
        .filter_by(score_id=score_id, stack=stack)
        .order_by(models.Snapshot.id.desc())
    ]
    stale_ids = ids[keep:]
    if stale_ids:
        session.query(models.Snapshot).filter(
            models.Snapshot.id.in_(stale_ids)
        ).delete(synchronize_session=False)


def save_snapshot(score_id: str, label: str) -> None:
    """Snapshot the score's current live XML onto the undo stack.

    Intended to be called immediately before a mutation is applied, so the
    saved state represents "the score as it was before `label`". Starting
    a new undo entry invalidates any existing redo history (the usual
    editor convention: once you make a new change, you can no longer redo
    forward past it). Undo history beyond MAX_SNAPSHOTS_PER_SCORE entries
    is evicted, oldest first.
    """
    _ensure_initialized()
    xml = read_xml(score_id)
    compressed = zlib.compress(xml.encode("utf-8"))
    with db.session_scope() as session:
        session.add(
            models.Snapshot(score_id=score_id, xml=compressed, label=label, stack="undo")
        )
        session.query(models.Snapshot).filter_by(score_id=score_id, stack="redo").delete()
        session.flush()
        _evict_oldest(session, score_id, "undo", MAX_SNAPSHOTS_PER_SCORE)


def _pop_and_swap(score_id: str, from_stack: str, to_stack: str) -> str | None:
    """Shared implementation for undo/redo: pop the latest entry off
    `from_stack`, restore it to the live file, and push the current
    (pre-restore) state onto `to_stack` under the same label so the
    operation can be reversed.
    """
    _ensure_initialized()
    with db.session_scope() as session:
        entry = (
            session.query(models.Snapshot)
            .filter_by(score_id=score_id, stack=from_stack)
            .order_by(models.Snapshot.id.desc())
            .first()
        )
        if entry is None:
            return None

        current_xml = read_xml(score_id)
        session.add(
            models.Snapshot(
                score_id=score_id,
                xml=zlib.compress(current_xml.encode("utf-8")),
                label=entry.label,
                stack=to_stack,
            )
        )

        restored_xml = zlib.decompress(entry.xml).decode("utf-8")
        label = entry.label
        session.delete(entry)

    write_xml(score_id, restored_xml)
    touch_modified(score_id)
    return label


def undo(score_id: str) -> str | None:
    """Pop the latest undo snapshot, restore it to the live file, and push
    the current state onto the redo stack. Returns the restored entry's
    label, or None if there is nothing to undo.
    """
    return _pop_and_swap(score_id, from_stack="undo", to_stack="redo")


def redo(score_id: str) -> str | None:
    """Inverse of undo(): pop the latest redo snapshot, restore it to the
    live file, and push the current state back onto the undo stack.
    Returns the restored entry's label, or None if there is nothing to redo.
    """
    return _pop_and_swap(score_id, from_stack="redo", to_stack="undo")


def delete_score_files(score_id: str) -> None:
    """Delete a score's live file, all snapshots, and all command logs.

    Does not delete the Score row itself; callers that also want the row
    removed should do so separately.
    """
    _ensure_initialized()
    path = path_for(score_id)
    with db.session_scope() as session:
        session.query(models.Snapshot).filter_by(score_id=score_id).delete()
        session.query(models.CommandLog).filter_by(score_id=score_id).delete()
    if path:
        if os.path.exists(path):
            os.remove(path)
        thumb_path = _thumbnail_path_for(path)
        if os.path.exists(thumb_path):
            os.remove(thumb_path)
