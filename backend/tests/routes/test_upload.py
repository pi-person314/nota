"""Upload pipeline tests: happy path for .musicxml and .mxl, and metadata
extraction correctness (measure count, pickup detection, time signature
map, parts list, display name).
"""

from __future__ import annotations

import io

from fixtures.musicxml_builders import (
    meter_change_score_bytes,
    pickup_score_bytes,
    simple_score_bytes,
    two_part_score_bytes,
    zip_mxl_bytes,
)

from nota import db as db_module
from nota import models


def _upload(client, filename, content):
    return client.post(
        "/api/scores/upload",
        data={"file": (io.BytesIO(content), filename)},
        content_type="multipart/form-data",
    )


def test_upload_requires_login(client):
    resp = _upload(client, "x.musicxml", simple_score_bytes())
    assert resp.status_code == 401


def test_upload_musicxml_happy_path(auth_client):
    resp = _upload(auth_client, "test.musicxml", simple_score_bytes(title="My Piece"))
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["name"] == "My Piece"
    assert body["part_name"] == "Violin"
    assert body["measure_count"] == 1
    assert body["is_starred"] is False
    assert "id" in body
    assert "created_at" in body and "last_opened_at" in body and "last_modified_at" in body


def test_upload_mxl_happy_path(auth_client):
    inner = simple_score_bytes(title="Compressed Piece")
    mxl = zip_mxl_bytes(inner, inner_name="Compressed Piece.musicxml")
    resp = _upload(auth_client, "test.mxl", mxl)
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["name"] == "Compressed Piece"
    assert body["measure_count"] == 1


def test_upload_persists_canonical_musicxml_file(auth_client, app):
    resp = _upload(auth_client, "test.musicxml", simple_score_bytes())
    score_id = resp.get_json()["id"]

    with db_module.session_scope() as session:
        score = session.get(models.Score, score_id)
        file_path = score.file_path

    assert file_path.endswith(".musicxml")
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "<score-partwise" in content


def test_upload_rejects_unsupported_extension(auth_client):
    # .pdf is handled separately (routed through OMR conversion, see
    # tests/routes/test_upload_pdf.py) so this uses an extension that is
    # unsupported outright.
    resp = _upload(auth_client, "not_a_score.docx", b"not a score")
    assert resp.status_code == 422
    assert resp.get_json()["error"] == "UNSUPPORTED_FILE_TYPE"


def test_upload_rejects_oversize_file(auth_client, app):
    cfg = app.config["NOTA_CONFIG"]
    oversized = b"<score-partwise>" + b"a" * (cfg.max_upload_bytes + 1)
    resp = _upload(auth_client, "big.musicxml", oversized)
    assert resp.status_code == 413
    assert resp.get_json()["error"] == "FILE_TOO_LARGE"


def test_upload_no_file_is_422(auth_client):
    resp = auth_client.post("/api/scores/upload", data={}, content_type="multipart/form-data")
    assert resp.status_code == 422
    assert resp.get_json()["error"] == "MISSING_FILE"


def test_upload_extracts_measure_count_and_time_signature_map(auth_client):
    resp = _upload(auth_client, "meter.musicxml", meter_change_score_bytes())
    assert resp.status_code == 201
    score_id = resp.get_json()["id"]

    detail = auth_client.get(f"/api/scores/{score_id}")
    body = detail.get_json()
    assert body["measure_count"] == 3
    assert body["time_signatures"] == [
        {"measure": 1, "ts": "4/4"},
        {"measure": 3, "ts": "3/4"},
    ]


def test_upload_detects_pickup_measure(auth_client):
    resp = _upload(auth_client, "pickup.musicxml", pickup_score_bytes())
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["has_pickup"] is True
    assert body["measure_count"] == 2


def test_upload_no_pickup_measure_is_false(auth_client):
    resp = _upload(auth_client, "simple.musicxml", simple_score_bytes())
    body = resp.get_json()
    assert body["has_pickup"] is False


def test_upload_extracts_parts_list(auth_client):
    resp = _upload(auth_client, "two_part.musicxml", two_part_score_bytes())
    score_id = resp.get_json()["id"]

    detail = auth_client.get(f"/api/scores/{score_id}")
    parts = detail.get_json()["parts"]
    assert len(parts) == 2
    names = {p["name"] for p in parts}
    assert names == {"Violin I", "Violin II"}
    ids = {p["id"] for p in parts}
    assert len(ids) == 2  # each part has a distinct id


def test_upload_display_name_falls_back_to_filename_without_title(auth_client):
    # Hand-written (not music21-generated) so there's no <work-title> or
    # <movement-title> at all — music21's own exporter always injects a
    # placeholder movement-title ("Music21 Fragment") when none is set,
    # which would defeat this test.
    no_title_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="4.0">
  <part-list>
    <score-part id="P1"><part-name>Cello</part-name></score-part>
  </part-list>
  <part id="P1">
    <measure number="1">
      <attributes>
        <divisions>1</divisions>
        <time><beats>4</beats><beat-type>4</beat-type></time>
      </attributes>
      <note><pitch><step>C</step><octave>3</octave></pitch><duration>4</duration><type>whole</type></note>
    </measure>
  </part>
</score-partwise>
"""

    resp = _upload(auth_client, "untitled_song.musicxml", no_title_xml)
    assert resp.status_code == 201
    assert resp.get_json()["name"] == "untitled_song"
