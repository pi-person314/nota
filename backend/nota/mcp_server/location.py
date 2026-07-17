"""Resolve (part, measure, beat) references against a parsed music21 score.

Beats are quarter-note-relative to the measure's meter the way musicians
count them (music21's `TimeSignature.beatCount` and `getOffsetFromBeat`
already handle compound meters, pickups, and mid-piece meter changes
correctly, so this module leans on those rather than re-deriving offsets by
hand). All functions here either return a resolved object or raise a
`ToolError` with an actionable message; they never mutate the score.
"""

from __future__ import annotations

import music21 as m21

from .errors import ErrorCode, ToolError

_EPSILON = 1e-6


def resolve_part(score, part_name: str | None):
    """Return the part matching `part_name`, or the first part if
    `part_name` is None/blank. Raises PART_NOT_FOUND (listing valid part
    names) if a name is given and nothing matches.
    """
    parts = list(score.parts)
    if not parts:
        # A bare Part (no enclosing Score) parses with no `.parts`.
        parts = [score]

    if part_name is None or not str(part_name).strip():
        return parts[0]

    target = str(part_name).strip().lower()
    for part in parts:
        candidates = {c for c in (part.partName, part.id) if c}
        if any(str(c).strip().lower() == target for c in candidates):
            return part

    valid = sorted({str(part.partName or part.id) for part in parts})
    raise ToolError(
        ErrorCode.PART_NOT_FOUND,
        f"No part named '{part_name}'. Valid parts: {', '.join(valid)}.",
    )


def _measure_map(part) -> dict[int, m21.stream.Measure]:
    return {measure.number: measure for measure in part.getElementsByClass(m21.stream.Measure)}


def measure_count(part) -> int:
    """Number of regular (non-pickup) measures, i.e. the highest measure
    number >= 1 present in the part.
    """
    numbers = [n for n in _measure_map(part) if n >= 1]
    return max(numbers) if numbers else 0


def _pickup_measure_number(part) -> int | None:
    """Return the number of `part`'s pickup (anacrusis) measure, or None
    if it has none. Most scores number the pickup 0, but real-world
    MusicXML sometimes numbers it 1 instead (with no measure 0 at all) and
    signals the pickup only through `paddingLeft` on that first measure —
    observed on a real corpus score (Schoenberg op. 19 no. 6). Only the
    lowest-numbered measure is ever checked: a `paddingLeft` on a later
    measure means a mid-piece insertion/anacrusis, not a pickup.
    """
    measures = _measure_map(part)
    if not measures:
        return None
    if 0 in measures:
        return 0
    first_number = min(measures)
    if (measures[first_number].paddingLeft or 0) > 0:
        return first_number
    return None


def has_pickup(part) -> bool:
    return _pickup_measure_number(part) is not None


def resolve_measure(part, measure_num: int) -> m21.stream.Measure:
    """Return the Measure with this number. Raises MEASURE_OUT_OF_RANGE
    (message states the actual measure count, and mentions the pickup
    measure if one exists) if there is no such measure.
    """
    measures = _measure_map(part)
    if measure_num not in measures:
        count = measure_count(part)
        pickup_number = _pickup_measure_number(part)
        pickup_note = (
            f" (plus a pickup measure, numbered {pickup_number})"
            if pickup_number is not None
            else ""
        )
        raise ToolError(
            ErrorCode.MEASURE_OUT_OF_RANGE,
            f"Measure {measure_num} does not exist. The score has "
            f"{count} measure{'s' if count != 1 else ''}{pickup_note}.",
        )
    return measures[measure_num]


def _time_signature_for(measure: m21.stream.Measure):
    return measure.timeSignature or measure.getContextByClass(m21.meter.TimeSignature)


