"""Score upload and CRUD routes.

Upload parsing/validation lives in `musicxml_ingest`; this module wires
that pipeline to HTTP, persists the resulting metadata via the existing
`storage`/`models` contracts, and enforces ownership on every score-scoped
route.
"""

from __future__ import annotations

import json
import os
import re
import uuid

from flask import Blueprint, current_app, jsonify, request

from .. import db as db_module
from .. import models
from .. import storage
from . import musicxml_ingest as ingest
from ._helpers import current_user_id, error_response, login_required

bp = Blueprint("scores", __name__, url_prefix="/api/scores")

SORT_FIELDS = {
    "last_opened": (models.Score.last_opened_at, True),
    "last_modified": (models.Score.last_modified_at, True),
    "date_uploaded": (models.Score.created_at, True),
    "name_asc": (models.Score.name, False),
    "name_desc": (models.Score.name, True),
}
DEFAULT_SORT = "last_opened"


def _score_summary(score: models.Score) -> dict:
    return {
        "id": score.id,
        "name": score.name,
        "part_name": score.part_name,
        "is_starred": score.is_starred,
        "measure_count": score.measure_count,
        "has_pickup": score.has_pickup,
        "created_at": score.created_at.isoformat(),
        "last_opened_at": score.last_opened_at.isoformat(),
        "last_modified_at": score.last_modified_at.isoformat(),
    }


def _fetch_owned_score(db_session, score_id: str):
    """Look up a score and enforce ownership.

    Returns `(score, None)` on success or `(None, error_response_tuple)`
    on failure — 404 if the score doesn't exist, 403 if it exists but
    belongs to a different user. Callers should `return err` immediately
    when it is not None.
    """
    score = db_session.get(models.Score, score_id)
    if score is None:
        return None, error_response(404, "SCORE_NOT_FOUND", "No score with that id.")
    if score.user_id != current_user_id():
        return None, error_response(
            403, "FORBIDDEN", "You do not have access to this score."
        )
    return score, None


def _safe_export_filename(name: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9 ._-]", "_", name or "").strip() or "score"
    return f"{stem}.musicxml"


@bp.post("/upload")
@login_required
def upload():
    cfg = current_app.config["NOTA_CONFIG"]

    upload_file = request.files.get("file")
    if upload_file is None or not upload_file.filename:
        return error_response(422, "MISSING_FILE", "No file was uploaded.")

    raw_bytes = upload_file.read()
    if len(raw_bytes) > cfg.max_upload_bytes:
        return error_response(
            413,
            "FILE_TOO_LARGE",
            f"File exceeds the {cfg.max_upload_mb} MB upload limit.",
        )

    try:
        metadata = ingest.ingest_upload(upload_file.filename, raw_bytes)
    except ingest.UploadRejected as exc:
        return error_response(exc.status, exc.code, exc.message)

    score_id = uuid.uuid4().hex
    file_path = os.path.join(cfg.score_storage_dir, f"{score_id}.musicxml")

    with db_module.session_scope() as db_session:
        score = models.Score(
            id=score_id,
            user_id=current_user_id(),
            name=metadata.display_name,
            part_name=metadata.part_name,
            file_path=file_path,
            measure_count=metadata.measure_count,
            has_pickup=metadata.has_pickup,
            parts_json=json.dumps(metadata.parts),
            time_signatures_json=json.dumps(metadata.time_signatures),
        )
        db_session.add(score)
        db_session.flush()
        summary = _score_summary(score)

    storage.write_xml(score_id, metadata.canonical_xml)

    return jsonify(summary), 201


@bp.get("")
@login_required
def list_scores():
    sort = request.args.get("sort", DEFAULT_SORT)
    if sort not in SORT_FIELDS:
        return error_response(
            422,
            "INVALID_SORT",
            f"Unknown sort '{sort}'. Valid values: {', '.join(SORT_FIELDS)}.",
        )
    starred_only = request.args.get("starred", "").strip().lower() == "true"

    column, descending = SORT_FIELDS[sort]
    order = column.desc() if descending else column.asc()

    with db_module.session_scope() as db_session:
        query = db_session.query(models.Score).filter_by(user_id=current_user_id())
        if starred_only:
            query = query.filter_by(is_starred=True)
        scores = query.order_by(order).all()
        summaries = [_score_summary(s) for s in scores]

    return jsonify(summaries), 200


@bp.get("/<score_id>")
@login_required
def get_score(score_id):
    with db_module.session_scope() as db_session:
        _, err = _fetch_owned_score(db_session, score_id)
        if err:
            return err

    storage.touch_opened(score_id)

    with db_module.session_scope() as db_session:
        score = db_session.get(models.Score, score_id)
        summary = _score_summary(score)
        parts = json.loads(score.parts_json)
        time_signatures = json.loads(score.time_signatures_json)

    xml = storage.read_xml(score_id)
    payload = {
        **summary,
        "parts": parts,
        "time_signatures": time_signatures,
        "musicxml": xml,
    }
    return jsonify(payload), 200


@bp.patch("/<score_id>")
@login_required
def update_score(score_id):
    data = request.get_json(silent=True) or {}
    if "name" not in data and "is_starred" not in data:
        return error_response(
            422, "INVALID_INPUT", "Provide name and/or is_starred to update."
        )

    with db_module.session_scope() as db_session:
        score, err = _fetch_owned_score(db_session, score_id)
        if err:
            return err

        if "name" in data:
            name = (data.get("name") or "").strip()
            if not name:
                return error_response(422, "INVALID_INPUT", "name cannot be empty.")
            score.name = name

        if "is_starred" in data:
            score.is_starred = bool(data.get("is_starred"))

        db_session.flush()
        summary = _score_summary(score)

    return jsonify(summary), 200


@bp.delete("/<score_id>")
@login_required
def delete_score(score_id):
    with db_module.session_scope() as db_session:
        _, err = _fetch_owned_score(db_session, score_id)
        if err:
            return err

    # Delete the file + snapshots + logs first (storage.delete_score_files
    # needs the Score row to still exist to resolve the file path), then
    # remove the row itself.
    storage.delete_score_files(score_id)

    with db_module.session_scope() as db_session:
        score = db_session.get(models.Score, score_id)
        if score is not None:
            db_session.delete(score)

    return jsonify({"ok": True}), 200


@bp.get("/<score_id>/export")
@login_required
def export_score(score_id):
    with db_module.session_scope() as db_session:
        score, err = _fetch_owned_score(db_session, score_id)
        if err:
            return err
        name = score.name

    xml = storage.read_xml(score_id)
    filename = _safe_export_filename(name)

    response = current_app.response_class(
        xml, mimetype="application/vnd.recordare.musicxml+xml"
    )
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
