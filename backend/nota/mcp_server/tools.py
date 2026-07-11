"""Notation tool implementations as plain, importable Python functions.

Each function here is a complete tool: it validates its arguments against
the live score, applies the requested edit, and returns the structured
success/error dict described in `harness.py`. They take no MCP-specific
types, so Flask (or any other future caller) can call them directly without
going through the MCP stdio transport, and tests can exercise them without a
running server. `server.py` is a thin MCP wrapper around these functions.

Validation order, enforced in every tool below: part exists, then any
enum-valued argument (dynamic/articulation name) is checked, then measure
is in range, then beat is in range for that measure's meter, then (where a
concrete note is required) a note actually starts at that position. All of
this happens inside the tool's planner, which runs before the harness takes
an undo snapshot — so a rejected call never pollutes undo history.
"""

from __future__ import annotations

import music21 as m21

from .. import storage
from . import ids, location
from .errors import ErrorCode, ToolError
from .harness import ToolPlan, run_tool

# Dynamic markings musicians commonly dictate. music21's Dynamic class will
# happily accept any string, but the tool restricts input to this set so a
# mis-transcribed word ("half forte") surfaces as a clean, actionable error
# rather than being silently engraved.
ALLOWED_DYNAMICS = frozenset(
    {
        "pppp",
        "ppp",
        "pp",
        "p",
        "mp",
        "mf",
        "f",
        "ff",
        "fff",
        "ffff",
        "sf",
        "sfz",
        "sfp",
        "fp",
        "fz",
        "rf",
        "rfz",
    }
)

# Articulation name -> music21 articulation class. MusicXML's
# <strong-accent> (marcato) is modeled by music21 as StrongAccent.
ARTICULATION_MAP: dict[str, type] = {
    "staccato": m21.articulations.Staccato,
    "staccatissimo": m21.articulations.Staccatissimo,
    "accent": m21.articulations.Accent,
    "marcato": m21.articulations.StrongAccent,
    "tenuto": m21.articulations.Tenuto,
    "down_bow": m21.articulations.DownBow,
    "up_bow": m21.articulations.UpBow,
    "spiccato": m21.articulations.Spiccato,
}


def _format_beat(beat: float) -> str:
    return f"{beat:g}"


def add_dynamic(score_id: str, measure: int, beat: float, dynamic: str, part: str | None = None) -> dict:
    """Insert a dynamic marking (f, p, mf, sfz, ...) at a beat position.

    If an identical dynamic already exists at that exact location, this is
    a no-op that still reports success (voice commands get repeated when a
    musician isn't sure they were heard).
    """
    label = f"add_dynamic {dynamic} m{measure} b{_format_beat(beat)}"

    def planner(score: m21.stream.Score) -> ToolPlan:
        part_obj = location.resolve_part(score, part)

        if dynamic not in ALLOWED_DYNAMICS:
            raise ToolError(
                ErrorCode.INVALID_ENUM_VALUE,
                f"Unknown dynamic '{dynamic}'. Valid values: {', '.join(sorted(ALLOWED_DYNAMICS))}.",
            )

        measure_obj = location.resolve_measure(part_obj, measure)
        offset = location.resolve_beat_offset(measure_obj, beat)

        already_present = any(
            isinstance(existing, m21.dynamics.Dynamic)
            and existing.value == dynamic
            and abs(existing.offset - offset) < 1e-6
            for existing in measure_obj.recurse().getElementsByClass(m21.dynamics.Dynamic)
        )
        if already_present:
            return ToolPlan(
                no_op_summary=(
                    f"{dynamic} already present at measure {measure} beat {_format_beat(beat)}"
                )
            )

        def apply() -> tuple[list[str], str]:
            dyn_obj = m21.dynamics.Dynamic(dynamic)
            dyn_id = ids.assign_id(dyn_obj)
            measure_obj.insert(offset, dyn_obj)
            summary = f"Added {dynamic} at measure {measure}, beat {_format_beat(beat)}"
            return [dyn_id], summary

        return ToolPlan(apply=apply)

    return run_tool(score_id, label, planner)


def draw_slur(
    score_id: str,
    start_measure: int,
    start_beat: float,
    end_measure: int,
    end_beat: float,
    part: str | None = None,
) -> dict:
    """Draw a slur between two notes. Both endpoints must resolve to
    actual notes (chords count as one note).
    """
    label = (
        f"draw_slur m{start_measure}b{_format_beat(start_beat)}"
        f"-m{end_measure}b{_format_beat(end_beat)}"
    )

    def planner(score: m21.stream.Score) -> ToolPlan:
        part_obj = location.resolve_part(score, part)

        start_measure_obj = location.resolve_measure(part_obj, start_measure)
        note_start = location.find_note_at(start_measure_obj, start_beat)

        end_measure_obj = location.resolve_measure(part_obj, end_measure)
        note_end = location.find_note_at(end_measure_obj, end_beat)

        def apply() -> tuple[list[str], str]:
            slur = m21.spanner.Slur(note_start, note_end)
            # music21's MusicXML writer does not carry a Slur's own id
            # through to the <slur> element it emits (verified: it writes
            # <slur number="1" type="start/stop"> with no xml:id support
            # for spanners of this kind), so the ids that actually mean
            # something to the frontend are the two endpoint notes' ids.
            slur.id = ids.new_id()
            part_obj.insert(0, slur)

            start_id = ids.assign_id(note_start)
            end_id = ids.assign_id(note_end)
            summary = (
                f"Added slur from measure {start_measure} beat {_format_beat(start_beat)} "
                f"to measure {end_measure} beat {_format_beat(end_beat)}"
            )
            return [start_id, end_id], summary

        return ToolPlan(apply=apply)

    return run_tool(score_id, label, planner)


