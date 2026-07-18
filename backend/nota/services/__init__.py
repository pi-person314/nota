"""Backend services: integrations with external APIs (transcription, OMR,
etc.) behind a small typed-exception interface so route modules never need
to know about a particular SDK's exception hierarchy, plus in-process
services like `score_cache` that don't wrap anything external but belong
alongside them rather than in a route or storage module.
"""

from __future__ import annotations
