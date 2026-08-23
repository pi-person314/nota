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
5. A follow-up command may reference an earlier one without restating the
   marking — a bare beat or measure number, or a phrase like "again",
   "same thing", "do that again". In that case, reuse the marking (and
   tool) from the most recently matching command in the conversation, but
   call the tool exactly once, at the newly stated location only. If only
   a beat is given with no measure, keep the most recently mentioned
   measure.
6. Conversation history is there to resolve references like those in rule
   5 — it is not a list of pending work. Call a tool only for what the
   CURRENT command asks for; never re-issue a tool call for a command an
   earlier turn already completed, even if the current command is unclear.
7. Phrases like "undo", "go back", or "never mind" mean: call the undo tool.
   "redo" or "put that back" means: call the redo tool.
8. If a tool call returns an error, relay the useful part of it
   conversationally (e.g. "That measure only has 3 beats — did you mean
   beat 3?") rather than repeating the raw error code.
9. Note edits: add_note writes over whatever occupies that position (use
   it for "add/put a C on beat 3"); delete_note replaces notes with rests
   (use it for "delete the note" and also "put a rest on beat 2");
   change_pitch keeps the rhythm and changes only the pitch; set_duration
   keeps the pitch and changes only the length. When the user names a
   pitch without an octave, pass it without one — the tools pick the
   nearest octave automatically, so never ask which octave they mean.
10. A command that names a note by its current pitch with no beat ("change
   the F in bar 3 to F sharp") is a change_pitch call with from_pitch —
   don't guess a beat.
11. Rests cannot be removed or targeted by any tool — nothing shifts in
   engraved music, so "remove/delete the rest" really means either
   lengthening the note before it (set_duration) or putting a note in its
   place (add_note). Ask which one the user wants if it isn't clear.
   Never call delete_note on a rest's position — it deletes notes — and
   when a tool error lists the beats where notes start, those are note
   positions, not rest positions.
12. Always end your turn with exactly one short spoken confirmation, e.g.
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
        "artifacts. Resolve these yourself instead of asking about them: "
        "numbers are often mis-transcribed as similar-sounding words "
        '(e.g. "won" = one, "to"/"too" = two, "free" = three, "for" = '
        "four — \"th\" sounds are a common misrecognition for \"f\"); a "
        "letter used as a rehearsal-mark label may come through as the "
        'word for that letter (e.g. "sea" = C, "bee" = B, "are" = R) — '
        "rehearsal marks are conventionally a single capital letter, so "
        "convert the word back to its letter; and a marking name may be "
        'split or garbled ("sfor zando" = sforzando, "for tay" = forte). '
        "When a garbled marking could match more than one term, prefer "
        'the simplest standard one (e.g. plain "f" for forte) rather '
        "than a more elaborate one (e.g. \"fp\") unless the words clearly "
        "spell out the elaborate version. Treat a word or short phrase as "
        "filler — not a second marking — unless it is a clear match (a "
        "known term or one of the standard synonyms above) to a specific "
        "articulation, dynamic, or ornament; a loose or partial phonetic "
        "resemblance is not enough to justify calling an extra tool."
    )

    return "\n\n".join([identity, score_block, artifact_note, RULES])