def resolve_beat_offset(measure: m21.stream.Measure, beat: float) -> float:
    """Convert a 1-based musician's beat number into an offset (in quarter
    lengths) relative to the start of `measure`, validated against that
    measure's actual meter. Raises BEAT_OUT_OF_RANGE (message states the
    measure's actual beat count) if `beat` is out of range.
    """
    ts = _time_signature_for(measure)
    if ts is None:
        # Defensive: every well-formed score carries an initial time
        # signature that later measures inherit via context, so this
        # should not be reachable in practice.
        raise ToolError(
            ErrorCode.BEAT_OUT_OF_RANGE,
            f"Measure {measure.number} has no discoverable time signature.",
        )

    beat_count = ts.beatCount
    if beat < 1 or beat >= beat_count + 1:
        raise ToolError(
            ErrorCode.BEAT_OUT_OF_RANGE,
            f"Measure {measure.number} is in {ts.ratioString} time and has "
            f"{beat_count} beat{'s' if beat_count != 1 else ''}. Beat {_format_beat(beat)} "
            "is out of range for that measure.",
        )

    # In a pickup (anacrusis) measure, musicians count beats as if the
    # missing opening beats existed: a one-quarter pickup in 4/4 is "beat
    # 4", but that note's offset within the measure stream is 0.
    # `paddingLeft` holds the length of the missing opening span, so
    # shifting by it converts a counted beat into a real intra-measure
    # offset. Beats that fall inside the missing span don't exist in the
    # pickup at all.
    offset = ts.getOffsetFromBeat(beat) - measure.paddingLeft
    if offset < 0:
        first_beat = ts.getBeatProportion(measure.paddingLeft)
        raise ToolError(
            ErrorCode.BEAT_OUT_OF_RANGE,
            f"Measure {measure.number} is a pickup measure: in {ts.ratioString} time "
            f"it begins at beat {_format_beat(first_beat)}, so beat {_format_beat(beat)} "
            "does not exist in it.",
        )
    return offset


def _format_beat(beat: float) -> str:
    return f"{beat:g}"


def find_note_at(measure: m21.stream.Measure, beat: float):
    """Return the note/chord starting at `beat` within `measure`. When a
    grace note and a full-duration note share the same beat, the
    full-duration note is preferred (that is what a musician means when
    they say "beat 2"). Raises NO_NOTE_AT_POSITION (message lists the
    nearest note positions in that measure) if nothing starts there, and
    BEAT_OUT_OF_RANGE if the beat itself isn't valid for this meter.
    """
    offset = resolve_beat_offset(measure, beat)
    all_notes = list(measure.recurse().notes)
    candidates = [n for n in all_notes if abs(n.offset - offset) < _EPSILON]
    non_grace = [n for n in candidates if not n.duration.isGrace]
    chosen = non_grace[0] if non_grace else (candidates[0] if candidates else None)

    if chosen is None:
        note_beats = sorted({n.beat for n in all_notes if not n.duration.isGrace})
        nearest = (
            ", ".join(_format_beat(b) for b in note_beats)
            if note_beats
            else "none — the measure has no notes"
        )
        raise ToolError(
            ErrorCode.NO_NOTE_AT_POSITION,
            f"No note at measure {measure.number} beat {_format_beat(beat)}. "
            f"Notes in that measure start at beat(s): {nearest}.",
        )
    return chosen


def note_at_offset_or_none(measure: m21.stream.Measure, offset: float):
    """Return the note/chord starting exactly at `offset` within `measure`
    (preferring a full-duration note over a grace note at the same offset,
    as `find_note_at` does), or None if nothing starts there.

    Unlike `find_note_at`, this never raises. It exists for tools whose
    own created element does not carry its id through MusicXML export
    (e.g. a free-floating text expression or rehearsal mark, which are
    not required to sit on a note) but that still want to report a
    nearby note's id as a best-effort highlighting anchor when one
    happens to be there.
    """
    all_notes = list(measure.recurse().notes)
    candidates = [n for n in all_notes if abs(n.offset - offset) < _EPSILON]
    non_grace = [n for n in candidates if not n.duration.isGrace]
    return non_grace[0] if non_grace else (candidates[0] if candidates else None)


def notes_in_range(
    part,
    start_measure: m21.stream.Measure,
    start_beat: float,
    end_measure: m21.stream.Measure,
    end_beat: float,
):
    """Return every note/chord in `part` (across voices, including grace
    notes) whose absolute offset falls within [start, end], inclusive,
    ordered by offset. `start`/`end` are resolved from measure+beat pairs
    that have already been validated by the caller via
    `resolve_measure`/`resolve_beat_offset`.
    """
    start_offset = start_measure.getOffsetInHierarchy(part) + resolve_beat_offset(
        start_measure, start_beat
    )
    end_offset = end_measure.getOffsetInHierarchy(part) + resolve_beat_offset(end_measure, end_beat)
    lo, hi = min(start_offset, end_offset), max(start_offset, end_offset)

    matches = []
    for note in part.recurse().notes:
        abs_offset = note.getOffsetInHierarchy(part)
        if lo - _EPSILON <= abs_offset <= hi + _EPSILON:
            matches.append((abs_offset, note))

    matches.sort(key=lambda pair: pair[0])
    return [note for _, note in matches]
