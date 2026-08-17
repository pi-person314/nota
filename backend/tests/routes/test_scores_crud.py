"""Score CRUD tests: sort orders, starred filter, get/touch, rename,
delete (file + rows), export headers, and cross-user ownership checks.
"""

from __future__ import annotations

import os
import time

from conftest import upload_score
from fixtures.musicxml_builders import simple_score_bytes

from nota import db as db_module
from nota import models


def test_list_scores_requires_login(client):
    resp = client.get("/api/scores")
    assert resp.status_code == 401


def test_list_scores_empty_for_new_user(auth_client):
    resp = auth_client.get("/api/scores")
    assert resp.status_code == 200
    assert resp.get_json() == []


def test_list_scores_only_returns_summaries(auth_client):
    upload_score(auth_client, content=simple_score_bytes())
    resp = auth_client.get("/api/scores")
    assert resp.status_code == 200
    body = resp.get_json()
    assert len(body) == 1
    assert "musicxml" not in body[0]
    assert "id" in body[0] and "name" in body[0]


def test_list_scores_invalid_sort_is_422(auth_client):
    resp = auth_client.get("/api/scores?sort=bogus")
    assert resp.status_code == 422
    assert resp.get_json()["error"] == "INVALID_SORT"


def test_list_scores_name_asc_and_desc(auth_client):
    upload_score(auth_client, content=simple_score_bytes(title="Beta"))
    upload_score(auth_client, content=simple_score_bytes(title="Alpha"))
    upload_score(auth_client, content=simple_score_bytes(title="Charlie"))

    resp = auth_client.get("/api/scores?sort=name_asc")
    names = [s["name"] for s in resp.get_json()]
    assert names == ["Alpha", "Beta", "Charlie"]

    resp = auth_client.get("/api/scores?sort=name_desc")
    names = [s["name"] for s in resp.get_json()]
    assert names == ["Charlie", "Beta", "Alpha"]


def test_list_scores_date_uploaded_order(auth_client):
    first = upload_score(auth_client, content=simple_score_bytes(title="First"))
    time.sleep(0.05)
    second = upload_score(auth_client, content=simple_score_bytes(title="Second"))

    resp = auth_client.get("/api/scores?sort=date_uploaded")
    ids = [s["id"] for s in resp.get_json()]
    assert ids == [second["id"], first["id"]]  # most recent first


def test_list_scores_last_opened_order_updates_on_get(auth_client):
    first = upload_score(auth_client, content=simple_score_bytes(title="First"))
    second = upload_score(auth_client, content=simple_score_bytes(title="Second"))

    # Re-open the first score; it should now sort ahead of the second.
    time.sleep(0.05)
    auth_client.get(f"/api/scores/{first['id']}")

    resp = auth_client.get("/api/scores?sort=last_opened")
    ids = [s["id"] for s in resp.get_json()]
    assert ids[0] == first["id"]
    assert ids[1] == second["id"]


def test_list_scores_starred_filter(auth_client):
    starred = upload_score(auth_client, content=simple_score_bytes(title="Starred"))
    upload_score(auth_client, content=simple_score_bytes(title="Not Starred"))
    auth_client.patch(f"/api/scores/{starred['id']}", json={"is_starred": True})

    resp = auth_client.get("/api/scores?starred=true")
    body = resp.get_json()
    assert len(body) == 1
    assert body[0]["id"] == starred["id"]
    assert body[0]["is_starred"] is True


def test_get_score_returns_full_musicxml_and_touches_opened(auth_client):
    created = upload_score(auth_client)
    resp = auth_client.get(f"/api/scores/{created['id']}")
    assert resp.status_code == 200
    body = resp.get_json()
    assert "<score-partwise" in body["musicxml"]
    assert body["last_opened_at"] >= created["last_opened_at"]


def test_get_score_not_found_is_404(auth_client):
    resp = auth_client.get("/api/scores/does-not-exist")
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "SCORE_NOT_FOUND"


def test_patch_renames_score(auth_client):
    created = upload_score(auth_client)
    resp = auth_client.patch(f"/api/scores/{created['id']}", json={"name": "New Name"})
    assert resp.status_code == 200
    assert resp.get_json()["name"] == "New Name"

    resp = auth_client.get(f"/api/scores/{created['id']}")
    assert resp.get_json()["name"] == "New Name"


def test_patch_stars_score(auth_client):
    created = upload_score(auth_client)
    resp = auth_client.patch(f"/api/scores/{created['id']}", json={"is_starred": True})
    assert resp.status_code == 200
    assert resp.get_json()["is_starred"] is True


