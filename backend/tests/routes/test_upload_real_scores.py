"""Upload pipeline tests against real scores from the music21-bundled
corpus, rather than small hand-built fixtures — see
`tests/tools/real_score_builders.py` for why real scores are worth testing
separately (they exercise shapes the synthetic fixtures can't).
"""

from __future__ import annotations

from music21 import corpus


def _upload(client, filename, content):
    import io

    return client.post(
        "/api/scores/upload",
        data={"file": (io.BytesIO(content), filename)},
        content_type="multipart/form-data",
    )


def test_upload_rejects_real_score_music21_cannot_reexport(auth_client):
    """Regression test for a real breakage found by parsing every
    bundled-corpus score and re-exporting it: schumann_robert's op. 41
    no. 1, third movement's viola part (measure 32) contains a note whose
    duration resolves to a nested 17-tuplet so short (a "2048th") that
    music21's own MusicXML writer refuses to emit it
    (MusicXMLExportException: 'Cannot convert "2048th" duration to
    MusicXML (too short)'). music21 parses this file just fine — the
    failure only happens on re-export, which `parse_score_metadata` needs
    to do to compute the canonical on-disk XML. Before the fix, this
    exception was uncaught and the upload route surfaced it as a bare
    500; it must come back as a normal rejected-upload response instead.
    """
    mxl_path = corpus.getWork("schumann_robert/opus41no1/movement1")
    raw_bytes = mxl_path.read_bytes()

    resp = _upload(auth_client, "schumann_op41_mvt1.mxl", raw_bytes)

    assert resp.status_code == 422
    body = resp.get_json()
    assert body["error"] == "INVALID_MUSICXML"
    assert "message" in body


def test_upload_real_multipart_pickup_chorale_succeeds(auth_client):
    """Sanity check that a real, well-formed score (a 5-part Bach chorale
    with a pickup measure) still uploads cleanly end to end, to bracket
    the rejection test above: real scores aren't rejected in general, only
    ones music21 genuinely can't round-trip.
    """
    mxl_path = corpus.getWork("bach/bwv1.6")
    raw_bytes = mxl_path.read_bytes()

    resp = _upload(auth_client, "bwv1.6.mxl", raw_bytes)

    assert resp.status_code == 201
    body = resp.get_json()
    assert body["has_pickup"] is True
    assert body["measure_count"] == 21  # counts the pickup as one of the measures, same as upload.py's convention elsewhere

    detail = auth_client.get(f"/api/scores/{body['id']}")
    parts = detail.get_json()["parts"]
    assert len(parts) == 5
