"""Pitch-editing notation tools: changing an existing note's pitch and
transposing a measure range.

Both tools follow the same shape as `tools.py`: a public function taking
`score_id` plus kwargs, a `planner(score) -> ToolPlan` that resolves and
validates the request against the live score (raising `ToolError` before
any mutation), and `run_tool` to carry out the stateless lifecycle
described in `harness.py`.
"""

from __future__ import annotations

import copy

import music21 as m21

from . import ids, location, notes
from .errors import ErrorCode, ToolError
from .harness import ToolPlan, run_tool


def _format_beat(beat: float) -> str:
    return f"{beat:g}"


# ---------------------------------------------------------------------------
# change_pitch helpers


def _spec_matches_pitch(spec: notes.PitchSpec, candidate: m21.pitch.Pitch) -> bool:
    """Whether `candidate` matches a parsed pitch spec: same letter and
    accidental always; same octave too, if the spec gave one.
    """
    if candidate.step != spec.step:
        return False
    if candidate.alter != spec.alter:
        return False
    if spec.octave is not None and candidate.octave != spec.octave:
        return False
    return True


def _matching_member_index(chord_obj: m21.chord.Chord, spec: notes.PitchSpec) -> int | None:
    """Index of the first pitch in `chord_obj` matching `spec`, or None."""
    for i, p in enumerate(chord_obj.pitches):
        if _spec_matches_pitch(spec, p):
            return i
    return None


def _describe_chord_pitches(chord_obj: m21.chord.Chord) -> str:
    return ", ".join(p.nameWithOctave for p in chord_obj.pitches)


def _describe_note_element(element) -> str:
    if isinstance(element, m21.chord.Chord):
        return f"a chord ({_describe_chord_pitches(element)})"
    return element.pitch.nameWithOctave


def _find_matches_in_measure(
    measure_obj: m21.stream.Measure, spec: notes.PitchSpec
) -> list[tuple]:
    """Every (container, note_obj) in `measure_obj` (all voices, rests
    already excluded by `.notes`) whose pitch matches `spec`. `container`
    is the Note or Chord actually sitting in the stream; `note_obj` is the
    specific per-pitch Note that matched (itself, for a plain Note; one of
    `chord.notes`, for a Chord).
    """
    matches = []
    for element in measure_obj.recurse().notes:
        if isinstance(element, m21.chord.Chord):
            idx = _matching_member_index(element, spec)
            if idx is not None:
                matches.append((element, element.notes[idx]))
        elif _spec_matches_pitch(spec, element.pitch):
            matches.append((element, element))
    return matches


def _leaf_sequence(part_obj: m21.stream.Part) -> list[tuple]:
    """Flatten every Note and Chord in `part_obj` into per-pitch leaves
    `(offset, container, note_obj)`, ordered by offset. A Chord
    contributes one leaf per member pitch (all sharing its offset), since
    ties connect per-pitch, not per-chord. Used to walk a tie chain
    forward/backward from a target note.
    """
    leaves = []
    for element in part_obj.recurse().notes:
        offset = element.getOffsetInHierarchy(part_obj)
        if isinstance(element, m21.chord.Chord):
            for note_obj in element.notes:
                leaves.append((offset, element, note_obj))
        else:
            leaves.append((offset, element, element))
    leaves.sort(key=lambda item: item[0])
    return leaves


