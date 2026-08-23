"""Background PDF-to-MusicXML conversion pipeline.

Audiveris OMR conversion can take up to a few minutes for a real scan --
far longer than a typical hosting proxy will hold an HTTP request open.
Rather than running it inline within the upload request, the upload route
stages the PDF to disk, creates a `ConversionJob` row, and hands the
actual work off to an in-process worker pool defined here; the client
polls the job's status instead of waiting on the original request.

Because the worker pool's queue lives only in this process's memory, the
`ConversionJob` row (see `models.py`) is the only durable record of an
in-flight conversion. `reconcile_interrupted_jobs` uses that at startup to
clean up anything a previous process life left stranded.

Deferred (function-local) imports are used below for
`nota.routes.musicxml_ingest`: importing it at module level would import
the `nota.routes` package first, which eagerly imports every blueprint
module including `nota.routes.scores` -- and `scores.py` needs to import
this module at call time to submit jobs, which would be a circular import
if this module also pulled in the whole `routes` package just to import
one function from it. By the time a job actually runs, application
startup has long since finished and every module is already fully
imported, so the deferred import here is free.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from . import db as db_module
from . import models
from . import storage
from .services import omr
from .services.omr_quality import assess_omr_output

# A plain module logger, not `current_app.logger`: `run_job` executes on a
# worker thread with no Flask application context, and `current_app`
# requires one.
logger = logging.getLogger(__name__)

# Audiveris is memory- and CPU-hungry (a real page can take tens of
# seconds to a few minutes and runs its own JVM heap); allowing several
# conversions to run concurrently risks exhausting a small hosting
# instance. A single worker deliberately serializes conversions instead --
# a newly submitted job just waits its turn in the executor's internal
# queue rather than stacking concurrently with others.
MAX_WORKERS = 1

_executor: ThreadPoolExecutor | None = None


def _get_executor() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(
            max_workers=MAX_WORKERS, thread_name_prefix="omr-conversion"
        )
    return _executor


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _pending_dir() -> Path:
    path = Path(storage.score_storage_dir()) / "pending"
    path.mkdir(parents=True, exist_ok=True)
    return path


def pending_pdf_path(job_id: str) -> Path:
    """Path a staged upload for `job_id` lives at (whether or not it
    currently exists).
    """
    return _pending_dir() / f"{job_id}.pdf"


def stage_pdf(job_id: str, raw_bytes: bytes) -> None:
    """Write an uploaded PDF's bytes to the pending directory so the
    worker thread that eventually runs this job -- which never sees the
    original HTTP request -- has something to read from disk.
    """
    pending_pdf_path(job_id).write_bytes(raw_bytes)


def submit_job(job_id: str) -> None:
    """Hand `job_id` off to the background worker pool to run
    asynchronously.

    This is the seam tests monkeypatch: replacing it with something that
    calls `run_job(job_id)` synchronously lets a test observe a finished
    job without any real thread timing, and replacing it with a no-op
    lets a test observe the freshly-queued row before anything runs.
    """
    _get_executor().submit(run_job, job_id)


def unfinished_job_count(user_id: str) -> int:
    """Count `user_id`'s jobs still in `queued` or `running`, for
    enforcing a per-user cap on simultaneous conversions.
    """
    with db_module.session_scope() as db_session:
        return (
            db_session.query(models.ConversionJob)
            .filter_by(user_id=user_id)
            .filter(models.ConversionJob.status.in_(("queued", "running")))
            .count()
        )


def _finish_job(
    job_id: str,
    *,
    status: str,
    error_code: str | None = None,
    error_message: str | None = None,
    score_id: str | None = None,
    warnings: list[str] | None = None,
) -> None:
    """Write a job's terminal (or transitional) state in one place, so
    every code path in `_execute` ends the same way.
    """
    with db_module.session_scope() as db_session:
        job = db_session.get(models.ConversionJob, job_id)
        if job is None:
            logger.error("_finish_job: no ConversionJob row for id=%s", job_id)
            return
        job.status = status
        job.error_code = error_code
        job.error_message = error_message
        job.score_id = score_id
        job.warnings_json = json.dumps(warnings or [])
        job.updated_at = _now()


def _execute(job_id: str, pdf_path: Path) -> None:
    """Run the actual OMR -> ingest -> quality-gate -> persist pipeline
    for one job, and record its outcome. Every expected failure mode is
    caught here and turned into a `failed` job row with a specific error
    code; anything that escapes this function is a genuine bug and is
    handled by `run_job`'s outer catch-all instead.
    """
    with db_module.session_scope() as db_session:
        job = db_session.get(models.ConversionJob, job_id)
        if job is None:
            logger.error("_execute: no ConversionJob row for id=%s", job_id)
            return
        job.status = "running"
        job.updated_at = _now()
        filename = job.filename
        user_id = job.user_id

    stem = Path(filename).stem or "score"
    try:
        with tempfile.TemporaryDirectory(prefix="nota-omr-") as tmp_dir:
            output_dir = Path(tmp_dir) / "out"
            produced = omr.convert_pdf_to_musicxml(pdf_path, output_dir)
            omr_filename = f"{stem}{produced.suffix}"
            raw_bytes = produced.read_bytes()
    except omr.OMRNotConfigured as exc:
        _finish_job(
            job_id,
            status="failed",
            error_code="OMR_NOT_CONFIGURED",
            error_message=str(exc) or "PDF import is not configured on this server.",
        )
        return
    except omr.OMRConversionFailed as exc:
        _finish_job(job_id, status="failed", error_code="OMR_FAILED", error_message=str(exc))
        return

    # Deferred import -- see module docstring for why this can't be a
    # top-level import.
    from .routes import musicxml_ingest as ingest

    try:
        metadata = ingest.ingest_upload(omr_filename, raw_bytes)
    except ingest.UploadRejected as exc:
        _finish_job(job_id, status="failed", error_code=exc.code, error_message=exc.message)
        return

    quality = assess_omr_output(metadata.canonical_xml)
    if not quality.acceptable:
        _finish_job(
            job_id,
            status="failed",
            error_code="OMR_LOW_QUALITY",
            error_message=(
                "Audiveris couldn't extract usable notation from this PDF. "
                "A cleaner, higher-resolution scan of printed sheet music works best."
            ),
        )
        return

    score_id = uuid.uuid4().hex
    file_path = os.path.join(storage.score_storage_dir(), f"{score_id}.musicxml")

    with db_module.session_scope() as db_session:
        db_session.add(
            models.Score(
                id=score_id,
                user_id=user_id,
                name=metadata.display_name,
                part_name=metadata.part_name,
                file_path=file_path,
                measure_count=metadata.measure_count,
                has_pickup=metadata.has_pickup,
                parts_json=json.dumps(metadata.parts),
                time_signatures_json=json.dumps(metadata.time_signatures),
                from_pdf=True,
            )
        )

    storage.write_xml(score_id, metadata.canonical_xml)

    _finish_job(job_id, status="succeeded", score_id=score_id, warnings=quality.warnings)


def run_job(job_id: str) -> None:
    """Run one conversion job end to end and record its outcome.

    This is what `submit_job` hands to the worker pool, so it executes on
    a background thread with no Flask application context and no caller
    waiting on its return value -- an exception that escaped this
    function would otherwise vanish into the executor's internal future
    with no trace of what went wrong (nothing ever calls `.result()` on
    it). Every exception is therefore caught here; unexpected ones are
    logged in full and recorded as `INTERNAL_ERROR` rather than allowed to
    propagate. The staged PDF is always deleted afterward, whether the job
    succeeded or failed.
    """
    pdf_path = pending_pdf_path(job_id)
    try:
        _execute(job_id, pdf_path)
    except Exception:
        logger.exception("run_job: unhandled error running conversion job %s", job_id)
        _finish_job(
            job_id,
            status="failed",
            error_code="INTERNAL_ERROR",
            error_message="Something went wrong while converting this file. Please try again.",
        )
    finally:
        try:
            pdf_path.unlink(missing_ok=True)
        except OSError:
            logger.warning(
                "run_job: could not delete staged pdf for job %s at %s",
                job_id,
                pdf_path,
                exc_info=True,
            )


def reconcile_interrupted_jobs() -> None:
    """Fail any job left `queued` or `running` from a previous process
    life, and delete any staged PDF still sitting in the pending
    directory.

    The worker pool and its queue are purely in-memory and do not survive
    a process restart, so a job that was mid-flight (or merely queued)
    when the process died has no worker left that will ever finish it.
    Without this, its row would stay stuck at `running`/`queued` forever
    and a client polling it would never see a terminal state. Meant to be
    called once, early in application startup.
    """
    with db_module.session_scope() as db_session:
        stuck = (
            db_session.query(models.ConversionJob)
            .filter(models.ConversionJob.status.in_(("queued", "running")))
            .all()
        )
        for job in stuck:
            job.status = "failed"
            job.error_code = "SERVER_RESTARTED"
            job.error_message = (
                "The conversion was interrupted by a server restart. Please try uploading again."
            )
            job.updated_at = _now()

    pending_dir = _pending_dir()
    for path in pending_dir.glob("*.pdf"):
        try:
            path.unlink()
        except OSError:
            logger.warning(
                "reconcile_interrupted_jobs: could not delete orphaned staged pdf %s",
                path,
                exc_info=True,
            )
