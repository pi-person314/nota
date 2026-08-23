"""Speech-to-text service: wraps the Whisper transcription API with a
musical-vocabulary prompt.

Voice commands are full of terms a general-purpose transcription model
tends to mishear or drop entirely ("crescendo", "sforzando", "pizzicato").
The `prompt` parameter Whisper accepts biases decoding toward whatever
tokens it contains without forcing any particular output, so seeding it
with notation vocabulary is a cheap accuracy win for this domain.
"""

from __future__ import annotations

import os
import threading

import openai

MODEL = "whisper-1"
TIMEOUT_SECONDS = 20.0

LEXICON_PROMPT = (
    "Musical notation commands: measure, bar, beat, crescendo, decrescendo, "
    "diminuendo, sforzando, fortissimo, pianissimo, mezzo forte, mezzo piano, "
    "staccato, staccatissimo, marcato, tenuto, legato, slur, accent, fermata, "
    "trill, mordent, pizzicato, arco, down-bow, up-bow, sul ponticello, "
    "rehearsal mark, ritardando, accelerando, a tempo, hairpin, dolce, "
    "sharp, flat, natural, octave, transpose, semitone, whole step, "
    "whole note, half note, quarter note, eighth note, sixteenth note, "
    "dotted quarter, dotted half, rest, tie, C sharp, B flat."
)

_client_lock = threading.Lock()
_client: openai.OpenAI | None = None


class STTNotConfigured(Exception):
    """Raised when OPENAI_API_KEY is not set in the environment. Callers
    (the /api/transcribe route) should turn this into a clean 503, never a
    crash.
    """


class TranscriptionFailed(Exception):
    """Raised when the transcription request times out or the API returns
    an error. Wraps the underlying SDK exception so callers get a plain
    message without needing to know about SDK-specific exception types.
    """


def _get_client() -> openai.OpenAI:
    """Lazily construct the module-level OpenAI client on first use.

    Kept as a separate function (rather than inlined in `transcribe`) so
    tests can monkeypatch it to return a fake client without touching
    `OPENAI_API_KEY` or the process-wide singleton.
    """
    global _client
    with _client_lock:
        if _client is None:
            if not os.environ.get("OPENAI_API_KEY"):
                raise STTNotConfigured("OPENAI_API_KEY is not set.")
            _client = openai.OpenAI()
        return _client


def transcribe(file_storage) -> str:
    """Transcribe an uploaded audio file to text.

    `file_storage` is a Werkzeug `FileStorage` (e.g. `request.files["audio"]`).
    It is sent to the API as a `(filename, bytes, content_type)` tuple so
    the SDK sees a proper filename extension rather than an anonymous
    stream, which matters for format detection.

    Raises `STTNotConfigured` if no API key is configured, and
    `TranscriptionFailed` if the request times out or the API returns an
    error.
    """
    client = _get_client()

    filename = file_storage.filename or "audio.webm"
    content_type = file_storage.content_type or "audio/webm"
    audio_bytes = file_storage.read()

    try:
        response = client.with_options(timeout=TIMEOUT_SECONDS).audio.transcriptions.create(
            model=MODEL,
            file=(filename, audio_bytes, content_type),
            prompt=LEXICON_PROMPT,
            language="en",
        )
    except openai.APITimeoutError as exc:
        raise TranscriptionFailed("Transcription timed out.") from exc
    except openai.APIConnectionError as exc:
        raise TranscriptionFailed("Could not reach the transcription service.") from exc
    except openai.APIStatusError as exc:
        raise TranscriptionFailed(f"Transcription service returned an error: {exc}") from exc

    return response.text
