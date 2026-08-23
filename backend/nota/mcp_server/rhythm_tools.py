"""Rhythm/structure notation tools: writing, resizing, and deleting notes.

These follow the same shape as `tools.py`'s functions (a public function
that builds an undo-stack label and a `planner(score) -> ToolPlan`, then
calls `run_tool`), but build on `notes.py`'s pitch/duration/span-carving
helpers instead of attaching free-standing markings. As with every other
tool, all raise-checks run inside the planner -- including calling
`notes.validate_span` directly wherever a span is about to be carved, even
though `carve_span` itself re-validates -- because the harness snapshots
the score for undo immediately after the planner returns, and anything a
`ToolPlan.apply` callback raises past that point is not turned into a
structured error the way a `ToolError` raised during planning is.
"""

from __future__ import annotations

import music21 as m21

from . import ids, location, notes
from .harness import ToolPlan, run_tool
from .notes import _boundary_note, _clear_incoming_tie, _clear_outgoing_tie

_EPSILON = 1e-6


def _format_beat(beat: float) -> str:
    return f"{beat:g}"


def _duration_word(name: str) -> str:
    return name.replace("_", " ")


def _span_has_note(measure: m21.stream.Measure, offset: float, quarter_length: float) -> bool:
    """Whether any Note/Chord (rests don't count) intersects
    `[offset, offset + quarter_length)` in the voice/measure stream that
    would actually be carved at that position. Used both to phrase a
    "replacing the existing notes there" summary clause and to detect an
    already-empty span for a no-op.
    """
    if quarter_length <= _EPSILON:
        return False
    stream_obj = notes.target_stream(measure, offset)
    span_end = offset + quarter_length
    for element in stream_obj.notesAndRests:
        if isinstance(element, m21.note.Rest):
            continue
        start = element.offset
        el_ql = element.duration.quarterLength
        if el_ql <= _EPSILON:
            if offset - _EPSILON <= start < span_end - _EPSILON:
                return True
            continue
        end = start + el_ql
        if start < span_end - _EPSILON and end > offset + _EPSILON:
            return True
    return False


# ---------------------------------------------------------------------------
# add_note


def _nearest_reference_pitch(part_obj, measure_obj: m21.stream.Measure, offset: float):
    """The pitch of the note nearest the insertion point, for octave
    placement of a pitch spec with no explicit octave: the nearest note
    starting strictly before the insertion point anywhere in the part; if
    none, the nearest note starting at or after it; if the part has no
    notes at all, None. A chord candidate contributes its highest pitch.
    """
    insertion_abs = measure_obj.getOffsetInHierarchy(part_obj) + offset

    before = None
    after = None
    for candidate in part_obj.recurse().notes:
        abs_offset = candidate.getOffsetInHierarchy(part_obj)
        if abs_offset < insertion_abs - _EPSILON:
            if before is None or abs_offset > before[0]:
                before = (abs_offset, candidate)
        else:
            if after is None or abs_offset < after[0]:
                after = (abs_offset, candidate)

    chosen = before[1] if before is not None else (after[1] if after is not None else None)
    if chosen is None:
        return None
    if isinstance(chosen, m21.chord.Chord):
        return max(chosen.pitches, key=lambda p: p.ps)
    return chosen.pitch


def add_note(
    score_id: str,
    measure: int,
    beat: float,
    pitch: str,
    duration: str,
    part: str | None = None,
) -> dict:
    """Write a note at a measure/beat position, overwriting whatever
    currently occupies that time span the way a desktop notation editor's
    note-entry tool does: notes/rests fully covered by the new note's
    duration are removed outright, a note only partially covered keeps its
    uncovered remainder as a backfill rest, and nothing else in the
    measure shifts.
    """
    label = f"add_note m{measure} b{_format_beat(beat)}"

    def planner(score: m21.stream.Score) -> ToolPlan:
        part_obj = location.resolve_part(score, part)
        pitch_spec = notes.parse_pitch_spec(pitch)
        quarter_length = notes.parse_duration(duration)
        measure_obj = location.resolve_measure(part_obj, measure)
        offset = location.resolve_beat_offset(measure_obj, beat)
        notes.validate_span(measure_obj, offset, quarter_length)

        had_notes = _span_has_note(measure_obj, offset, quarter_length)
        reference_pitch = (
            _nearest_reference_pitch(part_obj, measure_obj, offset)
            if pitch_spec.octave is None
            else None
        )

        def apply() -> tuple[list[str], str]:
            stream = notes.carve_span(measure_obj, offset, quarter_length)
            pitch_obj = notes.realize_pitch(pitch_spec, reference_pitch)
            note_obj = m21.note.Note(pitch_obj, quarterLength=quarter_length)
            note_id = ids.assign_id(note_obj)
            stream.insert(offset, note_obj)

            summary = (
                f"Added a {_duration_word(duration)} note {pitch_obj.nameWithOctave} at "
                f"measure {measure}, beat {_format_beat(beat)}"
            )
            if had_notes:
                summary += ", replacing the existing notes there"
            return [note_id], summary

        return ToolPlan(apply=apply)

    return run_tool(score_id, label, planner)


