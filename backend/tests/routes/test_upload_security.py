"""Upload security tests: every malicious or malformed input must come
back as a clean 4xx with the standard error shape, never a 500.
"""

from __future__ import annotations

import io

from fixtures.musicxml_builders import (
    BILLION_LAUGHS_PAYLOAD,
    XXE_PAYLOAD,
    malformed_mxl_missing_container_bytes,
    simple_score_bytes,
    zip_bomb_mxl_bytes,
    zip_mxl_bytes,
)


def _upload(client, filename, content):
    return client.post(
        "/api/scores/upload",
        data={"file": (io.BytesIO(content), filename)},
        content_type="multipart/form-data",
    )


def test_xxe_payload_rejected_as_musicxml(auth_client):
    resp = _upload(auth_client, "evil.musicxml", XXE_PAYLOAD)
    assert resp.status_code == 422
    body = resp.get_json()
    assert "error" in body and "message" in body


def test_xxe_payload_rejected_inside_mxl(auth_client):
    mxl = zip_mxl_bytes(XXE_PAYLOAD, inner_name="evil.musicxml")
    resp = _upload(auth_client, "evil.mxl", mxl)
    assert resp.status_code == 422


def test_billion_laughs_payload_rejected(auth_client):
    resp = _upload(auth_client, "lol.musicxml", BILLION_LAUGHS_PAYLOAD)
    assert resp.status_code == 422
    body = resp.get_json()
    assert "error" in body


def test_zip_bomb_rejected(auth_client):
    resp = _upload(auth_client, "bomb.mxl", zip_bomb_mxl_bytes())
    assert resp.status_code == 422
    assert resp.get_json()["error"] == "ARCHIVE_TOO_LARGE"


def test_malformed_mxl_missing_container_rejected(auth_client):
    bad = malformed_mxl_missing_container_bytes(simple_score_bytes())
    resp = _upload(auth_client, "broken.mxl", bad)
    assert resp.status_code == 422
    assert resp.get_json()["error"] == "MALFORMED_MXL"


def test_mxl_not_actually_a_zip_rejected(auth_client):
    resp = _upload(auth_client, "notazip.mxl", b"this is not a zip file at all")
    assert resp.status_code == 422
    assert resp.get_json()["error"] == "MALFORMED_MXL"


def test_garbage_xml_rejected_cleanly(auth_client):
    resp = _upload(auth_client, "garbage.musicxml", b"<not><valid<<xml")
    assert resp.status_code == 422


def test_empty_file_rejected_cleanly(auth_client):
    resp = _upload(auth_client, "empty.musicxml", b"")
    assert resp.status_code == 422


def test_valid_xml_that_is_not_musicxml_rejected_cleanly(auth_client):
    resp = _upload(
        auth_client,
        "notascore.xml",
        b"<?xml version='1.0'?><totally><unrelated>document</unrelated></totally>",
    )
    assert resp.status_code == 422
