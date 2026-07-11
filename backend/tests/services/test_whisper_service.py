"""Unit tests for `nota.services.whisper.transcribe`.

The OpenAI client is always a scripted fake (`fakes.FakeOpenAIClient`); no
test in this file makes a real network call.
"""

from __future__ import annotations

import io

import httpx
import pytest
from openai import APIConnectionError, APIStatusError, APITimeoutError
from werkzeug.datastructures import FileStorage

from nota.services import whisper

from .fakes import transcription_result


def _dummy_request() -> httpx.Request:
    return httpx.Request("POST", "https://api.openai.com/v1/audio/transcriptions")


def _audio_file(data: bytes = b"fake-audio-bytes", filename: str = "recording.webm") -> FileStorage:
    return FileStorage(stream=io.BytesIO(data), filename=filename, content_type="audio/webm")


def test_transcribe_returns_text_and_uses_lexicon_prompt(install_fake_client):
    fake = install_fake_client(transcription_result("add forte at measure twelve"))

    text = whisper.transcribe(_audio_file())

    assert text == "add forte at measure twelve"
    assert len(fake.audio.transcriptions.calls) == 1
    call = fake.audio.transcriptions.calls[0]
    assert call["model"] == "whisper-1"
    assert call["prompt"] == whisper.LEXICON_PROMPT
    assert call["language"] == "en"
    # File is passed as (filename, bytes, content_type) so the SDK sees a
    # real extension for format detection.
    filename, audio_bytes, content_type = call["file"]
    assert filename == "recording.webm"
    assert audio_bytes == b"fake-audio-bytes"
    assert content_type == "audio/webm"
    # Called with a bounded timeout, not the SDK default.
    assert fake.with_options_calls == [{"timeout": whisper.TIMEOUT_SECONDS}]


def test_transcribe_defaults_filename_and_content_type_when_missing(install_fake_client):
    fake = install_fake_client(transcription_result("ok"))
    audio = FileStorage(stream=io.BytesIO(b"data"), filename="", content_type=None)
    # Werkzeug FileStorage falls back to "file" for missing filenames; the
    # service should still supply a sane default if it comes through empty.
    audio.filename = None

    whisper.transcribe(audio)

    filename, _audio_bytes, content_type = fake.audio.transcriptions.calls[0]["file"]
    assert filename == "audio.webm"
    assert content_type == "audio/webm"


def test_transcribe_timeout_raises_transcription_failed(install_fake_client):
    install_fake_client(APITimeoutError(request=_dummy_request()))

    with pytest.raises(whisper.TranscriptionFailed):
        whisper.transcribe(_audio_file())


def test_transcribe_connection_error_raises_transcription_failed(install_fake_client):
    install_fake_client(APIConnectionError(request=_dummy_request()))

    with pytest.raises(whisper.TranscriptionFailed):
        whisper.transcribe(_audio_file())


def test_transcribe_api_status_error_raises_transcription_failed(install_fake_client):
    response = httpx.Response(500, request=_dummy_request(), json={"error": {"message": "boom"}})
    install_fake_client(APIStatusError("boom", response=response, body={"error": {"message": "boom"}}))

    with pytest.raises(whisper.TranscriptionFailed):
        whisper.transcribe(_audio_file())


def test_transcribe_without_configured_key_raises_stt_not_configured(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(whisper.STTNotConfigured):
        whisper.transcribe(_audio_file())
