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
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import Blueprint, current_app, jsonify, request

from .. import conversion
from .. import db as db_module
from .. import models
from .. import storage
from . import musicxml_ingest as ingest
from ._helpers import current_user_id, error_response, iso_utc, login_required

bp = Blueprint("scores", __name__, url_prefix="/api/scores")

PDF_EXTENSION = ".pdf"

MAX_THUMBNAIL_SVG_CHARS = 2_000_000

# How many PDF conversions a single user may have queued or running at
# once. Audiveris conversions are serialized onto one worker (see
# conversion.py), so without a cap one user queuing many large PDFs could
# make every other user's conversions wait behind all of them.
MAX_UNFINISHED_JOBS = 3

# How far back GET /api/scores/jobs looks. Long enough that a user who
# steps away mid-conversion and comes back later still finds it, short
# enough that the list doesn't accumulate months of old jobs.
JOB_LIST_WINDOW = timedelta(hours=24)
JOB_LIST_LIMIT = 20

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
        "is_archived": score.is_archived,
        "from_pdf": score.from_pdf,
        "measure_count": score.measure_count,
        "has_pickup": score.has_pickup,
        "created_at": iso_utc(score.created_at),
        "last_opened_at": iso_utc(score.last_opened_at),
        "last_modified_at": iso_utc(score.last_modified_at),
        "has_thumbnail": storage.has_thumbnail_at(score.file_path),
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


def _omr_configured() -> bool:
    """Cheap check for whether PDF import is set up at all, so an upload
    can fail fast at 422 instead of queueing a background job that's
    doomed to fail once a worker eventually picks it up.

    Mirrors `services/omr.py`'s own `AUDIVERIS_PATH` + path-existence
    check (`_audiveris_launcher`) rather than importing it: that module
    exposes no public "is configured" query, and adding one is outside
    the scope of this change.
    """
    launcher = os.environ.get("AUDIVERIS_PATH")
    return bool(launcher) and Path(launcher).is_file()


def _job_summary(job: models.ConversionJob) -> dict:
    return {
        "id": job.id,
        "status": job.status,
        "filename": job.filename,
        "score_id": job.score_id,
        "error_code": job.error_code,
        "error_message": job.error_message,
        "warnings": json.loads(job.warnings_json or "[]"),
        "created_at": iso_utc(job.created_at),
        "updated_at": iso_utc(job.updated_at),
    }


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

    filename = upload_file.filename
    from_pdf = ingest.extension_of(filename) == PDF_EXTENSION

    if from_pdf:
        # PDFs go through Audiveris OMR, which can take minutes -- far
        # longer than a request should stay open. This queues a
        # background ConversionJob and returns immediately; the client
        # polls GET /api/scores/jobs/<job_id> for the result instead of
        # waiting on this response. Every other upload type is handled
        # inline below, unchanged.
        if not _omr_configured():
            return error_response(
                422,
                "OMR_NOT_CONFIGURED",
                "PDF import is not configured on this server.",
            )

        user_id = current_user_id()
        if conversion.unfinished_job_count(user_id) >= MAX_UNFINISHED_JOBS:
            return error_response(
                429,
                "TOO_MANY_CONVERSIONS",
                f"You already have {MAX_UNFINISHED_JOBS} PDF conversions in "
                "progress. Wait for one to finish before starting another.",
            )

        job_id = uuid.uuid4().hex
        with db_module.session_scope() as db_session:
            db_session.add(
                models.ConversionJob(
                    id=job_id, user_id=user_id, filename=filename, status="queued"
                )
            )

        conversion.stage_pdf(job_id, raw_bytes)
        conversion.submit_job(job_id)

        return jsonify({"job_id": job_id, "status": "queued", "filename": filename}), 202

    try:
        metadata = ingest.ingest_upload(filename, raw_bytes)
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
            from_pdf=False,
        )
        db_session.add(score)
        db_session.flush()
        summary = _score_summary(score)

    storage.write_xml(score_id, metadata.canonical_xml)

    return jsonify(summary), 201


@bp.get("/jobs/<job_id>")
@login_required
def get_job(job_id):
    with db_module.session_scope() as db_session:
        job = db_session.get(models.ConversionJob, job_id)
        if job is None:
            return error_response(404, "JOB_NOT_FOUND", "No conversion job with that id.")
        if job.user_id != current_user_id():
            return error_response(403, "FORBIDDEN", "You do not have access to this job.")
        summary = _job_summary(job)

    return jsonify(summary), 200


@bp.get("/jobs")
@login_required
def list_jobs():
    cutoff = datetime.now(timezone.utc) - JOB_LIST_WINDOW
    with db_module.session_scope() as db_session:
        jobs = (
            db_session.query(models.ConversionJob)
            .filter_by(user_id=current_user_id())
            .filter(models.ConversionJob.created_at >= cutoff)
            .order_by(models.ConversionJob.created_at.desc())
            .limit(JOB_LIST_LIMIT)
            .all()
        )
        items = [_job_summary(job) for job in jobs]

    return jsonify({"items": items}), 200


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
    archived_filter = request.args.get("archived", "").strip().lower()

    column, descending = SORT_FIELDS[sort]
    order = column.desc() if descending else column.asc()

    with db_module.session_scope() as db_session:
        query = db_session.query(models.Score).filter_by(user_id=current_user_id())
        if starred_only:
            query = query.filter_by(is_starred=True)
        if archived_filter == "true":
            query = query.filter_by(is_archived=True)
        elif archived_filter != "all":
            query = query.filter_by(is_archived=False)
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
    if "name" not in data and "is_starred" not in data and "is_archived" not in data:
        return error_response(
            422, "INVALID_INPUT", "Provide name, is_starred, and/or is_archived to update."
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

        if "is_archived" in data:
            score.is_archived = bool(data.get("is_archived"))

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


@bp.put("/<score_id>/thumbnail")
@login_required
def put_thumbnail(score_id):
    with db_module.session_scope() as db_session:
        _, err = _fetch_owned_score(db_session, score_id)
        if err:
            return err

    data = request.get_json(silent=True) or {}
    svg = data.get("svg")
    if not isinstance(svg, str) or not svg:
        return error_response(422, "INVALID_THUMBNAIL", "svg must be a non-empty string.")
    if len(svg) > MAX_THUMBNAIL_SVG_CHARS:
        return error_response(413, "THUMBNAIL_TOO_LARGE", "Thumbnail SVG is too large.")
    if not svg.lstrip().startswith(("<svg", "<?xml")):
        return error_response(422, "INVALID_THUMBNAIL", "svg does not look like an SVG document.")

    page_count = data.get("page_count")
    if page_count is not None:
        if isinstance(page_count, bool) or not isinstance(page_count, int) or page_count <= 0:
            return error_response(422, "INVALID_THUMBNAIL", "page_count must be a positive integer.")

    storage.write_thumbnail(score_id, svg, page_count)
    return jsonify({"ok": True}), 200


@bp.get("/<score_id>/thumbnail")
@login_required
def get_thumbnail(score_id):
    with db_module.session_scope() as db_session:
        _, err = _fetch_owned_score(db_session, score_id)
        if err:
            return err

    thumbnail = storage.read_thumbnail(score_id)
    if thumbnail is None:
        return error_response(404, "THUMBNAIL_NOT_FOUND", "No thumbnail stored for this score.")

    return jsonify(
        {"svg": thumbnail.get("svg"), "page_count": thumbnail.get("page_count")}
    ), 200


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
