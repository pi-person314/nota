"""HTTP-level tests for /api/scores/:id/command, /undo, /redo, and
/history (nota/routes/commands.py).
"""

from __future__ import annotations

import threading

from nota.orchestrator import locks

from .fakes import fake_response, text_block, tool_use_block


def test_empty_transcript_is_rejected_before_any_llm_call(scored_client):
    client, score_id = scored_client
    # No fake client installed at all -- if the route tried to call Claude
    # it would hit the real (unconfigured) client and 503 instead of 422.
    resp = client.post(f"/api/scores/{score_id}/command", json={"text": "a"})

    assert resp.status_code == 422
    assert resp.get_json()["error"] == "EMPTY_TRANSCRIPT"


def test_whitespace_only_transcript_is_rejected(scored_client):
    client, score_id = scored_client
    resp = client.post(f"/api/scores/{score_id}/command", json={"text": "   "})

    assert resp.status_code == 422
    assert resp.get_json()["error"] == "EMPTY_TRANSCRIPT"


def test_command_without_configured_llm_returns_503(scored_client, monkeypatch):
    client, score_id = scored_client
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    resp = client.post(f"/api/scores/{score_id}/command", json={"text": "add forte at measure one"})

    assert resp.status_code == 503
    assert resp.get_json()["error"] == "LLM_NOT_CONFIGURED"


def test_successful_command_returns_full_contract(scored_client, install_fake_client, install_direct_dispatcher):
    client, score_id = scored_client
    install_direct_dispatcher()
    install_fake_client(
        [
            fake_response(tool_use_block("toolu_1", "add_dynamic", {"measure": 1, "beat": 1, "dynamic": "f"})),
            fake_response(text_block("Added forte at measure 1.")),
        ]
    )

    resp = client.post(f"/api/scores/{score_id}/command", json={"text": "add forte at measure one"})

    assert resp.status_code == 200
    body = resp.get_json()
    assert set(body) == {
        "musicxml",
        "changed_element_ids",
        "confirmation",
        "tools_called",
        "needs_clarification",
    }
    assert body["tools_called"] == ["add_dynamic"]
    assert body["changed_element_ids"]
    assert body["confirmation"] == "Added forte at measure 1."
    assert body["needs_clarification"] is False

    history_resp = client.get(f"/api/scores/{score_id}/history")
    assert history_resp.status_code == 200
    items = history_resp.get_json()["items"]
    assert len(items) == 1
    assert items[0]["transcript"] == "add forte at measure one"
    assert items[0]["tools_called"] == ["add_dynamic"]
    assert items[0]["confirmation"] == "Added forte at measure 1."


def test_command_on_missing_score_is_404(auth_client):
    resp = auth_client.post("/api/scores/does-not-exist/command", json={"text": "add forte"})
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "SCORE_NOT_FOUND"


def test_command_on_someone_elses_score_is_403(scored_client, second_auth_client):
    _owner_client, score_id = scored_client
    resp = second_auth_client.post(f"/api/scores/{score_id}/command", json={"text": "add forte"})
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "FORBIDDEN"


def test_undo_endpoint_with_nothing_to_undo(scored_client):
    client, score_id = scored_client
    resp = client.post(f"/api/scores/{score_id}/undo")
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "NOTHING_TO_UNDO"


def test_redo_endpoint_with_nothing_to_redo(scored_client):
    client, score_id = scored_client
    resp = client.post(f"/api/scores/{score_id}/redo")
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "NOTHING_TO_REDO"


def test_undo_and_redo_endpoints_are_deterministic_and_llm_free(
    scored_client, install_direct_dispatcher
):
    client, score_id = scored_client
    dispatcher = install_direct_dispatcher()
    # Mutate directly through the tool layer (no LLM involved) so the
    # score has something to undo.
    result = dispatcher.call_tool("add_dynamic", {"score_id": score_id, "measure": 1, "beat": 1, "dynamic": "f"})
    assert result["success"] is True
    dynamic_id = result["changed_element_ids"][0]

    undo_resp = client.post(f"/api/scores/{score_id}/undo")
    assert undo_resp.status_code == 200
    undo_body = undo_resp.get_json()
    assert undo_body["summary"].startswith("Undid: add_dynamic")
    assert undo_body["changed_element_ids"] == []
    assert f'id="{dynamic_id}"' not in undo_body["musicxml"]

    redo_resp = client.post(f"/api/scores/{score_id}/redo")
    assert redo_resp.status_code == 200
    redo_body = redo_resp.get_json()
    assert redo_body["summary"].startswith("Redid: add_dynamic")
    assert f'id="{dynamic_id}"' in redo_body["musicxml"]


def test_undo_on_someone_elses_score_is_403(scored_client, second_auth_client):
    _owner_client, score_id = scored_client
    resp = second_auth_client.post(f"/api/scores/{score_id}/undo")
    assert resp.status_code == 403


def test_history_endpoint_empty_for_fresh_score(scored_client):
    client, score_id = scored_client
    resp = client.get(f"/api/scores/{score_id}/history")
    assert resp.status_code == 200
    assert resp.get_json() == {"items": []}


def test_history_endpoint_returns_commands_oldest_first(
    scored_client, install_fake_client, install_direct_dispatcher
):
    client, score_id = scored_client
    install_direct_dispatcher()
    install_fake_client(
        [
            fake_response(tool_use_block("toolu_1", "add_dynamic", {"measure": 1, "beat": 1, "dynamic": "f"})),
            fake_response(text_block("Added forte at measure 1.")),
            fake_response(tool_use_block("toolu_2", "add_dynamic", {"measure": 2, "beat": 1, "dynamic": "p"})),
            fake_response(text_block("Added piano at measure 2.")),
        ]
    )

    client.post(f"/api/scores/{score_id}/command", json={"text": "add forte at measure one"})
    client.post(f"/api/scores/{score_id}/command", json={"text": "add piano at measure two"})

    items = client.get(f"/api/scores/{score_id}/history").get_json()["items"]

    assert [item["transcript"] for item in items] == [
        "add forte at measure one",
        "add piano at measure two",
    ]
    assert [item["id"] for item in items] == sorted(item["id"] for item in items)


def test_history_endpoint_requires_ownership(scored_client, second_auth_client):
    _owner_client, score_id = scored_client
    resp = second_auth_client.get(f"/api/scores/{score_id}/history")
    assert resp.status_code == 403


def test_second_concurrent_command_gets_409(scored_client, monkeypatch):
    """With the score lock already held, a second request must fail fast
    with COMMAND_IN_PROGRESS rather than blocking for the real 15s budget.
    """
    import nota.routes.commands as commands_module

    monkeypatch.setattr(commands_module, "COMMAND_LOCK_TIMEOUT", 0.3)

    client, score_id = scored_client

    holder_ready = threading.Event()
    release_holder = threading.Event()

    def hold_lock():
        with locks.score_lock(score_id, timeout=5.0):
            holder_ready.set()
            release_holder.wait(timeout=5.0)

    t = threading.Thread(target=hold_lock)
    t.start()
    try:
        holder_ready.wait(timeout=5.0)
        resp = client.post(f"/api/scores/{score_id}/command", json={"text": "add forte at measure one"})
        assert resp.status_code == 409
        assert resp.get_json()["error"] == "COMMAND_IN_PROGRESS"
    finally:
        release_holder.set()
        t.join()
