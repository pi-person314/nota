"""HTTP-level tests for the daily usage quota enforced on
POST /api/scores/:id/command and POST /api/transcribe (nota/quota.py,
wired into nota/routes/commands.py and nota/routes/transcribe.py).

Self-contained like the other test directories: local fixtures build on
`auth_client`/`second_auth_client` from tests/routes/conftest.py (parent
conftest auto-discovery), and reuse the scripted-fake test doubles from
tests/orchestrator/fakes.py and tests/services/fakes.py by plain module
import (both are proper packages under `tests`, so this doesn't need
`pytest_plugins`/relative-import tricks).
"""

from __future__ import annotations

import io

import pytest

from nota import quota as quota_module
from nota.orchestrator import loop as loop_module
from nota.services import whisper as whisper_module

from fixtures.musicxml_builders import simple_score_bytes
from tests.orchestrator.fakes import (
    DirectDispatchDispatcher,
    FakeAnthropicClient,
    fake_response,
    text_block,
)
from tests.services.fakes import FakeOpenAIClient, transcription_result


@pytest.fixture(autouse=True)
def _reset_client_singletons():
    """Guard against test-order pollution of the module-level cached LLM
    clients, matching the equivalent fixtures in tests/orchestrator and
    tests/services.
    """
    loop_module._client = None
    whisper_module._client = None
    yield
    loop_module._client = None
    whisper_module._client = None


@pytest.fixture
def low_command_limit(monkeypatch):
    monkeypatch.setenv("DAILY_COMMAND_LIMIT", "2")


@pytest.fixture
def low_transcribe_limit(monkeypatch):
    monkeypatch.setenv("DAILY_TRANSCRIBE_LIMIT", "2")