def test_patch_empty_body_is_422(auth_client):
    created = upload_score(auth_client)
    resp = auth_client.patch(f"/api/scores/{created['id']}", json={})
    assert resp.status_code == 422


def test_patch_empty_name_is_422(auth_client):
    created = upload_score(auth_client)
    resp = auth_client.patch(f"/api/scores/{created['id']}", json={"name": "   "})
    assert resp.status_code == 422


def test_patch_not_found_is_404(auth_client):
    resp = auth_client.patch("/api/scores/does-not-exist", json={"name": "x"})
    assert resp.status_code == 404


def test_delete_removes_file_and_row(auth_client, app):
    created = upload_score(auth_client)
    score_id = created["id"]

    with db_module.session_scope() as session:
        file_path = session.get(models.Score, score_id).file_path
    assert os.path.exists(file_path)

    resp = auth_client.delete(f"/api/scores/{score_id}")
    assert resp.status_code == 200

    assert not os.path.exists(file_path)
    with db_module.session_scope() as session:
        assert session.get(models.Score, score_id) is None

    resp = auth_client.get(f"/api/scores/{score_id}")
    assert resp.status_code == 404


def test_delete_not_found_is_404(auth_client):
    resp = auth_client.delete("/api/scores/does-not-exist")
    assert resp.status_code == 404


def test_export_returns_attachment_headers(auth_client):
    created = upload_score(auth_client, content=simple_score_bytes(title="Export Me"))
    resp = auth_client.get(f"/api/scores/{created['id']}/export")
    assert resp.status_code == 200
    disposition = resp.headers.get("Content-Disposition", "")
    assert "attachment" in disposition
    assert "Export Me.musicxml" in disposition
    assert b"<score-partwise" in resp.data


def test_export_not_found_is_404(auth_client):
    resp = auth_client.get("/api/scores/does-not-exist/export")
    assert resp.status_code == 404


# --- Ownership -------------------------------------------------------


def test_second_user_cannot_get_others_score(auth_client, second_auth_client):
    created = upload_score(auth_client)
    resp = second_auth_client.get(f"/api/scores/{created['id']}")
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "FORBIDDEN"


def test_second_user_cannot_patch_others_score(auth_client, second_auth_client):
    created = upload_score(auth_client)
    resp = second_auth_client.patch(f"/api/scores/{created['id']}", json={"name": "Hijacked"})
    assert resp.status_code == 403


def test_second_user_cannot_delete_others_score(auth_client, second_auth_client):
    created = upload_score(auth_client)
    resp = second_auth_client.delete(f"/api/scores/{created['id']}")
    assert resp.status_code == 403

    # Original owner can still access it — nothing was actually deleted.
    resp = auth_client.get(f"/api/scores/{created['id']}")
    assert resp.status_code == 200


def test_second_user_cannot_export_others_score(auth_client, second_auth_client):
    created = upload_score(auth_client)
    resp = second_auth_client.get(f"/api/scores/{created['id']}/export")
    assert resp.status_code == 403


def test_second_user_does_not_see_others_score_in_list(auth_client, second_auth_client):
    upload_score(auth_client)
    resp = second_auth_client.get("/api/scores")
    assert resp.get_json() == []


def test_scores_routes_require_login(client):
    resp = client.get("/api/scores/anything")
    assert resp.status_code == 401
    resp = client.patch("/api/scores/anything", json={"name": "x"})
    assert resp.status_code == 401
    resp = client.delete("/api/scores/anything")
    assert resp.status_code == 401
    resp = client.get("/api/scores/anything/export")
    assert resp.status_code == 401


# --- Thumbnail ---------------------------------------------------------

SAMPLE_SVG = "<svg xmlns=\"http://www.w3.org/2000/svg\"><rect /></svg>"


def test_thumbnail_requires_login(client):
    resp = client.put("/api/scores/anything/thumbnail", json={"svg": SAMPLE_SVG})
    assert resp.status_code == 401
    resp = client.get("/api/scores/anything/thumbnail")
    assert resp.status_code == 401


def test_get_thumbnail_404_before_any_put(auth_client):
    created = upload_score(auth_client)
    resp = auth_client.get(f"/api/scores/{created['id']}/thumbnail")
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "THUMBNAIL_NOT_FOUND"