def add_articulation(
    score_id: str,
    measure: int,
    beat: float,
    articulation: str,
    part: str | None = None,
    end_measure: int | None = None,
    end_beat: float | None = None,
) -> dict:
    """Add an articulation/bowing mark to a note, or, when `end_measure`
    and `end_beat` are both given, to every note whose offset lies within
    [start, end] in one call (range mode). Chords count as a single note.
    """
    range_active = end_measure is not None and end_beat is not None

    if range_active:
        label = (
            f"add_articulation {articulation} m{measure}b{_format_beat(beat)}"
            f"-m{end_measure}b{_format_beat(end_beat)}"
        )
    else:
        label = f"add_articulation {articulation} m{measure}b{_format_beat(beat)}"

    def planner(score: m21.stream.Score) -> ToolPlan:
        part_obj = location.resolve_part(score, part)

        if articulation not in ARTICULATION_MAP:
            raise ToolError(
                ErrorCode.INVALID_ENUM_VALUE,
                f"Unknown articulation '{articulation}'. Valid values: "
                f"{', '.join(sorted(ARTICULATION_MAP))}.",
            )
        articulation_cls = ARTICULATION_MAP[articulation]

        start_measure_obj = location.resolve_measure(part_obj, measure)
        location.resolve_beat_offset(start_measure_obj, beat)  # validate before further resolution

        if range_active:
            end_measure_obj = location.resolve_measure(part_obj, end_measure)
            location.resolve_beat_offset(end_measure_obj, end_beat)

            notes = location.notes_in_range(part_obj, start_measure_obj, beat, end_measure_obj, end_beat)
            if not notes:
                raise ToolError(
                    ErrorCode.NO_NOTE_AT_POSITION,
                    f"No notes found between measure {measure} beat {_format_beat(beat)} "
                    f"and measure {end_measure} beat {_format_beat(end_beat)}.",
                )

            def apply() -> tuple[list[str], str]:
                changed_ids = []
                for note in notes:
                    note.articulations.append(articulation_cls())
                    changed_ids.append(ids.assign_id(note))
                summary = (
                    f"Added {articulation} to {len(changed_ids)} note"
                    f"{'s' if len(changed_ids) != 1 else ''} from measure {measure} "
                    f"beat {_format_beat(beat)} to measure {end_measure} beat {_format_beat(end_beat)}"
                )
                return changed_ids, summary

            return ToolPlan(apply=apply)

        target_note = location.find_note_at(start_measure_obj, beat)

        def apply_single() -> tuple[list[str], str]:
            target_note.articulations.append(articulation_cls())
            note_id = ids.assign_id(target_note)
            summary = f"Added {articulation} at measure {measure} beat {_format_beat(beat)}"
            return [note_id], summary

        return ToolPlan(apply=apply_single)

    return run_tool(score_id, label, planner)


def undo(score_id: str) -> dict:
    """Revert the score's most recent change by restoring the previous
    undo-stack snapshot, and push the just-reverted state onto the redo
    stack. Returns the structured success/error contract every tool uses;
    on an empty undo stack this is NOTHING_TO_UNDO rather than a no-op
    success, so a caller (Claude or the direct HTTP endpoint) can say so.
    """
    if storage.path_for(score_id) is None:
        return {
            "success": False,
            "error_code": ErrorCode.SCORE_NOT_FOUND,
            "message": f"No score with id {score_id}.",
        }

    label = storage.undo(score_id)
    if label is None:
        return {
            "success": False,
            "error_code": ErrorCode.NOTHING_TO_UNDO,
            "message": "There is nothing to undo.",
        }
    return {"success": True, "changed_element_ids": [], "summary": f"Undid: {label}"}


def redo(score_id: str) -> dict:
    """Inverse of undo(): re-apply the most recently undone change from the
    redo stack, pushing the pre-redo state back onto the undo stack.
    """
    if storage.path_for(score_id) is None:
        return {
            "success": False,
            "error_code": ErrorCode.SCORE_NOT_FOUND,
            "message": f"No score with id {score_id}.",
        }

    label = storage.redo(score_id)
    if label is None:
        return {
            "success": False,
            "error_code": ErrorCode.NOTHING_TO_REDO,
            "message": "There is nothing to redo.",
        }
    return {"success": True, "changed_element_ids": [], "summary": f"Redid: {label}"}