# ---------------------------------------------------------------------------
# set_duration


def _forward_neighbor(measure_obj: m21.stream.Measure, stream_obj: m21.stream.Stream, target_note):
    """The note/rest immediately following `target_note` in `stream_obj`,
    or the first note of the next measure if `target_note` is the last
    element in its stream. Used to locate a tie partner without carving
    anything, for the shortening path of `set_duration`.
    """
    elements = sorted(stream_obj.notesAndRests, key=lambda e: e.offset)
    idx = next((i for i, e in enumerate(elements) if e is target_note), None)
    if idx is None or idx + 1 >= len(elements):
        return _boundary_note(measure_obj, "next")
    return elements[idx + 1]


def set_duration(score_id: str, measure: int, beat: float, duration: str, part: str | None = None) -> dict:
    """Change the written duration of the note/chord starting at a
    measure/beat position, keeping its pitch(es) and any attached
    articulations/expressions -- the existing object's duration is
    mutated in place rather than the note being recreated.
    """
    label = f"set_duration m{measure} b{_format_beat(beat)}"

    def planner(score: m21.stream.Score) -> ToolPlan:
        part_obj = location.resolve_part(score, part)
        new_ql = notes.parse_duration(duration)
        measure_obj = location.resolve_measure(part_obj, measure)
        target_note = location.find_note_at(measure_obj, beat)
        note_offset = location.resolve_beat_offset(measure_obj, beat)
        old_ql = target_note.duration.quarterLength
        duration_word = _duration_word(duration)

        if abs(new_ql - old_ql) < _EPSILON:
            return ToolPlan(
                no_op_summary=(
                    f"The note at measure {measure}, beat {_format_beat(beat)} is already "
                    f"a {duration_word} note"
                )
            )

        if new_ql > old_ql:
            extension = new_ql - old_ql
            notes.validate_span(measure_obj, note_offset + old_ql, extension)

            def apply() -> tuple[list[str], str]:
                # Clearing the extension span also repairs a forward tie on
                # `target_note`, if it has one: `carve_span` looks at the
                # tie type of whatever it removes, and a removed note tied
                # back to this one has type "stop"/"continue", which
                # triggers the same outgoing-tie repair on this note that
                # `carve_span` runs on any other surviving neighbor.
                notes.carve_span(measure_obj, note_offset + old_ql, extension)
                target_note.duration.quarterLength = new_ql
                note_id = ids.assign_id(target_note)
                summary = (
                    f"Changed the note at measure {measure}, beat {_format_beat(beat)} "
                    f"to a {duration_word} note"
                )
                return [note_id], summary

            return ToolPlan(apply=apply)

        def apply() -> tuple[list[str], str]:
            stream_obj = notes.target_stream(measure_obj, note_offset)
            tie_obj = getattr(target_note, "tie", None)
            if tie_obj is not None and tie_obj.type in ("start", "continue"):
                partner = _forward_neighbor(measure_obj, stream_obj, target_note)
                if partner is not None:
                    _clear_incoming_tie(partner)
                _clear_outgoing_tie(target_note)

            target_note.duration.quarterLength = new_ql
            stream_obj.insert(note_offset + new_ql, m21.note.Rest(quarterLength=old_ql - new_ql))
            note_id = ids.assign_id(target_note)
            summary = (
                f"Changed the note at measure {measure}, beat {_format_beat(beat)} "
                f"to a {duration_word} note"
            )
            return [note_id], summary

        return ToolPlan(apply=apply)

    return run_tool(score_id, label, planner)


# ---------------------------------------------------------------------------
# delete_note


def _plan_delete_single(part_obj, measure: int, beat: float) -> ToolPlan:
    measure_obj = location.resolve_measure(part_obj, measure)
    target_note = location.find_note_at(measure_obj, beat)
    note_offset = location.resolve_beat_offset(measure_obj, beat)
    note_ql = target_note.duration.quarterLength
    notes.validate_span(measure_obj, note_offset, note_ql)

    def apply() -> tuple[list[str], str]:
        stream = notes.carve_span(measure_obj, note_offset, note_ql)
        stream.insert(note_offset, m21.note.Rest(quarterLength=note_ql))
        summary = f"Deleted the note at measure {measure}, beat {_format_beat(beat)} (replaced with a rest)"
        return [], summary

    return ToolPlan(apply=apply)


def _plan_delete_whole_measure(part_obj, measure: int) -> ToolPlan:
    measure_obj = location.resolve_measure(part_obj, measure)
    writable_length = measure_obj.barDuration.quarterLength - (measure_obj.paddingLeft or 0)
    notes.validate_span(measure_obj, 0.0, writable_length)

    if not _span_has_note(measure_obj, 0.0, writable_length):
        return ToolPlan(no_op_summary=f"Measure {measure} is already all rests")

    def apply() -> tuple[list[str], str]:
        stream = notes.carve_span(measure_obj, 0.0, writable_length)
        stream.insert(0.0, m21.note.Rest(quarterLength=writable_length))
        summary = f"Cleared measure {measure} to rests"
        return [], summary

    return ToolPlan(apply=apply)


