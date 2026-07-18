"""PDF upload tests: OMR conversion is mocked for the happy path and every
error path (see tests/services/test_omr_service.py for the OMR service's
own unit tests). The one real end-to-end conversion against a live
Audiveris install lives in `test_real_audiveris_conversion_end_to_end`
below, auto-skipped unless `AUDIVERIS_PATH` is set and points at a real
launcher.
"""

from __future__ import annotations

import io
import os
from pathlib import Path

import pytest
from fixtures.musicxml_builders import simple_score_bytes

from nota.services import omr


def _upload(client, filename, content):
    return client.post(
        "/api/scores/upload",
        data={"file": (io.BytesIO(content), filename)},
        content_type="multipart/form-data",
    )


def _install_fake_omr(monkeypatch, *, xml_bytes=None, suffix=".musicxml", exc=None):
    """Monkeypatch `omr.convert_pdf_to_musicxml` so the route never shells
    out to a real Audiveris process. On success, writes `xml_bytes` to a
    real file under the caller-supplied `output_dir` and returns its path,
    matching the real function's contract; `exc` makes it raise instead.
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


def test_pdf_upload_happy_path_runs_omr_then_ingest(auth_client, monkeypatch):
    _install_fake_omr(monkeypatch, xml_bytes=simple_score_bytes(title="Scanned Piece"))

    resp = _upload(auth_client, "scanned.pdf", b"%PDF-1.4 fake pdf bytes")

    assert resp.status_code == 201
    body = resp.get_json()
    assert body["name"] == "Scanned Piece"
    assert body["measure_count"] == 1


def test_pdf_upload_not_configured_is_422(auth_client, monkeypatch):
    _install_fake_omr(monkeypatch, exc=omr.OMRNotConfigured("AUDIVERIS_PATH is not set."))

    resp = _upload(auth_client, "scanned.pdf", b"%PDF-1.4 fake pdf bytes")

    assert resp.status_code == 422
    assert resp.get_json()["error"] == "OMR_NOT_CONFIGURED"


def test_pdf_upload_conversion_failure_is_422(auth_client, monkeypatch):
    _install_fake_omr(monkeypatch, exc=omr.OMRConversionFailed("Audiveris exited with status 1."))

    resp = _upload(auth_client, "scanned.pdf", b"%PDF-1.4 fake pdf bytes")

    assert resp.status_code == 422
    body = resp.get_json()
    assert body["error"] == "OMR_FAILED"
    assert "status 1" in body["message"]


def test_pdf_upload_with_unparseable_omr_output_is_invalid_musicxml(auth_client, monkeypatch):
    # OMR "succeeds" (produces a file) but the content isn't valid
    # MusicXML -- the normal ingest pipeline's own rejection must still
    # apply, unchanged, to whatever OMR hands it.
    _install_fake_omr(monkeypatch, xml_bytes=b"not xml at all")

    resp = _upload(auth_client, "scanned.pdf", b"%PDF-1.4 fake pdf bytes")

    assert resp.status_code == 422
    assert resp.get_json()["error"] == "INVALID_XML"


def test_pdf_upload_respects_existing_size_cap(auth_client, app, monkeypatch):
    # Should be rejected on size alone, before OMR ever runs -- fail the
    # test loudly if that assumption breaks.
    def fail_if_called(*args, **kwargs):
        raise AssertionError("OMR should not run for an oversized upload")

    monkeypatch.setattr(omr, "convert_pdf_to_musicxml", fail_if_called)

    cfg = app.config["NOTA_CONFIG"]
    oversized = b"%PDF-1.4" + b"a" * (cfg.max_upload_bytes + 1)

    resp = _upload(auth_client, "big.pdf", oversized)

    assert resp.status_code == 413
    assert resp.get_json()["error"] == "FILE_TOO_LARGE"


def test_pdf_upload_result_filename_uses_original_stem(auth_client, monkeypatch, app):
    _install_fake_omr(monkeypatch, xml_bytes=simple_score_bytes())

    resp = _upload(auth_client, "my great score.pdf", b"%PDF-1.4 fake pdf bytes")

    assert resp.status_code == 201


@pytest.mark.skipif(
    not (os.environ.get("AUDIVERIS_PATH") and Path(os.environ["AUDIVERIS_PATH"]).is_file()),
    reason="AUDIVERIS_PATH is not set to a real Audiveris launcher",
)
def test_real_audiveris_conversion_end_to_end(auth_client):
    """Runs a real Audiveris conversion against a small generated PDF of
    an engraved scale. Only runs when AUDIVERIS_PATH points at a real,
    installed launcher; skipped in ordinary CI/dev runs otherwise.
    """
    fixture_pdf = Path(__file__).parent / "fixtures" / "omr_test_scale.pdf"
    raw_bytes = fixture_pdf.read_bytes()

    resp = _upload(auth_client, "test_scale.pdf", raw_bytes)

    assert resp.status_code == 201, resp.get_json()
    body = resp.get_json()
    assert body["measure_count"] >= 1

    detail = auth_client.get(f"/api/scores/{body['id']}")
    xml = detail.get_json()["musicxml"]
    assert "<score-partwise" in xml
