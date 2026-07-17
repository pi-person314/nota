"""Error codes and the internal exception notation tools use to signal a
validation failure before any score mutation or snapshot has happened.

`ToolError` is caught by the per-call harness (see `harness.py`) and turned
into the structured `{"success": false, "error_code": ..., "message": ...}`
response shape. It is never allowed to escape a tool function.
"""

from __future__ import annotations


class ErrorCode:
    """String constants for every machine-readable error a tool can return.

    Kept as plain class attributes (not an Enum) so the values serialize to
    JSON exactly as written here with no extra conversion step.
    """

    SCORE_NOT_FOUND = "SCORE_NOT_FOUND"
    MEASURE_OUT_OF_RANGE = "MEASURE_OUT_OF_RANGE"
    BEAT_OUT_OF_RANGE = "BEAT_OUT_OF_RANGE"
    NO_NOTE_AT_POSITION = "NO_NOTE_AT_POSITION"
    PART_NOT_FOUND = "PART_NOT_FOUND"
    INVALID_ENUM_VALUE = "INVALID_ENUM_VALUE"
    NOTHING_TO_REMOVE = "NOTHING_TO_REMOVE"
    NOTHING_TO_UNDO = "NOTHING_TO_UNDO"
    NOTHING_TO_REDO = "NOTHING_TO_REDO"
    AMBIGUOUS_TARGET = "AMBIGUOUS_TARGET"
    TEXT_REQUIRED = "TEXT_REQUIRED"
    EXPORT_FAILED = "EXPORT_FAILED"


class ToolError(Exception):
    """Raised by validation/resolution helpers to abort a tool call with a
    structured, actionable error. Must always be raised before any mutation
    is applied to the in-memory score or any snapshot is taken.
    """

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message
