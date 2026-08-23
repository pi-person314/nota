"""Pure helpers for note-level score edits: pitch parsing, octave
placement, duration/interval vocabularies, and carving a time span out of
a measure so a caller can insert new content there.

Nothing in this module is a tool function -- there is no `score_id`
argument and nothing here talks to storage or the undo stack. Future tool
modules (add_note, change_pitch, etc.) import these helpers and wire them
into a `ToolPlan`/`run_tool` planner the same way `location.py`'s helpers
are used by `tools.py` today. Every function here either returns a
resolved value/object or raises a `ToolError` with an actionable message;
none of them mutate a score except `carve_span`, whose job is exactly
that -- and even it never mutates until every raise-check has already
passed (see its docstring).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import music21 as m21

from .errors import ErrorCode, ToolError

_EPSILON = 1e-6


# ---------------------------------------------------------------------------
# Pitch parsing


@dataclass(frozen=True)
class PitchSpec:
    """A parsed, not-yet-octave-resolved pitch: a letter name, a
    semitone alteration (0 = natural, positive = sharp(s), negative =
    flat(s)), and an optional explicit octave (None means "pick the
    nearest octave to some reference" -- see `realize_pitch`).
    """

    step: str
    alter: int
    octave: int | None


# Accidental words recognized after the leading letter, matched against the
# whitespace/hyphen-normalized remainder (so "double-sharp" and "double
# sharp" both match "double sharp"). An empty remainder (bare letter, no
# accidental at all) is natural.
_WORD_ACCIDENTALS: dict[str, int] = {
    "": 0,
    "natural": 0,
    "sharp": 1,
    "flat": -1,
    "double sharp": 2,
    "doublesharp": 2,
    "double flat": -2,
    "doubleflat": -2,
}

# Symbol accidentals, matched with all internal whitespace stripped (so a
# stray space between two symbol characters still matches). "x" is the
# conventional double-sharp symbol; "♮"/"natural" both mean alter 0.
_SYMBOL_ACCIDENTALS: dict[str, int] = {
    "#": 1,
    "♯": 1,
    "b": -1,
    "♭": -1,
    "##": 2,
    "x": 2,
    "♯♯": 2,
    "bb": -2,
    "♭♭": -2,
    "♮": 0,
}

_PITCH_EXAMPLE = "e.g. 'C#4', 'Db5', 'F natural 3', 'b flat'"


def parse_pitch_spec(text: str) -> PitchSpec:
    """Parse a spoken/typed pitch name into a `PitchSpec`.

    A leading letter A-G (case-insensitive) is always read as the note
    letter; everything after it is the accidental (word or symbol form)
    and an optional trailing octave digit. This is a deliberate
    disambiguation rule for the letter B versus the flat symbol "b": "b"
    alone is the note B (nothing follows the letter), "bb" alone is the
    note B with a flat symbol after it (B-flat), and "bbb" is B with a
    double-flat symbol (B-double-flat). The flat symbol is never read
    before a letter has been consumed, so it can never be mistaken for
    the note name itself.

    Accepts, case-insensitively and with flexible whitespace/hyphens
    between the letter, accidental, and octave: bare letters; the words
    "sharp", "flat", "natural", "double sharp"/"double-sharp", "double
    flat"/"double-flat"; the symbols "#", "b", "x", "##", "bb", and the
    unicode symbols "♯", "♭", "♮"; and a trailing octave integer 0-8.

    Raises ToolError(INVALID_PITCH) on anything else.
    """
    if not isinstance(text, str) or not text.strip():
        raise ToolError(
            ErrorCode.INVALID_PITCH,
            f"Pitch cannot be empty. Valid forms look like {_PITCH_EXAMPLE}.",
        )

    raw = text.strip()
    letter_match = re.match(r"^[A-Ga-g]", raw)
    if not letter_match:
        raise ToolError(
            ErrorCode.INVALID_PITCH,
            f"'{text}' does not start with a note letter (A-G). Valid forms look like {_PITCH_EXAMPLE}.",
        )
    step = letter_match.group(0).upper()
    rest = raw[len(letter_match.group(0)) :]

    # Collapse hyphens/whitespace runs to single spaces and trim, so
    # "c - sharp - 4", "c-sharp-4", and "c sharp 4" are all equivalent.
    normalized = re.sub(r"[-\s]+", " ", rest).strip()

    octave: int | None = None
    octave_match = re.search(r"(\d+)\s*$", normalized)
    if octave_match:
        digits = octave_match.group(1)
        candidate = int(digits)
        if len(digits) > 1 or not (0 <= candidate <= 8):
            raise ToolError(
                ErrorCode.INVALID_PITCH,
                f"'{text}' has an invalid octave ('{digits}'); valid octaves are 0-8. "
                f"Valid forms look like {_PITCH_EXAMPLE}.",
            )
        octave = candidate
        normalized = normalized[: octave_match.start()].strip()

    accidental_text = normalized.lower()
    if accidental_text in _WORD_ACCIDENTALS:
        alter = _WORD_ACCIDENTALS[accidental_text]
    else:
        symbol_key = accidental_text.replace(" ", "")
        if symbol_key in _SYMBOL_ACCIDENTALS:
            alter = _SYMBOL_ACCIDENTALS[symbol_key]
        else:
            raise ToolError(
                ErrorCode.INVALID_PITCH,
                f"Could not parse the accidental in '{text}'. Valid forms look like {_PITCH_EXAMPLE}.",
            )

    return PitchSpec(step=step, alter=alter, octave=octave)


def _build_pitch(step: str, alter: int, octave: int) -> m21.pitch.Pitch:
    pitch = m21.pitch.Pitch()
    pitch.step = step
    pitch.accidental = m21.pitch.Accidental(alter) if alter != 0 else None
    pitch.octave = octave
    return pitch


def realize_pitch(spec: PitchSpec, reference: m21.pitch.Pitch | None) -> m21.pitch.Pitch:
    """Turn a `PitchSpec` into a concrete, properly-spelled
    `music21.pitch.Pitch`.

    If `spec.octave` was given explicitly, it is used as-is. Otherwise the
    octave is chosen to place the new pitch as close as possible (in
    semitones) to `reference`; on an exact tie the higher octave wins.
    With no reference at all, octave 4 is used. The requested letter and
    accidental spelling is always preserved (a request for D-flat comes
    back as D-flat, never its enharmonic equivalent C-sharp).
    """
    if spec.octave is not None:
        return _build_pitch(spec.step, spec.alter, spec.octave)

    if reference is None:
        return _build_pitch(spec.step, spec.alter, 4)

    best_pitch = None
    best_key = None
    for candidate_octave in (reference.octave - 1, reference.octave, reference.octave + 1):
        candidate = _build_pitch(spec.step, spec.alter, candidate_octave)
        distance = abs(candidate.ps - reference.ps)
        # Sort by distance ascending, then by octave descending so an
        # exact tie resolves to the higher octave.
        key = (distance, -candidate_octave)
        if best_key is None or key < best_key:
            best_key = key
            best_pitch = candidate
    return best_pitch


# ---------------------------------------------------------------------------
# Duration vocabulary


# Duration name -> quarter length, in the same style as
# `tools.TEMPO_UNIT_QUARTER_LENGTHS`.
DURATION_QUARTER_LENGTHS: dict[str, float] = {
    "thirty_second": 0.125,
    "dotted_sixteenth": 0.375,
    "sixteenth": 0.25,
    "dotted_eighth": 0.75,
    "eighth": 0.5,
    "dotted_quarter": 1.5,
    "quarter": 1.0,
    "dotted_half": 3.0,
    "half": 2.0,
    "dotted_whole": 6.0,
    "whole": 4.0,
}


def parse_duration(name: str) -> float:
    """Return the quarter length for a duration vocabulary word. Raises
    ToolError(INVALID_DURATION) listing the valid values on unknown input.
    """
    if name not in DURATION_QUARTER_LENGTHS:
        raise ToolError(
            ErrorCode.INVALID_DURATION,
            f"Unknown duration '{name}'. Valid values: {', '.join(sorted(DURATION_QUARTER_LENGTHS))}.",
        )
    return DURATION_QUARTER_LENGTHS[name]


# ---------------------------------------------------------------------------
# Interval vocabulary


# Spoken interval name -> music21 interval string. Several names are
# synonyms for the same interval (half_step/semitone, whole_step/
# whole_tone) because musicians use both interchangeably when dictating.
INTERVAL_NAMES: dict[str, str] = {
    "octave": "P8",
    "half_step": "m2",
    "semitone": "m2",
    "whole_step": "M2",
    "whole_tone": "M2",
    "minor_second": "m2",
    "major_second": "M2",
    "minor_third": "m3",
    "major_third": "M3",
    "perfect_fourth": "P4",
    "tritone": "A4",
    "perfect_fifth": "P5",
    "minor_sixth": "m6",
    "major_sixth": "M6",
    "minor_seventh": "m7",
    "major_seventh": "M7",
}

_VALID_DIRECTIONS = ("up", "down")


def parse_interval(name: str, direction: str) -> m21.interval.Interval:
    """Return a `music21.interval.Interval` for a spoken interval name and
    direction ("up" or "down" -- "down" reverses the interval so applying
    it via `Interval.transposePitch` moves downward). Raises
    ToolError(INVALID_INTERVAL) listing valid values on unknown interval
    name or direction.
    """
    if name not in INTERVAL_NAMES:
        raise ToolError(
            ErrorCode.INVALID_INTERVAL,
            f"Unknown interval '{name}'. Valid values: {', '.join(sorted(INTERVAL_NAMES))}.",
        )
    if direction not in _VALID_DIRECTIONS:
        raise ToolError(
            ErrorCode.INVALID_INTERVAL,
            f"Unknown direction '{direction}'. Valid values: {', '.join(_VALID_DIRECTIONS)}.",
        )

    interval_obj = m21.interval.Interval(INTERVAL_NAMES[name])
    if direction == "down":
        interval_obj = interval_obj.reverse()
    return interval_obj


# ---------------------------------------------------------------------------
# Voice targeting


def target_stream(measure: m21.stream.Measure, offset: float) -> m21.stream.Stream:
    """Return the stream note edits at `offset` should operate in: if
    `measure` contains Voices, the voice that has a note/rest whose span
    covers or starts at `offset` (the first voice if none does); the
    measure itself if it has no voices at all.
    """
    voices = list(measure.getElementsByClass(m21.stream.Voice))
    if not voices:
        return measure

    for voice in voices:
        for element in voice.notesAndRests:
            start = element.offset
            end = start + element.duration.quarterLength
            if start - _EPSILON <= offset < end - _EPSILON or abs(start - offset) < _EPSILON:
                return voice
    return voices[0]


# ---------------------------------------------------------------------------
# Span carving


def _intersects(element, span_start: float, span_end: float) -> bool:
    start = element.offset
    quarter_length = element.duration.quarterLength
    if quarter_length <= _EPSILON:
        # Zero-length (grace) note: intersects if it is positioned inside
        # the span at all, since it has no span of its own to overlap.
        return span_start - _EPSILON <= start < span_end - _EPSILON
    end = start + quarter_length
    return start < span_end - _EPSILON and end > span_start + _EPSILON


def validate_span(measure: m21.stream.Measure, offset: float, quarter_length: float) -> None:
    """Raise-only checks `carve_span` needs before it mutates anything,
    split out so planners can validate a span before the harness takes
    its undo snapshot (see `harness.py`'s lifecycle).

    Raises ToolError(DURATION_CROSSES_BARLINE) if the span would run past
    the measure's writable length (its bar duration minus any pickup
    padding), and ToolError(UNSUPPORTED_TUPLET) if any note/rest the span
    would touch belongs to a tuplet.
    """
    writable_length = measure.barDuration.quarterLength - (measure.paddingLeft or 0)
    span_end = offset + quarter_length
    if span_end > writable_length + _EPSILON:
        remaining = max(writable_length - offset, 0)
        raise ToolError(
            ErrorCode.DURATION_CROSSES_BARLINE,
            f"Measure {measure.number} only has {remaining:g} quarter length of room left "
            f"starting at offset {offset:g} (bar length {writable_length:g}), but this edit "
            f"needs {quarter_length:g}. Try a shorter duration.",
        )

    stream_obj = target_stream(measure, offset)
    for element in stream_obj.notesAndRests:
        if _intersects(element, offset, span_end) and element.duration.tuplets:
            raise ToolError(
                ErrorCode.UNSUPPORTED_TUPLET,
                f"Measure {measure.number} has a tuplet overlapping offset {offset:g}-{span_end:g}; "
                "tuplet passages can't be rewritten yet.",
            )


def _boundary_note(measure: m21.stream.Measure, direction: str):
    """Return the first ("next") or last ("previous", read backwards)
    note in the sibling measure adjacent to `measure` within its part, or
    None if there is no enclosing part or no such measure/note. Used to
    repair a tie whose partner lies just across a barline from the span
    being carved -- outside the stream `carve_span` otherwise looks at.
    """
    part = measure.activeSite
    if part is None:
        return None
    measures = sorted(part.getElementsByClass(m21.stream.Measure), key=lambda m: m.offset)
    try:
        idx = next(i for i, m in enumerate(measures) if m is measure)
    except StopIteration:
        return None

    ordered = measures[idx + 1 :] if direction == "next" else reversed(measures[:idx])
    for sibling in ordered:
        notes = sorted(sibling.recurse().notes, key=lambda n: n.offset)
        if not notes:
            continue
        return notes[0] if direction == "next" else notes[-1]
    return None


def _clear_incoming_tie(neighbor) -> None:
    """`neighbor` was the target of a tie ("start") whose source note was
    just removed. Drop the now-dangling backward half of its own tie.
    """
    tie_obj = getattr(neighbor, "tie", None)
    if tie_obj is None:
        return
    if tie_obj.type == "stop":
        neighbor.tie = None
    elif tie_obj.type == "continue":
        neighbor.tie = m21.tie.Tie("start")


def _clear_outgoing_tie(neighbor) -> None:
    """`neighbor` had a tie ("start") pointing at a note that was just
    removed. Drop the now-dangling forward half of its own tie.
    """
    tie_obj = getattr(neighbor, "tie", None)
    if tie_obj is None:
        return
    if tie_obj.type == "start":
        neighbor.tie = None
    elif tie_obj.type == "continue":
        neighbor.tie = m21.tie.Tie("stop")


def carve_span(measure: m21.stream.Measure, offset: float, quarter_length: float) -> m21.stream.Stream:
    """Clear the time span `[offset, offset + quarter_length)` inside the
    appropriate voice/measure stream of `measure` and return that stream,
    ready for a caller to insert new content into.

    Every note/rest intersecting the span is removed outright (grace
    notes included). A removed note that started before `offset` leaves a
    backfill rest covering `[its_start, offset)`; one that extended past
    the span end leaves a backfill rest covering `[span_end, its_end)`.
    Ties into notes outside the span are repaired on the surviving
    partner so no dangling tie is left behind.

    Calls `validate_span` first, so every raise-check runs before the
    first removal -- a failed carve never partially mutates the measure.
    """
    validate_span(measure, offset, quarter_length)

    stream_obj = target_stream(measure, offset)
    span_start, span_end = offset, offset + quarter_length

    elements = sorted(stream_obj.notesAndRests, key=lambda e: e.offset)
    to_remove = [e for e in elements if _intersects(e, span_start, span_end)]
    removal_ids = {id(e) for e in to_remove}

    for idx, element in enumerate(elements):
        if id(element) not in removal_ids:
            continue
        tie_obj = getattr(element, "tie", None)
        if tie_obj is None:
            continue
        if tie_obj.type == "start":
            if idx + 1 < len(elements):
                neighbor = elements[idx + 1]
                if id(neighbor) not in removal_ids:
                    _clear_incoming_tie(neighbor)
            else:
                # Last note in this stream: its tie partner, if any, is
                # the first note of the next measure (across the
                # barline), not reachable through `elements`.
                neighbor = _boundary_note(measure, "next")
                if neighbor is not None:
                    _clear_incoming_tie(neighbor)
        if tie_obj.type in ("stop", "continue"):
            if idx - 1 >= 0:
                neighbor = elements[idx - 1]
                if id(neighbor) not in removal_ids:
                    _clear_outgoing_tie(neighbor)
            else:
                # First note in this stream: its tie partner is the last
                # note of the previous measure.
                neighbor = _boundary_note(measure, "previous")
                if neighbor is not None:
                    _clear_outgoing_tie(neighbor)

    for element in to_remove:
        start = element.offset
        end = start + element.duration.quarterLength
        stream_obj.remove(element)
        if start < span_start - _EPSILON:
            stream_obj.insert(start, m21.note.Rest(quarterLength=span_start - start))
        if end > span_end + _EPSILON:
            stream_obj.insert(span_end, m21.note.Rest(quarterLength=end - span_end))

    return stream_obj
