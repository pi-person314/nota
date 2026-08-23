"""Tests for the background PDF-to-MusicXML conversion job pipeline:
the `/api/scores/upload` route's async PDF path, the `ConversionJob`
model it drives, the `/api/scores/jobs` status/list endpoints, and
`conversion.reconcile_interrupted_jobs`.

`conversion.submit_job` is monkeypatched in every test so nothing here
depends on real background-thread timing: `sync_jobs` makes it run the
job synchronously in the calling thread (for tests that want to observe
a finished outcome), and `noop_submit` makes it a no-op (for tests that
want to observe the freshly-queued row, e.g. the per-user job cap).
Audiveris itself is always mocked via `nota.services.omr.convert_pdf_to_musicxml`,
the same way tests/routes/test_upload_pdf.py mocks it for the synchronous
upload path.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from fixtures.musicxml_builders import (
    omr_clean_score_bytes,
    omr_mostly_empty_score_bytes,
    omr_warning_level_score_bytes,
    simple_score_bytes,
)

from nota import conversion
from nota import db as db_module
from nota import models
from nota.services import omr

PDF_BYTES = b"%PDF-1.4 fake pdf bytes"


def _upload_pdf(client, filename="scanned.pdf", content: bytes = PDF_BYTES):
    return client.post(
        "/api/scores/upload",
        data={"file": (io.BytesIO(content), filename)},
        content_type="multipart/form-data",
    )


def _install_fake_omr(monkeypatch, *, xml_bytes=None, suffix=".musicxml", exc=None):
    """Monkeypatch `omr.convert_pdf_to_musicxml` so no real Audiveris runs.
    On success, writes `xml_bytes` to a real file under `output_dir` and
    returns its path, matching the real function's contract; `exc` makes
    it raise instead.
    """

    def fake_convert(pdf_path, output_dir, *, timeout_s=omr.DEFAULT_TIMEOUT_S):
        if exc is not None:
            raise exc
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        produced = output_dir / f"converted{suffix}"
        produced.write_bytes(xml_bytes)
        return produced

    monkeypatch.setattr(omr, "convert_pdf_to_musicxml", fake_convert)


@pytest.fixture(autouse=True)
def configured_omr(monkeypatch, tmp_path):
    """Point AUDIVERIS_PATH at a real (but fake-content) file for every
    test in this module by default, so `upload()`'s own inline
    "is OMR configured" check (independent of whatever
    `omr.convert_pdf_to_musicxml` itself is mocked to do) passes and
    requests reach the job-queueing logic under test. The one test that
    specifically exercises the unconfigured case removes it again with
    `monkeypatch.delenv`.
    """
    launcher = tmp_path / "Audiveris.exe"
    launcher.write_text("fake launcher")
    monkeypatch.setenv("AUDIVERIS_PATH", str(launcher))
    return launcher


@pytest.fixture
def sync_jobs(monkeypatch):
    """Run every submitted job synchronously, in the request thread."""
    monkeypatch.setattr(conversion, "submit_job", lambda job_id: conversion.run_job(job_id))


@pytest.fixture
def noop_submit(monkeypatch):
    """Never actually run a submitted job -- it stays `queued` forever."""
    monkeypatch.setattr(conversion, "submit_job", lambda job_id: None)


def _get_job_row(job_id: str) -> models.ConversionJob | None:
    with db_module.session_scope() as db_session:
        return db_session.get(models.ConversionJob, job_id)


# --- upload() PDF path: queueing -------------------------------------------


def test_pdf_upload_returns_202_with_queued_job(auth_client, noop_submit, monkeypatch):
    _install_fake_omr(monkeypatch, xml_bytes=simple_score_bytes())

    resp = _upload_pdf(auth_client, "scanned.pdf")

    assert resp.status_code == 202
    body = resp.get_json()
    assert body["status"] == "queued"
    assert body["filename"] == "scanned.pdf"
    assert "job_id" in body and body["job_id"]

    row = _get_job_row(body["job_id"])
    assert row is not None
    assert row.status == "queued"
    assert row.filename == "scanned.pdf"


def test_pdf_upload_not_configured_is_422_before_queueing(auth_client, monkeypatch):
    # AUDIVERIS_PATH unset (default test env) -- the fast-fail check must
    # reject before any job row is ever created.
    monkeypatch.delenv("AUDIVERIS_PATH", raising=False)

    resp = _upload_pdf(auth_client, "scanned.pdf")

    assert resp.status_code == 422
    assert resp.get_json()["error"] == "OMR_NOT_CONFIGURED"

    with db_module.session_scope() as db_session:
        assert db_session.query(models.ConversionJob).count() == 0


def test_pdf_upload_respects_existing_size_cap(auth_client, app, monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("OMR should not run for an oversized upload")

    monkeypatch.setattr(omr, "convert_pdf_to_musicxml", fail_if_called)

    cfg = app.config["NOTA_CONFIG"]
    oversized = b"%PDF-1.4" + b"a" * (cfg.max_upload_bytes + 1)

    resp = _upload_pdf(auth_client, "big.pdf", oversized)

    assert resp.status_code == 413
    assert resp.get_json()["error"] == "FILE_TOO_LARGE"
    with db_module.session_scope() as db_session:
        assert db_session.query(models.ConversionJob).count() == 0


# --- run_job outcomes --------------------------------------------------


def test_pdf_upload_happy_path_job_succeeds_with_score(auth_client, sync_jobs, monkeypatch):
    _install_fake_omr(monkeypatch, xml_bytes=omr_clean_score_bytes(title="Scanned Piece"))

    resp = _upload_pdf(auth_client, "scanned.pdf")
    assert resp.status_code == 202
    job_id = resp.get_json()["job_id"]

    status = auth_client.get(f"/api/scores/jobs/{job_id}")
    assert status.status_code == 200
    body = status.get_json()
    assert body["status"] == "succeeded"
    assert body["score_id"]
    assert body["error_code"] is None
    assert body["error_message"] is None
    assert body["warnings"] == []

    detail = auth_client.get(f"/api/scores/{body['score_id']}")
    assert detail.status_code == 200
    detail_body = detail.get_json()
    assert detail_body["name"] == "Scanned Piece"
    assert detail_body["from_pdf"] is True

    # The staged PDF is cleaned up once the job finishes.
    assert not conversion.pending_pdf_path(job_id).exists()


def test_pdf_upload_conversion_failure_job_fails_with_omr_failed(
    auth_client, sync_jobs, monkeypatch
):
    _install_fake_omr(monkeypatch, exc=omr.OMRConversionFailed("Audiveris exited with status 1."))

    resp = _upload_pdf(auth_client, "scanned.pdf")
    job_id = resp.get_json()["job_id"]

    status = auth_client.get(f"/api/scores/jobs/{job_id}")
    body = status.get_json()
    assert body["status"] == "failed"
    assert body["error_code"] == "OMR_FAILED"
    assert "status 1" in body["error_message"]
    assert body["score_id"] is None

    with db_module.session_scope() as db_session:
        assert db_session.query(models.Score).count() == 0

    assert not conversion.pending_pdf_path(job_id).exists()


def test_pdf_upload_mostly_empty_output_job_fails_with_low_quality(
    auth_client, sync_jobs, monkeypatch
):
    _install_fake_omr(monkeypatch, xml_bytes=omr_mostly_empty_score_bytes())

    resp = _upload_pdf(auth_client, "scanned.pdf")
    job_id = resp.get_json()["job_id"]

    status = auth_client.get(f"/api/scores/jobs/{job_id}")
    body = status.get_json()
    assert body["status"] == "failed"
    assert body["error_code"] == "OMR_LOW_QUALITY"

    with db_module.session_scope() as db_session:
        assert db_session.query(models.Score).count() == 0


def test_pdf_upload_warning_level_output_job_succeeds_with_warnings(
    auth_client, sync_jobs, monkeypatch
):
    _install_fake_omr(monkeypatch, xml_bytes=omr_warning_level_score_bytes())

    resp = _upload_pdf(auth_client, "scanned.pdf")
    job_id = resp.get_json()["job_id"]

    status = auth_client.get(f"/api/scores/jobs/{job_id}")
    body = status.get_json()
    assert body["status"] == "succeeded"
    assert body["warnings"] != []


def test_pdf_upload_unparseable_output_job_fails_with_ingest_error_code(
    auth_client, sync_jobs, monkeypatch
):
    _install_fake_omr(monkeypatch, xml_bytes=b"not xml at all")

    resp = _upload_pdf(auth_client, "scanned.pdf")
    job_id = resp.get_json()["job_id"]

    status = auth_client.get(f"/api/scores/jobs/{job_id}")
    body = status.get_json()
    assert body["status"] == "failed"
    assert body["error_code"] == "INVALID_XML"


# --- job status endpoint: ownership, 404 --------------------------------


def test_job_status_unknown_id_is_404(auth_client):
    resp = auth_client.get("/api/scores/jobs/does-not-exist")
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "JOB_NOT_FOUND"


def test_job_status_enforces_ownership(auth_client, second_auth_client, noop_submit, monkeypatch):
    _install_fake_omr(monkeypatch, xml_bytes=simple_score_bytes())
    resp = _upload_pdf(auth_client, "scanned.pdf")
    job_id = resp.get_json()["job_id"]

    other = second_auth_client.get(f"/api/scores/jobs/{job_id}")
    assert other.status_code == 403
    assert other.get_json()["error"] == "FORBIDDEN"

    mine = auth_client.get(f"/api/scores/jobs/{job_id}")
    assert mine.status_code == 200


def test_job_status_requires_login(client):
    resp = client.get("/api/scores/jobs/anything")
    assert resp.status_code == 401


# --- jobs list -----------------------------------------------------------


def test_jobs_list_returns_only_callers_jobs(
    auth_client, second_auth_client, noop_submit, monkeypatch
):
    _install_fake_omr(monkeypatch, xml_bytes=simple_score_bytes())
    _upload_pdf(auth_client, "mine.pdf")
    _upload_pdf(second_auth_client, "theirs.pdf")

    resp = auth_client.get("/api/scores/jobs")
    assert resp.status_code == 200
    body = resp.get_json()
    filenames = {item["filename"] for item in body["items"]}
    assert filenames == {"mine.pdf"}


def test_jobs_list_newest_first_and_shape(auth_client, sync_jobs, monkeypatch):
    _install_fake_omr(monkeypatch, xml_bytes=simple_score_bytes())
    _upload_pdf(auth_client, "first.pdf")
    _upload_pdf(auth_client, "second.pdf")

    resp = auth_client.get("/api/scores/jobs")
    body = resp.get_json()
    assert [item["filename"] for item in body["items"]] == ["second.pdf", "first.pdf"]
    for item in body["items"]:
        assert set(item) == {
            "id",
            "status",
            "filename",
            "score_id",
            "error_code",
            "error_message",
            "warnings",
            "created_at",
            "updated_at",
        }


def test_jobs_list_route_not_shadowed_by_score_detail_route(auth_client):
    # GET /api/scores/jobs must resolve to the jobs-list endpoint, not be
    # captured by GET /api/scores/<score_id> with "jobs" as the id (which
    # would 404 as SCORE_NOT_FOUND instead of returning an empty list).
    resp = auth_client.get("/api/scores/jobs")
    assert resp.status_code == 200
    assert resp.get_json() == {"items": []}


# --- per-user unfinished-job cap ------------------------------------------


def test_fourth_unfinished_job_is_refused_with_429(auth_client, noop_submit, monkeypatch):
    _install_fake_omr(monkeypatch, xml_bytes=simple_score_bytes())

    for i in range(3):
        resp = _upload_pdf(auth_client, f"scan{i}.pdf")
        assert resp.status_code == 202, resp.get_json()

    resp = _upload_pdf(auth_client, "scan4.pdf")
    assert resp.status_code == 429
    assert resp.get_json()["error"] == "TOO_MANY_CONVERSIONS"

    with db_module.session_scope() as db_session:
        assert db_session.query(models.ConversionJob).count() == 3


# --- reconcile_interrupted_jobs -------------------------------------------


def test_reconcile_interrupted_jobs_fails_stranded_running_job(auth_client, app):
    with db_module.session_scope() as db_session:
        user = db_session.query(models.User).first()
        job = models.ConversionJob(
            user_id=user.id, filename="stuck.pdf", status="running"
        )
        db_session.add(job)
        db_session.flush()
        job_id = job.id

    conversion.stage_pdf(job_id, b"%PDF-1.4 orphaned staged bytes")
    assert conversion.pending_pdf_path(job_id).exists()

    conversion.reconcile_interrupted_jobs()

    row = _get_job_row(job_id)
    assert row.status == "failed"
    assert row.error_code == "SERVER_RESTARTED"
    assert row.error_message
    assert not conversion.pending_pdf_path(job_id).exists()


def test_reconcile_interrupted_jobs_leaves_terminal_jobs_alone(auth_client):
    with db_module.session_scope() as db_session:
        user = db_session.query(models.User).first()
        job = models.ConversionJob(
            user_id=user.id,
            filename="done.pdf",
            status="succeeded",
            score_id="abc123",
        )
        db_session.add(job)
        db_session.flush()
        job_id = job.id

    conversion.reconcile_interrupted_jobs()

    row = _get_job_row(job_id)
    assert row.status == "succeeded"
    assert row.error_code is None


# --- non-PDF upload unaffected -------------------------------------------


def test_non_pdf_upload_still_returns_201_synchronously(auth_client):
    resp = auth_client.post(
        "/api/scores/upload",
        data={"file": (io.BytesIO(simple_score_bytes()), "score.musicxml")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 201
    body = resp.get_json()
    assert "id" in body
    assert body["from_pdf"] is False

    with db_module.session_scope() as db_session:
        assert db_session.query(models.ConversionJob).count() == 0
