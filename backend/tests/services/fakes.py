"""Test doubles for the whisper service test suite: a scripted fake OpenAI
client so tests never make a real API call.
"""

from __future__ import annotations

from types import SimpleNamespace


def transcription_result(text: str) -> SimpleNamespace:
    """A fake `openai.types.audio.Transcription`-shaped object carrying
    only the `.text` field the service actually reads.
    """
    return SimpleNamespace(text=text)


class FakeTranscriptions:
    """Fake `client.audio.transcriptions`. `.create()` returns a scripted
    response (or raises a scripted exception instance) and records the
    call's kwargs for assertions.
    """

    def __init__(self, item):
        self._item = item
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self._item, BaseException):
            raise self._item
        return self._item


class FakeAudio:
    def __init__(self, item):
        self.transcriptions = FakeTranscriptions(item)


class FakeOpenAIClient:
    """Fake `openai.OpenAI()` client good enough to stand in for
    `client.with_options(timeout=...).audio.transcriptions.create(...)`.
    """

    def __init__(self, item):
        self.audio = FakeAudio(item)
        self.with_options_calls: list[dict] = []

    def with_options(self, **kwargs):
        self.with_options_calls.append(kwargs)
        return self
