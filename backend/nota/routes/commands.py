"""Command orchestration endpoints: the voice/text command loop, direct
undo/redo (no LLM round-trip), and command history.

Ownership is enforced the same way as every other score-scoped route (see
`scores.py`): a 404 if the score doesn't exist, 403 if it belongs to
another user. This module owns its own copy of that check rather than
importing from `scores.py`, keeping route modules independent.
"""

from __future__ import annotations

import json

from flask import Blueprint, jsonify, request

from .. import db as db_module
from .. import models
from .. import storage
from ..orchestrator import loop, locks
from ._helpers import current_user_id, error_response, iso_utc, login_required

bp = Blueprint("commands", __name__, url_prefix="/api/scores")

HISTORY_LIMIT = 50

# Module-level (not a bound default parameter) so tests can shrink it via
# monkeypatch to exercise the 409 COMMAND_IN_PROGRESS path without waiting
# out the real 15s budget.
COMMAND_LOCK_TIMEOUT = locks.DEFAULT_LOCK_TIMEOUT


def _fetch_owned_score(db_session, score_id: str):
    """Look up a score and enforce ownership; see scores.py for the same
    pattern. Returns `(score, None)` or `(None, error_response_tuple)`.
    """
    score = db_session.get(models.Score, score_id)
    if score is None:
        return None, error_response(404, "SCORE_NOT_FOUND", "No score with that id.")
    if score.user_id != current_user_id():
        return None, error_response(403, "FORBIDDEN", "You do not have access to this score.")
    return score, None


@bp.post("/<score_id>/command")
@login_required
def command(score_id):
    with db_module.session_scope() as db_session:
        _, err = _fetch_owned_score(db_session, score_id)
        if err:
            return err

    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    if len(text) < 2:
        return error_response(422, "EMPTY_TRANSCRIPT", "Transcript is empty or too short.")

    try:
        with locks.score_lock(score_id, timeout=COMMAND_LOCK_TIMEOUT):
            try:
                result = loop.run_command(score_id, text)
            except loop.LLMNotConfiguredError:
                return error_response(
                    503,
                    "LLM_NOT_CONFIGURED",
                    "The command assistant is not configured on this server.",
                )
            except storage.ScoreNotFoundError:
                return error_response(404, "SCORE_NOT_FOUND", "No score with that id.")
    except locks.LockTimeout:
        return error_response(
            409, "COMMAND_IN_PROGRESS", "Still working on the previous command."
        )

    return jsonify(result), 200


@bp.post("/<score_id>/undo")
@login_required
def undo(score_id):
    with db_module.session_scope() as db_session:
        _, err = _fetch_owned_score(db_session, score_id)
        if err:
            return err

    try:
        with locks.score_lock(score_id, timeout=COMMAND_LOCK_TIMEOUT):
            label = storage.undo(score_id)
    except locks.LockTimeout:
        return error_response(
            409, "COMMAND_IN_PROGRESS", "Still working on the previous command."
        )

    if label is None:
        return error_response(409, "NOTHING_TO_UNDO", "There is nothing to undo.")

    return (
        jsonify(
            {
                "musicxml": storage.read_xml(score_id),
                "summary": f"Undid: {label}",
                "changed_element_ids": [],
            }
        ),
        200,
    )


@bp.post("/<score_id>/redo")
@login_required
def redo(score_id):
    with db_module.session_scope() as db_session:
        _, err = _fetch_owned_score(db_session, score_id)
        if err:
            return err

    try:
        with locks.score_lock(score_id, timeout=COMMAND_LOCK_TIMEOUT):
            label = storage.redo(score_id)
    except locks.LockTimeout:
        return error_response(
            409, "COMMAND_IN_PROGRESS", "Still working on the previous command."
        )

    if label is None:
        return error_response(409, "NOTHING_TO_REDO", "There is nothing to redo.")

    return (
        jsonify(
            {
                "musicxml": storage.read_xml(score_id),
                "summary": f"Redid: {label}",
                "changed_element_ids": [],
            }
        ),
        200,
    )


@bp.get("/<score_id>/history")
@login_required
def history(score_id):
    with db_module.session_scope() as db_session:
        _, err = _fetch_owned_score(db_session, score_id)
        if err:
            return err

        rows = (
            db_session.query(models.CommandLog)
            .filter_by(score_id=score_id)
            .order_by(models.CommandLog.id.desc())
            .limit(HISTORY_LIMIT)
            .all()
        )
        items = [
            {
                "id": row.id,
                "transcript": row.transcript,
                "confirmation": row.confirmation,
                "tools_called": json.loads(row.tools_called_json or "[]"),
                "created_at": iso_utc(row.created_at),
            }
            for row in rows
        ]

    return jsonify({"items": items}), 200
