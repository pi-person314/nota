"""HTTP-level tests for POST /api/transcribe (nota/routes/transcribe.py).

The OpenAI client is always a scripted fake (`fakes.FakeOpenAIClient`); no
test in this file makes a real network call.
"""

from __future__ import annotations

import io

import httpx
from openai import APITimeoutError

from nota.routes.transcribe import MAX_AUDIO_BYTES

from .fakes import transcription_result


def _dummy_request() -> httpx.Request:
    return httpx.Request("POST", "https://api.openai.com/v1/audio/transcriptions")


def _post_audio(client, data: bytes = b"fake-audio-bytes", filename: str = "recording.webm"):
    return client.post(
        "/api/transcribe",
        data={"audio": (io.BytesIO(data), filename)},
        content_type="multipart/form-data",
    )


def test_successful_transcription_returns_text(auth_client, install_fake_client):
    install_fake_client(transcription_result("add forte at measure twelve"))

    resp = _post_audio(auth_client)

    assert resp.status_code == 200
    assert resp.get_json() == {"text": "add forte at measure twelve"}


def test_missing_audio_field_is_422(auth_client):
    resp = auth_client.post("/api/transcribe", data={}, content_type="multipart/form-data")

    assert resp.status_code == 422
    assert resp.get_json()["error"] == "NO_AUDIO"


def test_oversize_audio_is_413(auth_client):
    oversize = b"0" * (MAX_AUDIO_BYTES + 1)

    resp = _post_audio(auth_client, data=oversize)

    assert resp.status_code == 413
    assert resp.get_json()["error"] == "AUDIO_TOO_LARGE"


def test_stt_not_configured_is_503(auth_client, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    resp = _post_audio(auth_client)

    assert resp.status_code == 503
    assert resp.get_json()["error"] == "STT_NOT_CONFIGURED"


def test_transcription_failure_is_502(auth_client, install_fake_client):
    install_fake_client(APITimeoutError(request=_dummy_request()))

    resp = _post_audio(auth_client)

    assert resp.status_code == 502
    assert resp.get_json()["error"] == "TRANSCRIPTION_FAILED"


def test_unauthenticated_request_is_401(client):
    resp = _post_audio(client)

    assert resp.status_code == 401
    assert resp.get_json()["error"] == "UNAUTHENTICATED"
