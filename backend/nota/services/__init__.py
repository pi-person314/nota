"""Backend service integrations that wrap external APIs (transcription,
etc.) behind a small typed-exception interface, so route modules never
need to know about a particular SDK's exception hierarchy.
"""

from __future__ import annotations
