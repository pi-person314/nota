"""Fixtures for the command-orchestrator test suite.

Self-contained: builds its own authenticated-client and score fixtures
rather than importing from tests/routes/conftest.py or
tests/tools/conftest.py, so this directory can run independently. Reuses
the `app`/`client` fixtures from the top-level tests/conftest.py (pytest
auto-discovers parent conftest files), which already wire a fresh
temporary SQLite DB and score storage directory per test through the
normal `create_app` -> `storage.configure` path.
"""

from __future__ import annotations

import io
import json
import os
import uuid

import pytest
from music21 import meter, note, metadata as m21_metadata, stream
from music21.musicxml.m21ToXml import GeneralObjectExporter

from nota import db as db_module
from nota import models
from nota.orchestrator import loop

from .fakes import DirectDispatchDispatcher, FakeAnthropicClient


def _four_measure_musicxml_bytes(title: str = "Test Piece") -> bytes:
    """A single 4/4 part, 4 measures of quarter notes -- enough range for
    "measure 2", "measures 1 through 3", and "measure 12 is out of range"
    style commands.
    """
    s = stream.Score()
    part = stream.Part()
    part.id = "P1"
    part.partName = "Violin"
    pitches = ["C4", "D4", "E4", "F4"]
    for m_num in range(1, 5):
        m = stream.Measure(number=m_num)
        if m_num == 1:
            m.append(meter.TimeSignature("4/4"))
        for p in pitches:
            m.append(note.Note(p, quarterLength=1))
        part.append(m)
    s.insert(0, part)
    s.metadata = m21_metadata.Metadata()
    s.metadata.title = title
    return GeneralObjectExporter(s).parse()


@pytest.fixture(autouse=True)
def _reset_llm_client_singleton():
    """Guard against test-order pollution of `loop`'s module-level cached
    Anthropic client -- most tests monkeypatch `_get_client` directly, but
    the LLM_NOT_CONFIGURED test exercises the real function, which caches
    onto a module global.
    """
    loop._client = None
    yield
    loop._client = None


@pytest.fixture
def signup(client):
    """Factory fixture: signup(name, email, password) -> response JSON.
    Leaves the returned client logged in (session cookie retained by the
    Flask test client across requests).
    """

    def _signup(name="Ada", email="ada@example.com", password="hunter2pass"):
        resp = client.post(
            "/api/auth/signup",
            json={"name": name, "email": email, "password": password},
        )
        assert resp.status_code == 201, resp.get_json()
        return resp.get_json()

    return _signup


@pytest.fixture
def auth_client(client, signup):
    """A test client already logged in as a fresh user."""
    signup()
    return client


@pytest.fixture
def second_auth_client(app, signup):
    """A second, independently-logged-in test client -- for ownership
    tests. Uses its own client instance so its session cookie doesn't
    clobber `auth_client`'s.
    """
    other_client = app.test_client()
    resp = other_client.post(
        "/api/auth/signup",
        json={"name": "Bea", "email": "bea@example.com", "password": "hunter2pass"},
    )
    assert resp.status_code == 201, resp.get_json()
    return other_client


@pytest.fixture
def scored_client(auth_client):
    """An authenticated client with one uploaded 4-measure 4/4 score.
    Returns (client, score_id).
    """
    content = _four_measure_musicxml_bytes()
    resp = auth_client.post(
        "/api/scores/upload",
        data={"file": (io.BytesIO(content), "test.musicxml")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 201, resp.get_json()
    return auth_client, resp.get_json()["id"]


@pytest.fixture
def make_score(app):
    """Factory fixture: make_score() -> score_id. Inserts a User + Score
    row directly (no HTTP round-trip) backed by the same 4-measure 4/4
    fixture `scored_client` uses, for tests that want to call
    `loop.run_command` / tool functions directly rather than through the
    HTTP API.
    """
    cfg = app.config["NOTA_CONFIG"]

    def _make(name: str = "Test Piece") -> str:
        user_id = uuid.uuid4().hex
        score_id = uuid.uuid4().hex
        file_path = os.path.join(cfg.score_storage_dir, f"{score_id}.musicxml")

        with db_module.session_scope() as session:
            session.add(models.User(id=user_id, name="Test User", email=f"{user_id}@example.com"))
            session.add(
                models.Score(
                    id=score_id,
                    user_id=user_id,
                    name=name,
                    file_path=file_path,
                    measure_count=4,
                    has_pickup=False,
                    parts_json=json.dumps([{"id": "P1", "name": "Violin"}]),
                    time_signatures_json=json.dumps([{"measure": 1, "ts": "4/4"}]),
                )
            )

        os.makedirs(cfg.score_storage_dir, exist_ok=True)
        with open(file_path, "wb") as f:
            f.write(_four_measure_musicxml_bytes(name))

        return score_id

    return _make


@pytest.fixture
def install_fake_client(monkeypatch):
    """Factory fixture: install_fake_client([...scripted responses]) ->
    FakeAnthropicClient. Monkeypatches `nota.orchestrator.loop._get_client`
    so `run_command` never touches the real Anthropic API.
    """

    def _install(responses) -> FakeAnthropicClient:
        fake = FakeAnthropicClient(responses)
        monkeypatch.setattr(loop, "_get_client", lambda: fake)
        return fake

    return _install


@pytest.fixture
def install_direct_dispatcher(monkeypatch):
    """Install a DirectDispatchDispatcher (real tool functions, no MCP
    subprocess) as the loop's tool dispatcher.
    """

    def _install() -> DirectDispatchDispatcher:
        fake = DirectDispatchDispatcher()
        monkeypatch.setattr(loop, "_get_dispatcher", lambda: fake)
        return fake

    return _install