def _plan_delete_range(
    part_obj,
    measure: int,
    beat: float | None,
    end_measure: int,
    end_beat: float | None,
) -> ToolPlan:
    # `beat` always pairs with `measure` and `end_beat` always pairs with
    # `end_measure`; sorting the two (measure, beat) pairs by measure
    # number keeps that pairing intact when end_measure < measure.
    pair_lo, pair_hi = sorted([(measure, beat), (end_measure, end_beat)], key=lambda pair: pair[0])
    start_num, start_beat = pair_lo
    end_num, end_beat_val = pair_hi

    measure_objs = {m_num: location.resolve_measure(part_obj, m_num) for m_num in range(start_num, end_num + 1)}
    start_measure_obj = measure_objs[start_num]
    end_measure_obj = measure_objs[end_num]

    start_offset = (
        location.resolve_beat_offset(start_measure_obj, start_beat) if start_beat is not None else 0.0
    )
    if end_beat_val is not None:
        end_offset_in_last = location.resolve_beat_offset(end_measure_obj, end_beat_val)
        note_at_end = location.note_at_offset_or_none(end_measure_obj, end_offset_in_last)
        if note_at_end is not None:
            end_bound = end_offset_in_last + note_at_end.duration.quarterLength
        else:
            end_bound = end_offset_in_last
    else:
        end_bound = end_measure_obj.barDuration.quarterLength - (end_measure_obj.paddingLeft or 0)

    spans: list[tuple[m21.stream.Measure, float, float]] = []
    if start_num == end_num:
        spans.append((start_measure_obj, start_offset, max(end_bound - start_offset, 0.0)))
    else:
        first_writable = start_measure_obj.barDuration.quarterLength - (start_measure_obj.paddingLeft or 0)
        spans.append((start_measure_obj, start_offset, max(first_writable - start_offset, 0.0)))
        for m_num in range(start_num + 1, end_num):
            mid_obj = measure_objs[m_num]
            mid_writable = mid_obj.barDuration.quarterLength - (mid_obj.paddingLeft or 0)
            spans.append((mid_obj, 0.0, mid_writable))
        spans.append((end_measure_obj, 0.0, end_bound))

    for m_obj, off, ql in spans:
        if ql > _EPSILON:
            notes.validate_span(m_obj, off, ql)

    has_notes = any(ql > _EPSILON and _span_has_note(m_obj, off, ql) for m_obj, off, ql in spans)

    if beat is None and end_beat is None:
        summary_location = (
            f"measure {start_num}" if start_num == end_num else f"measures {start_num}–{end_num}"
        )
    else:
        start_desc = f"measure {measure}" + (f" beat {_format_beat(beat)}" if beat is not None else "")
        end_desc = f"measure {end_measure}" + (f" beat {_format_beat(end_beat)}" if end_beat is not None else "")
        summary_location = f"{start_desc} through {end_desc}"

    if not has_notes:
        no_op_location = (
            f"Measure {start_num} is" if start_num == end_num else f"Measures {start_num}–{end_num} are"
        )
        return ToolPlan(no_op_summary=f"{no_op_location} already all rests")

    def apply() -> tuple[list[str], str]:
        for m_obj, off, ql in spans:
            if ql <= _EPSILON:
                continue
            stream = notes.carve_span(m_obj, off, ql)
            stream.insert(off, m21.note.Rest(quarterLength=ql))
        summary = f"Cleared {summary_location} to rests"
        return [], summary

    return ToolPlan(apply=apply)


def delete_note(
    score_id: str,
    measure: int,
    beat: float | None = None,
    end_measure: int | None = None,
    end_beat: float | None = None,
    part: str | None = None,
) -> dict:
    """Replace one note, a whole measure, or a measure range with rests of
    the same total length -- engraved music doesn't shift when a note is
    deleted, so what follows always keeps its position.

    With `beat` and no `end_measure`, the note/chord starting at that beat
    is replaced with a single rest. With neither `beat` nor `end_measure`,
    the whole measure's writable span is cleared to a single rest (a
    measure already containing only rests is a no-op). With `end_measure`
    given, every measure from `measure` to `end_measure` (in either order)
    is cleared to rests; `beat`/`end_beat`, if given, narrow the start/end
    of the cleared span within their respective measures.
    """
    if end_measure is not None:
        label = f"delete_note m{measure}-m{end_measure}"
    elif beat is not None:
        label = f"delete_note m{measure} b{_format_beat(beat)}"
    else:
        label = f"delete_note m{measure}"

    def planner(score: m21.stream.Score) -> ToolPlan:
        part_obj = location.resolve_part(score, part)

        if end_measure is not None:
            return _plan_delete_range(part_obj, measure, beat, end_measure, end_beat)
        if beat is not None:
            return _plan_delete_single(part_obj, measure, beat)
        return _plan_delete_whole_measure(part_obj, measure)

    return run_tool(score_id, label, planner)