@pytest.fixture
def scored_client(auth_client):
    """An authenticated client with one uploaded score. Returns
    (client, score_id).
    """
    resp = auth_client.post(
        "/api/scores/upload",
        data={"file": (io.BytesIO(simple_score_bytes()), "test.musicxml")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 201, resp.get_json()
    return auth_client, resp.get_json()["id"]


@pytest.fixture
def install_fake_anthropic(monkeypatch):
    """Install a scripted fake Anthropic client that always answers with a
    plain text confirmation (no tool calls), and a direct-dispatch tool
    dispatcher (real MCP subprocess never touched). Commands issued
    through this fixture always succeed with 200 as long as quota allows.
    """

    def _install():
        # `run_command` always calls `dispatcher.list_tool_schemas()`, even
        # for a response with no tool_use blocks, so the dispatcher has to
        # be faked too, not just the LLM client.
        monkeypatch.setattr(loop_module, "_get_dispatcher", lambda: DirectDispatchDispatcher())
        fake = FakeAnthropicClient(
            [fake_response(text_block("Done.")) for _ in range(50)]
        )
        monkeypatch.setattr(loop_module, "_get_client", lambda: fake)
        return fake

    return _install


@pytest.fixture
def install_fake_whisper(monkeypatch):
    def _install():
        fake = FakeOpenAIClient(transcription_result("add forte at measure one"))
        monkeypatch.setattr(whisper_module, "_get_client", lambda: fake)
        return fake

    return _install


def _post_audio(client):
    return client.post(
        "/api/transcribe",
        data={"audio": (io.BytesIO(b"fake-audio-bytes"), "recording.webm")},
        content_type="multipart/form-data",
    )


# --- command quota -----------------------------------------------------


def test_commands_within_limit_succeed(low_command_limit, scored_client, install_fake_anthropic):
    client, score_id = scored_client
    install_fake_anthropic()

    for _ in range(2):
        resp = client.post(f"/api/scores/{score_id}/command", json={"text": "add forte"})
        assert resp.status_code == 200


def test_command_over_limit_is_429_and_does_not_increment(
    low_command_limit, scored_client, install_fake_anthropic
):
    client, score_id = scored_client
    install_fake_anthropic()

    for _ in range(2):
        resp = client.post(f"/api/scores/{score_id}/command", json={"text": "add forte"})
        assert resp.status_code == 200

    resp = client.post(f"/api/scores/{score_id}/command", json={"text": "add forte"})
    assert resp.status_code == 429
    body = resp.get_json()
    assert body["error"] == "QUOTA_EXCEEDED"
    assert "2 per day" in body["message"]

    # Denial must not have consumed quota: check the counter row directly.
    from nota import db as db_module
    from nota import models

    with db_module.session_scope() as session:
        rows = session.query(models.UsageCounter).filter_by(kind="command").all()
        assert len(rows) == 1
        assert rows[0].count == 2

    # Raising the limit lets the very next request through -- confirms the
    # denial truly left the counter untouched rather than, say, capping it.
    import os

    os.environ["DAILY_COMMAND_LIMIT"] = "3"
    try:
        resp = client.post(f"/api/scores/{score_id}/command", json={"text": "add forte"})
        assert resp.status_code == 200
    finally:
        os.environ["DAILY_COMMAND_LIMIT"] = "2"


def test_empty_transcript_does_not_consume_quota(low_command_limit, scored_client):
    client, score_id = scored_client
    # No fake LLM client installed -- if quota were checked after this 422
    # short-circuit, no LLM call would happen either way, but we also want
    # to confirm no counter row gets created at all.
    resp = client.post(f"/api/scores/{score_id}/command", json={"text": "a"})
    assert resp.status_code == 422

    from nota import db as db_module
    from nota import models

    with db_module.session_scope() as session:
        rows = session.query(models.UsageCounter).all()
        assert rows == []


def test_command_quota_disabled_when_limit_is_non_positive(
    monkeypatch, scored_client, install_fake_anthropic
):
    monkeypatch.setenv("DAILY_COMMAND_LIMIT", "0")
    client, score_id = scored_client
    install_fake_anthropic()

    for _ in range(5):
        resp = client.post(f"/api/scores/{score_id}/command", json={"text": "add forte"})
        assert resp.status_code == 200


def test_command_quota_is_per_user(low_command_limit, scored_client, second_auth_client, install_fake_anthropic):
    client, score_id = scored_client
    install_fake_anthropic()

    for _ in range(2):
        resp = client.post(f"/api/scores/{score_id}/command", json={"text": "add forte"})
        assert resp.status_code == 200
    resp = client.post(f"/api/scores/{score_id}/command", json={"text": "add forte"})
    assert resp.status_code == 429

    # A second user, unrelated score, is unaffected by the first user's
    # exhausted quota.
    resp2 = second_auth_client.post(
        "/api/scores/upload",
        data={"file": (io.BytesIO(simple_score_bytes()), "other.musicxml")},
        content_type="multipart/form-data",
    )
    assert resp2.status_code == 201
    other_score_id = resp2.get_json()["id"]

    resp3 = second_auth_client.post(
        f"/api/scores/{other_score_id}/command", json={"text": "add forte"}
    )
    assert resp3.status_code == 200


def test_command_quota_is_per_kind(
    low_command_limit, low_transcribe_limit, scored_client, install_fake_anthropic, install_fake_whisper
):
    client, score_id = scored_client
    install_fake_anthropic()
    install_fake_whisper()

    for _ in range(2):
        resp = client.post(f"/api/scores/{score_id}/command", json={"text": "add forte"})
        assert resp.status_code == 200
    resp = client.post(f"/api/scores/{score_id}/command", json={"text": "add forte"})
    assert resp.status_code == 429

    # Command quota being exhausted does not block transcription -- it's a
    # separate counter row (same user, different `kind`).
    resp = _post_audio(client)
    assert resp.status_code == 200


def test_command_quota_resets_at_utc_midnight(low_command_limit, scored_client, install_fake_anthropic, monkeypatch):
    client, score_id = scored_client
    install_fake_anthropic()

    monkeypatch.setattr(quota_module, "_today", lambda: "2020-01-01")
    for _ in range(2):
        resp = client.post(f"/api/scores/{score_id}/command", json={"text": "add forte"})
        assert resp.status_code == 200
    resp = client.post(f"/api/scores/{score_id}/command", json={"text": "add forte"})
    assert resp.status_code == 429

    # A new UTC day: yesterday's exhausted counter must not carry over.
    monkeypatch.setattr(quota_module, "_today", lambda: "2020-01-02")
    resp = client.post(f"/api/scores/{score_id}/command", json={"text": "add forte"})
    assert resp.status_code == 200


# --- transcribe quota ----------------------------------------------------


def test_transcriptions_within_limit_succeed(low_transcribe_limit, auth_client, install_fake_whisper):
    install_fake_whisper()

    for _ in range(2):
        resp = _post_audio(auth_client)
        assert resp.status_code == 200


def test_transcribe_over_limit_is_429_and_does_not_increment(
    low_transcribe_limit, auth_client, install_fake_whisper
):
    install_fake_whisper()

    for _ in range(2):
        resp = _post_audio(auth_client)
        assert resp.status_code == 200

    resp = _post_audio(auth_client)
    assert resp.status_code == 429
    body = resp.get_json()
    assert body["error"] == "QUOTA_EXCEEDED"
    assert "2 per day" in body["message"]

    from nota import db as db_module
    from nota import models

    with db_module.session_scope() as session:
        rows = session.query(models.UsageCounter).filter_by(kind="transcribe").all()
        assert len(rows) == 1
        assert rows[0].count == 2


def test_transcribe_quota_disabled_when_limit_is_non_positive(monkeypatch, auth_client, install_fake_whisper):
    monkeypatch.setenv("DAILY_TRANSCRIBE_LIMIT", "0")
    install_fake_whisper()

    for _ in range(5):
        resp = _post_audio(auth_client)
        assert resp.status_code == 200


def test_transcribe_quota_is_per_user(low_transcribe_limit, auth_client, second_auth_client, install_fake_whisper):
    install_fake_whisper()

    for _ in range(2):
        resp = _post_audio(auth_client)
        assert resp.status_code == 200
    resp = _post_audio(auth_client)
    assert resp.status_code == 429

    resp = _post_audio(second_auth_client)
    assert resp.status_code == 200