def _tie_chain(leaves: list[tuple], idx: int) -> list[tuple]:
    """Every `(container, note_obj)` tied to `leaves[idx]`, that leaf
    included: walk forward while the current note's tie says
    start/continue and the next leaf has the same pitch, then walk
    backward the same way for stop/continue. A leaf with no tie at all
    yields just itself.
    """
    target_note_obj = leaves[idx][2]
    target_pitch_name = target_note_obj.pitch.nameWithOctave
    chain = [(leaves[idx][1], target_note_obj)]

    current, i = target_note_obj, idx
    while True:
        tie_obj = getattr(current, "tie", None)
        if tie_obj is None or tie_obj.type not in ("start", "continue"):
            break
        if i + 1 >= len(leaves):
            break
        nxt_offset, nxt_container, nxt = leaves[i + 1]
        if nxt.pitch.nameWithOctave != target_pitch_name:
            break
        chain.append((nxt_container, nxt))
        current, i = nxt, i + 1

    current, i = target_note_obj, idx
    while True:
        tie_obj = getattr(current, "tie", None)
        if tie_obj is None or tie_obj.type not in ("stop", "continue"):
            break
        if i - 1 < 0:
            break
        prv_offset, prv_container, prv = leaves[i - 1]
        if prv.pitch.nameWithOctave != target_pitch_name:
            break
        chain.append((prv_container, prv))
        current, i = prv, i - 1

    return chain


def change_pitch(
    score_id: str,
    measure: int,
    pitch: str,
    beat: float | None = None,
    from_pitch: str | None = None,
    part: str | None = None,
) -> dict:
    """Change the pitch of an existing note (or one member of a chord),
    preserving its duration, articulations, expressions, and everything
    else attached to it -- the note is mutated in place, never recreated.

    Targeting: with `beat`, the note/chord starting there is the target
    (a chord requires `from_pitch` to say which member); without `beat`,
    `from_pitch` is required and the measure's notes (all voices) are
    searched for a pitch-class match. If the targeted note is part of a
    tie chain, every note in the chain gets the new pitch. An octave in
    `pitch` is honored as given; otherwise the new pitch lands in the
    octave nearest the note's current one.
    """
    label = (
        f"change_pitch m{measure}"
        + (f"b{_format_beat(beat)}" if beat is not None else "")
        + f" -> {pitch}"
    )

    def planner(score: m21.stream.Score) -> ToolPlan:
        part_obj = location.resolve_part(score, part)

        new_spec = notes.parse_pitch_spec(pitch)
        from_spec = notes.parse_pitch_spec(from_pitch) if from_pitch else None

        measure_obj = location.resolve_measure(part_obj, measure)

        if beat is not None:
            target_container = location.find_note_at(measure_obj, beat)
            if isinstance(target_container, m21.chord.Chord):
                if from_spec is None:
                    raise ToolError(
                        ErrorCode.AMBIGUOUS_TARGET,
                        f"Measure {measure} beat {_format_beat(beat)} is a chord "
                        f"({_describe_chord_pitches(target_container)}) -- say from_pitch "
                        "to pick which note in it to change.",
                    )
                match_idx = _matching_member_index(target_container, from_spec)
                if match_idx is None:
                    raise ToolError(
                        ErrorCode.NO_NOTE_AT_POSITION,
                        f"No note matching '{from_pitch}' in the chord at measure {measure} "
                        f"beat {_format_beat(beat)} ({_describe_chord_pitches(target_container)}).",
                    )
                target_note_obj = target_container.notes[match_idx]
            else:
                target_note_obj = target_container
        else:
            if from_spec is None:
                raise ToolError(
                    ErrorCode.AMBIGUOUS_TARGET,
                    "Say which beat, or which note (by its current pitch), to change.",
                )
            matches = _find_matches_in_measure(measure_obj, from_spec)
            if not matches:
                present = [
                    f"{_describe_note_element(e)} at beat {_format_beat(e.beat)}"
                    for e in measure_obj.recurse().notes
                ]
                contents = ", ".join(present) if present else "no notes"
                raise ToolError(
                    ErrorCode.NO_NOTE_AT_POSITION,
                    f"No note matching '{from_pitch}' found in measure {measure}. "
                    f"That measure contains: {contents}.",
                )
            if len(matches) > 1:
                beats_desc = ", ".join(
                    _format_beat(container.beat) for container, _ in matches
                )
                raise ToolError(
                    ErrorCode.AMBIGUOUS_TARGET,
                    f"'{from_pitch}' matches more than one note in measure {measure} "
                    f"(beats: {beats_desc}) -- add beat to say which one.",
                )
            target_container, target_note_obj = matches[0]

        reference_pitch = target_note_obj.pitch
        new_pitch = notes.realize_pitch(new_spec, reference=reference_pitch)

        original_pitch_str = reference_pitch.nameWithOctave
        new_pitch_str = new_pitch.nameWithOctave
        report_beat = _format_beat(target_container.beat)

        same_spelling = (
            new_pitch.step == reference_pitch.step
            and new_pitch.octave == reference_pitch.octave
            and new_pitch.alter == reference_pitch.alter
        )
        if same_spelling:
            return ToolPlan(
                no_op_summary=(
                    f"{original_pitch_str} is already {new_pitch_str} at measure {measure}, "
                    f"beat {report_beat}"
                )
            )

        def apply() -> tuple[list[str], str]:
            leaves = _leaf_sequence(part_obj)
            target_idx = next(
                i
                for i, leaf in enumerate(leaves)
                if leaf[2] is target_note_obj and leaf[1] is target_container
            )
            chain = _tie_chain(leaves, target_idx)

            changed_ids = []
            seen_containers: set[int] = set()
            for container, note_obj in chain:
                note_obj.pitch = copy.deepcopy(new_pitch)
                if id(container) not in seen_containers:
                    seen_containers.add(id(container))
                    changed_ids.append(ids.assign_id(container))

            summary = (
                f"Changed {original_pitch_str} to {new_pitch_str} at measure {measure}, "
                f"beat {report_beat}"
            )
            return changed_ids, summary

        return ToolPlan(apply=apply)

    return run_tool(score_id, label, planner)


