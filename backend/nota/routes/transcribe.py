"""Speech-to-text endpoint: turns a recorded voice command's audio into
text via the Whisper transcription service, ahead of the command
orchestrator (`commands.py`) turning that text into notation edits.
"""

from __future__ import annotations

import os

from flask import Blueprint, jsonify, request

from ..services import whisper
from ._helpers import error_response, login_required

bp = Blueprint("transcribe", __name__, url_prefix="/api")

# Whisper's own per-request upload limit; deliberately separate from
# MAX_UPLOAD_MB (which governs score file uploads and is user-configurable).
MAX_AUDIO_BYTES = 25 * 1024 * 1024


@bp.post("/transcribe")
@login_required
def transcribe():
    audio_file = request.files.get("audio")
    if audio_file is None or not audio_file.filename:
        return error_response(422, "NO_AUDIO", "No audio file was uploaded.")

    audio_file.stream.seek(0, os.SEEK_END)
    size = audio_file.stream.tell()
    audio_file.stream.seek(0)
    if size > MAX_AUDIO_BYTES:
        return error_response(
            413,
            "AUDIO_TOO_LARGE",
            f"Audio exceeds the {MAX_AUDIO_BYTES // (1024 * 1024)} MB limit.",
        )

    try:
        text = whisper.transcribe(audio_file)
    except whisper.STTNotConfigured:
        return error_response(
            503,
            "STT_NOT_CONFIGURED",
            "The transcription service is not configured on this server.",
        )
    except whisper.TranscriptionFailed as exc:
        return error_response(502, "TRANSCRIPTION_FAILED", str(exc))

    return jsonify({"text": text}), 200
