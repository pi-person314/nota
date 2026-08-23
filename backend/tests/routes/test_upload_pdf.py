"""PDF upload cases not covered by the background-job pipeline tests.

PDF conversion runs as a background job, so the bulk of PDF coverage —
queueing, job status/list endpoints, every OMR and ingest failure code,
the quality gate, and cleanup — lives in `test_conversion_jobs.py`. What
remains here is the handful of cases specific to the upload request
itself: an awkward filename surviving the round trip, native MusicXML
uploads staying free of OMR-only response fields, and the one real
end-to-end conversion against a live Audiveris install (auto-skipped
unless `AUDIVERIS_PATH` points at a real launcher).
"""

from __future__ import annotations

import io
import os
from pathlib import Path

import pytest
from fixtures.musicxml_builders import omr_clean_score_bytes, simple_score_bytes

from nota import conversion
from nota.services import omr


def _upload(client, filename, content):
    return client.post(
        "/api/scores/upload",
        data={"file": (io.BytesIO(content), filename)},
        content_type="multipart/form-data",
    )


@pytest.fixture
def configured_omr(monkeypatch, tmp_path):
    """Point AUDIVERIS_PATH at a real (if fake-content) file so the
    upload route's "is OMR configured" fast-fail check passes and the
    request reaches the queueing logic.
    """
    launcher = tmp_path / "Audiveris.exe"
    launcher.write_text("fake launcher")
    monkeypatch.setenv("AUDIVERIS_PATH", str(launcher))
    return launcher


@pytest.fixture
def sync_jobs(monkeypatch):
    """Run every submitted job synchronously, in the request thread."""
    monkeypatch.setattr(conversion, "submit_job", lambda job_id: conversion.run_job(job_id))


def _install_fake_omr(monkeypatch, xml_bytes):
    def fake_convert(pdf_path, output_dir, *, timeout_s=omr.DEFAULT_TIMEOUT_S):
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        produced = output_dir / "converted.musicxml"
        produced.write_bytes(xml_bytes)
        return produced

    monkeypatch.setattr(omr, "convert_pdf_to_musicxml", fake_convert)


def test_pdf_upload_with_spaces_in_filename_converts_cleanly(
    auth_client, configured_omr, sync_jobs, monkeypatch
):
    # Spaces and mixed case in the original name have to survive being
    # staged to disk and handed to the converter.
    _install_fake_omr(monkeypatch, omr_clean_score_bytes())

    resp = _upload(auth_client, "My Great Score.pdf", b"%PDF-1.4 fake pdf bytes")
    assert resp.status_code == 202
    body = resp.get_json()
    assert body["filename"] == "My Great Score.pdf"

    status = auth_client.get(f"/api/scores/jobs/{body['job_id']}").get_json()
    assert status["status"] == "succeeded", status
    assert status["score_id"]


def test_native_musicxml_upload_has_no_omr_warnings_key(auth_client):
    resp = auth_client.post(
        "/api/scores/upload",
        data={"file": (io.BytesIO(simple_score_bytes()), "score.musicxml")},
        content_type="multipart/form-data",
    )

    assert resp.status_code == 201
    assert "omr_warnings" not in resp.get_json()


@pytest.mark.skipif(
    not (os.environ.get("AUDIVERIS_PATH") and Path(os.environ["AUDIVERIS_PATH"]).is_file()),
    reason="AUDIVERIS_PATH is not set to a real Audiveris launcher",
)
def test_real_audiveris_conversion_end_to_end(auth_client, sync_jobs):
    """Runs a real Audiveris conversion against a small generated PDF of
    an engraved scale. Only runs when AUDIVERIS_PATH points at a real,
    installed launcher; skipped in ordinary CI/dev runs otherwise.

    The job is run synchronously here so the conversion's outcome is
    observable without polling a background thread.
    """
    fixture_pdf = Path(__file__).parent / "fixtures" / "omr_test_scale.pdf"
    raw_bytes = fixture_pdf.read_bytes()

    resp = _upload(auth_client, "test_scale.pdf", raw_bytes)
    assert resp.status_code == 202, resp.get_json()

    status = auth_client.get(f"/api/scores/jobs/{resp.get_json()['job_id']}").get_json()
    assert status["status"] == "succeeded", status

    detail = auth_client.get(f"/api/scores/{status['score_id']}").get_json()
    assert detail["measure_count"] >= 1
    assert "<score-partwise" in detail["musicxml"]