# ---------------------------------------------------------------------------
# transpose


def transpose(
    score_id: str,
    interval: str,
    direction: str,
    start_measure: int,
    end_measure: int | None = None,
    part: str | None = None,
) -> dict:
    """Transpose every note in a measure range (chords and grace notes
    included) by a named interval. `end_measure` defaults to
    `start_measure`; if it comes before `start_measure`, the two are
    swapped silently.
    """
    label = (
        f"transpose {direction} {interval} m{start_measure}"
        + (f"-{end_measure}" if end_measure is not None else "")
    )

    def planner(score: m21.stream.Score) -> ToolPlan:
        part_obj = location.resolve_part(score, part)

        interval_obj = notes.parse_interval(interval, direction)

        end = end_measure if end_measure is not None else start_measure
        lo, hi = min(start_measure, end), max(start_measure, end)

        location.resolve_measure(part_obj, lo)
        if hi != lo:
            location.resolve_measure(part_obj, hi)

        measure_objs = sorted(
            (
                m_obj
                for m_obj in part_obj.getElementsByClass(m21.stream.Measure)
                if lo <= m_obj.number <= hi
            ),
            key=lambda m_obj: m_obj.number,
        )

        target_notes = [n for m_obj in measure_objs for n in m_obj.recurse().notes]

        range_desc = f"measure {lo}" if lo == hi else f"measures {lo}–{hi}"
        if not target_notes:
            if lo == hi:
                no_op_summary = f"Measure {lo} has no notes to transpose"
            else:
                no_op_summary = f"Measures {lo}–{hi} have no notes to transpose"
            return ToolPlan(no_op_summary=no_op_summary)

        def apply() -> tuple[list[str], str]:
            changed_ids = []
            for note_obj in target_notes:
                note_obj.transpose(interval_obj, inPlace=True)
                changed_ids.append(ids.assign_id(note_obj))

            interval_word = interval.replace("_", " ")
            article = "an" if interval_word[:1].lower() in "aeiou" else "a"
            summary = f"Transposed {range_desc} {direction} {article} {interval_word}"
            return changed_ids, summary

        return ToolPlan(apply=apply)

    return run_tool(score_id, label, planner)
