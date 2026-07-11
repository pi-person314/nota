"""Builds the Claude system prompt for one command, fresh per request from
the target score's stored metadata (name, measure count, parts, time
signatures). Nothing here is cached across requests — the metadata is cheap
to read off the Score row, and a stale prompt (wrong measure count after a
prior command) would be worse than the cost of rebuilding it every time.
"""

from __future__ import annotations

import json

from .. import models

RULES = """RULES:
1. Prefer acting over asking. Call a tool whenever the command specifies a
   location and a marking; ask a brief clarifying question only when the
   location or marking is genuinely ambiguous or missing.
2. Accept standard synonyms: bar = measure, cresc = crescendo,
   dim/decresc = decrescendo, stacc = staccato, marc = marcato.
3. Validate measure references against the score metadata above yourself,
   without calling a tool to check. If the user references a measure
   outside the score's range, don't call a tool — tell them briefly instead.
4. A compound command needs multiple tool calls. A range command (e.g.
   "staccato in bars 8 through 12") is a single ranged tool call, not one
   call per note.
5. If a beat is given with no measure, use the most recently mentioned
   measure from the conversation.
6. Phrases like "undo", "go back", or "never mind" mean: call the undo tool.
   "redo" or "put that back" means: call the redo tool.
7. If a tool call returns an error, relay the useful part of it
   conversationally (e.g. "That measure only has 3 beats — did you mean
   beat 3?") rather than repeating the raw error code.
8. Always end your turn with exactly one short spoken confirmation, e.g.
   "Added forte at measure 12." It will be read aloud by text-to-speech, so
   keep it brief and natural to say out loud."""


def _format_parts(parts: list[dict]) -> str:
    if not parts:
        return "single part (unspecified)"
    names = [p.get("name") or p.get("id") or "?" for p in parts]
    return ", ".join(names)


def _format_time_signatures(time_signatures: list[dict]) -> str:
    if not time_signatures:
        return "not recorded"
    pieces = []
    for entry in time_signatures:
        measure = entry.get("measure")
        ts = entry.get("ts")
        pieces.append(f"{ts} from measure {measure}")
    return "; ".join(pieces)


def build_system_prompt(score: models.Score) -> str:
    """Build the full system prompt for a command against `score`.

    `score` is expected to be a live or detached-but-loaded `Score` row
    (its JSON metadata columns are parsed here, not by the caller).
    """
    try:
        parts = json.loads(score.parts_json) if score.parts_json else []
    except (TypeError, ValueError):
        parts = []
    try:
        time_signatures = json.loads(score.time_signatures_json) if score.time_signatures_json else []
    except (TypeError, ValueError):
        time_signatures = []

    pickup_note = " (plus a pickup measure, numbered 0)" if score.has_pickup else ""

    identity = (
        "You are Nota, a voice-driven music notation assistant for orchestral musicians."
    )

    score_block = (
        "CURRENT SCORE:\n"
        f"- Title: {score.name}\n"
        f"- Parts: {_format_parts(parts)}\n"
        f"- Measures: {score.measure_count}{pickup_note}\n"
        f"- Time signatures: {_format_time_signatures(time_signatures)}"
    )

    artifact_note = (
        "Commands come from speech-to-text and may contain transcription "
        'artifacts ("sfor zando" = sforzando, "measure to" may mean "measure 2").'
    )

    return "\n\n".join([identity, score_block, artifact_note, RULES])