def test_put_then_get_thumbnail_roundtrip(auth_client):
    created = upload_score(auth_client)
    score_id = created["id"]

    resp = auth_client.put(
        f"/api/scores/{score_id}/thumbnail", json={"svg": SAMPLE_SVG, "page_count": 3}
    )
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True}

    resp = auth_client.get(f"/api/scores/{score_id}/thumbnail")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["svg"] == SAMPLE_SVG
    assert body["page_count"] == 3


def test_put_thumbnail_without_page_count(auth_client):
    created = upload_score(auth_client)
    score_id = created["id"]

    resp = auth_client.put(f"/api/scores/{score_id}/thumbnail", json={"svg": SAMPLE_SVG})
    assert resp.status_code == 200

    resp = auth_client.get(f"/api/scores/{score_id}/thumbnail")
    assert resp.status_code == 200
    assert resp.get_json()["page_count"] is None


def test_has_thumbnail_appears_in_summaries(auth_client):
    created = upload_score(auth_client)
    score_id = created["id"]

    resp = auth_client.get("/api/scores")
    assert resp.get_json()[0]["has_thumbnail"] is False

    resp = auth_client.get(f"/api/scores/{score_id}")
    assert resp.get_json()["has_thumbnail"] is False

    auth_client.put(f"/api/scores/{score_id}/thumbnail", json={"svg": SAMPLE_SVG})

    resp = auth_client.get("/api/scores")
    assert resp.get_json()[0]["has_thumbnail"] is True

    resp = auth_client.get(f"/api/scores/{score_id}")
    assert resp.get_json()["has_thumbnail"] is True


def test_put_thumbnail_not_found_is_404(auth_client):
    resp = auth_client.put("/api/scores/does-not-exist/thumbnail", json={"svg": SAMPLE_SVG})
    assert resp.status_code == 404


def test_put_thumbnail_rejects_empty_svg(auth_client):
    created = upload_score(auth_client)
    resp = auth_client.put(f"/api/scores/{created['id']}/thumbnail", json={"svg": ""})
    assert resp.status_code == 422
    assert resp.get_json()["error"] == "INVALID_THUMBNAIL"


def test_put_thumbnail_rejects_non_svg_content(auth_client):
    created = upload_score(auth_client)
    resp = auth_client.put(
        f"/api/scores/{created['id']}/thumbnail", json={"svg": "not an svg document"}
    )
    assert resp.status_code == 422
    assert resp.get_json()["error"] == "INVALID_THUMBNAIL"


def test_put_thumbnail_rejects_too_large_svg(auth_client):
    created = upload_score(auth_client)
    huge = "<svg>" + ("x" * 2_000_001)
    resp = auth_client.put(f"/api/scores/{created['id']}/thumbnail", json={"svg": huge})
    assert resp.status_code == 413
    assert resp.get_json()["error"] == "THUMBNAIL_TOO_LARGE"


def test_put_thumbnail_rejects_invalid_page_count(auth_client):
    created = upload_score(auth_client)
    resp = auth_client.put(
        f"/api/scores/{created['id']}/thumbnail",
        json={"svg": SAMPLE_SVG, "page_count": 0},
    )
    assert resp.status_code == 422
    assert resp.get_json()["error"] == "INVALID_THUMBNAIL"

    resp = auth_client.put(
        f"/api/scores/{created['id']}/thumbnail",
        json={"svg": SAMPLE_SVG, "page_count": "3"},
    )
    assert resp.status_code == 422
    assert resp.get_json()["error"] == "INVALID_THUMBNAIL"


def test_second_user_cannot_put_thumbnail_on_others_score(auth_client, second_auth_client):
    created = upload_score(auth_client)
    resp = second_auth_client.put(
        f"/api/scores/{created['id']}/thumbnail", json={"svg": SAMPLE_SVG}
    )
    assert resp.status_code == 403


def test_second_user_cannot_get_thumbnail_on_others_score(auth_client, second_auth_client):
    created = upload_score(auth_client)
    auth_client.put(f"/api/scores/{created['id']}/thumbnail", json={"svg": SAMPLE_SVG})
    resp = second_auth_client.get(f"/api/scores/{created['id']}/thumbnail")
    assert resp.status_code == 403


def test_delete_score_removes_thumbnail(auth_client):
    created = upload_score(auth_client)
    score_id = created["id"]
    auth_client.put(f"/api/scores/{score_id}/thumbnail", json={"svg": SAMPLE_SVG})

    resp = auth_client.delete(f"/api/scores/{score_id}")
    assert resp.status_code == 200

    resp = auth_client.get(f"/api/scores/{score_id}/thumbnail")
    assert resp.status_code == 404
