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

# Hairpin direction -> music21 spanner class. "diminuendo" is accepted as a
# plain synonym for "decrescendo" (both musical terms are used
# interchangeably by musicians) and maps to the same class.
HAIRPIN_CLASSES: dict[str, type] = {
    "crescendo": m21.dynamics.Crescendo,
    "decrescendo": m21.dynamics.Diminuendo,
    "diminuendo": m21.dynamics.Diminuendo,
}

# Ornament name -> music21 expression class. All of these attach to
# note.expressions (fermata included, even though MusicXML models it as a
# notation rather than an ornament proper).
ORNAMENT_MAP: dict[str, type] = {
    "trill": m21.expressions.Trill,
    "mordent": m21.expressions.Mordent,
    "inverted_mordent": m21.expressions.InvertedMordent,
    "turn": m21.expressions.Turn,
    "tremolo": m21.expressions.Tremolo,
    "fermata": m21.expressions.Fermata,
}

# Whether music21's MusicXML writer carries an ornament object's own id
# through to the serialized element, verified empirically (rendered each
# type through the exporter and inspected the output). Trill/Mordent/
# InvertedMordent/Turn/Tremolo are written inside a <notations><ornaments>
# (or <technical>) wrapper whose child elements never receive the id the
# music21 object was given; Fermata is written as its own <notations>
# child and does keep it. Where the id is dropped, the tool falls back to
# reporting the parent note's id instead (the same fallback idea as the
# chord-id fallback in ids.py, applied to a different serialization gap).
ORNAMENT_ID_SURVIVES_EXPORT: dict[str, bool] = {
    "trill": False,
    "mordent": False,
    "inverted_mordent": False,
    "turn": False,
    "tremolo": False,
    "fermata": True,
}

# Tempo unit -> referent quarter-length, passed to
# music21.tempo.MetronomeMark(referent=...). music21 accepts a numeric
# quarter length for `referent` but not free-form strings like "dotted
# quarter" (only bare type names like "quarter"/"eighth"), so dotted values
# are expressed as their quarter-length equivalent instead.
TEMPO_UNIT_QUARTER_LENGTHS: dict[str, float] = {
    "sixteenth": 0.25,
    "eighth": 0.5,
    "dotted_eighth": 0.75,
    "quarter": 1.0,
    "dotted_quarter": 1.5,
    "half": 2.0,
    "dotted_half": 3.0,
    "whole": 4.0,
}

BPM_MIN = 10
BPM_MAX = 400

# notation_type value (for remove_notation) -> human-readable family name,
# used both for enum validation and for composing candidate descriptions.
NOTATION_TYPE_LABELS: dict[str, str] = {
    "dynamic": "dynamic",
    "hairpin": "hairpin",
    "slur": "slur",
    "articulation": "articulation",
    "ornament": "ornament",
    "text_expression": "text expression",
    "tempo": "tempo marking",
    "rehearsal_mark": "rehearsal mark",
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


def draw_hairpin(
    score_id: str,
    start_measure: int,
    start_beat: float,
    end_measure: int,
    end_beat: float,
    direction: str,
    part: str | None = None,
) -> dict:
    """Draw a crescendo/decrescendo hairpin between two notes. Both
    endpoints must resolve to actual notes (chords count as one note).
    """
    label = (
        f"draw_hairpin {direction} m{start_measure}b{_format_beat(start_beat)}"
        f"-m{end_measure}b{_format_beat(end_beat)}"
    )

    def planner(score: m21.stream.Score) -> ToolPlan:
        part_obj = location.resolve_part(score, part)

        if direction not in HAIRPIN_CLASSES:
            raise ToolError(
                ErrorCode.INVALID_ENUM_VALUE,
                f"Unknown hairpin direction '{direction}'. Valid values: "
                f"{', '.join(sorted(HAIRPIN_CLASSES))}.",
            )
        hairpin_cls = HAIRPIN_CLASSES[direction]

        start_measure_obj = location.resolve_measure(part_obj, start_measure)
        note_start = location.find_note_at(start_measure_obj, start_beat)

        end_measure_obj = location.resolve_measure(part_obj, end_measure)
        note_end = location.find_note_at(end_measure_obj, end_beat)

        def apply() -> tuple[list[str], str]:
            wedge = hairpin_cls(note_start, note_end)
            # Empirically, music21's MusicXML writer *does* carry a
            # Crescendo/Diminuendo spanner's own id through (onto both the
            # <direction> and <wedge> elements it emits at each endpoint,
            # both start and stop). The id is still not returned here:
            # draw_slur's convention is to report the two endpoint notes so
            # the frontend highlights the actual notes the marking spans,
            # and hairpins follow the same convention for consistency
            # rather than relying on Verovio carrying an id on a <wedge>
            # element through to the rendered SVG.
            wedge.id = ids.new_id()
            part_obj.insert(0, wedge)

            start_id = ids.assign_id(note_start)
            end_id = ids.assign_id(note_end)
            direction_word = "crescendo" if hairpin_cls is m21.dynamics.Crescendo else "decrescendo"
            summary = (
                f"Added {direction_word} from measure {start_measure} beat {_format_beat(start_beat)} "
                f"to measure {end_measure} beat {_format_beat(end_beat)}"
            )
            return [start_id, end_id], summary

        return ToolPlan(apply=apply)

    return run_tool(score_id, label, planner)


def add_text_expression(
    score_id: str,
    measure: int,
    beat: float,
    text: str,
    part: str | None = None,
) -> dict:
    """Insert a free-text expression (e.g. "dolce", "espressivo") at a
    beat position. Unlike add_dynamic/add_articulation, no note needs to
    start at that position — the marking is placed at the beat's offset
    within the measure either way.
    """
    label = f"add_text_expression m{measure}b{_format_beat(beat)}"

    def planner(score: m21.stream.Score) -> ToolPlan:
        part_obj = location.resolve_part(score, part)

        if text is None or not text.strip():
            raise ToolError(ErrorCode.TEXT_REQUIRED, "Text expression text cannot be empty.")
        clean_text = text.strip()

        measure_obj = location.resolve_measure(part_obj, measure)
        offset = location.resolve_beat_offset(measure_obj, beat)

        def apply() -> tuple[list[str], str]:
            expr = m21.expressions.TextExpression(clean_text)
            measure_obj.insert(offset, expr)

            # A TextExpression's own id is dropped by music21's MusicXML
            # writer (the <words> element it produces is never passed
            # through synchronizeIds), so there is nothing of the tool's
            # own creation to report. Fall back to the note at that exact
            # position, if one happens to be there, purely as a
            # best-effort highlighting anchor; if nothing starts there,
            # there is simply nothing to highlight.
            anchor = location.note_at_offset_or_none(measure_obj, offset)
            changed_ids = [ids.assign_id(anchor)] if anchor is not None else []

            summary = f'Added text "{clean_text}" at measure {measure}, beat {_format_beat(beat)}'
            return changed_ids, summary

        return ToolPlan(apply=apply)

    return run_tool(score_id, label, planner)


def add_tempo(
    score_id: str,
    measure: int,
    bpm: float | None = None,
    text: str | None = None,
    unit: str | None = None,
    part: str | None = None,
) -> dict:
    """Insert a tempo marking at the start of a measure (beat 1 — tempo
    marks are measure-level, not tied to a specific beat). At least one of
    `bpm`/`text` is required; `unit` (defaults to quarter) is the beat
    unit the bpm number refers to.
    """
    label = f"add_tempo m{measure}"

    def planner(score: m21.stream.Score) -> ToolPlan:
        part_obj = location.resolve_part(score, part)

        clean_text = text.strip() if text else None
        if bpm is None and not clean_text:
            raise ToolError(
                ErrorCode.TEXT_REQUIRED,
                "add_tempo requires at least a bpm, a text marking (e.g. 'Andante'), or both.",
            )

        resolved_unit = unit or "quarter"
        if resolved_unit not in TEMPO_UNIT_QUARTER_LENGTHS:
            raise ToolError(
                ErrorCode.INVALID_ENUM_VALUE,
                f"Unknown tempo unit '{unit}'. Valid values: "
                f"{', '.join(sorted(TEMPO_UNIT_QUARTER_LENGTHS))}.",
            )

        if bpm is not None and not (BPM_MIN <= bpm <= BPM_MAX):
            raise ToolError(
                ErrorCode.INVALID_ENUM_VALUE,
                f"bpm {bpm} is out of range. Valid range is {BPM_MIN}-{BPM_MAX}.",
            )

        measure_obj = location.resolve_measure(part_obj, measure)

        def apply() -> tuple[list[str], str]:
            kwargs: dict = {"referent": TEMPO_UNIT_QUARTER_LENGTHS[resolved_unit]}
            if bpm is not None:
                kwargs["number"] = bpm
            if clean_text:
                kwargs["text"] = clean_text
            mark = m21.tempo.MetronomeMark(**kwargs)
            mark_id = ids.assign_id(mark)
            measure_obj.insert(0, mark)

            descriptors = []
            if bpm is not None:
                descriptors.append(f"{bpm} bpm")
            if clean_text:
                descriptors.append(f"'{clean_text}'")
            summary = f"Added tempo marking ({', '.join(descriptors)}) at measure {measure}"
            return [mark_id], summary

        return ToolPlan(apply=apply)

    return run_tool(score_id, label, planner)


def add_rehearsal_mark(
    score_id: str,
    measure: int,
    label: str,
    part: str | None = None,
) -> dict:
    """Insert a rehearsal mark (e.g. "A", "B", "Coda") at the start of a
    measure. If the same label is already present at that measure, this is
    a no-op that still reports success, matching add_dynamic's dedupe
    behavior for repeated voice commands.
    """
    undo_label = f"add_rehearsal_mark m{measure}"

    def planner(score: m21.stream.Score) -> ToolPlan:
        part_obj = location.resolve_part(score, part)

        if label is None or not label.strip():
            raise ToolError(ErrorCode.TEXT_REQUIRED, "Rehearsal mark label cannot be empty.")
        clean_label = label.strip()

        measure_obj = location.resolve_measure(part_obj, measure)

        already_present = any(
            isinstance(existing, m21.expressions.RehearsalMark) and existing.content == clean_label
            for existing in measure_obj.recurse().getElementsByClass(m21.expressions.RehearsalMark)
        )
        if already_present:
            return ToolPlan(
                no_op_summary=f"Rehearsal mark '{clean_label}' already present at measure {measure}"
            )

        def apply() -> tuple[list[str], str]:
            mark = m21.expressions.RehearsalMark(clean_label)
            measure_obj.insert(0, mark)

            # Like TextExpression, RehearsalMark's own id is dropped by
            # music21's MusicXML writer, so fall back to the note at the
            # start of the measure (if any) as a highlighting anchor.
            anchor = location.note_at_offset_or_none(measure_obj, 0)
            changed_ids = [ids.assign_id(anchor)] if anchor is not None else []

            summary = f"Added rehearsal mark '{clean_label}' at measure {measure}"
            return changed_ids, summary

        return ToolPlan(apply=apply)

    return run_tool(score_id, undo_label, planner)


def add_ornament(
    score_id: str,
    measure: int,
    beat: float,
    ornament: str,
    part: str | None = None,
) -> dict:
    """Attach an ornament (trill, mordent, inverted_mordent, turn,
    tremolo, fermata) to the note at a beat position. Must target a real
    note (chords count as one note).
    """
    label = f"add_ornament {ornament} m{measure}b{_format_beat(beat)}"

    def planner(score: m21.stream.Score) -> ToolPlan:
        part_obj = location.resolve_part(score, part)

        if ornament not in ORNAMENT_MAP:
            raise ToolError(
                ErrorCode.INVALID_ENUM_VALUE,
                f"Unknown ornament '{ornament}'. Valid values: {', '.join(sorted(ORNAMENT_MAP))}.",
            )
        ornament_cls = ORNAMENT_MAP[ornament]

        measure_obj = location.resolve_measure(part_obj, measure)
        target_note = location.find_note_at(measure_obj, beat)

        def apply() -> tuple[list[str], str]:
            ornament_obj = ornament_cls()
            target_note.expressions.append(ornament_obj)

            if ORNAMENT_ID_SURVIVES_EXPORT[ornament]:
                changed_ids = [ids.assign_id(ornament_obj)]
            else:
                changed_ids = [ids.assign_id(target_note)]

            summary = f"Added {ornament.replace('_', ' ')} at measure {measure} beat {_format_beat(beat)}"
            return changed_ids, summary

        return ToolPlan(apply=apply)

    return run_tool(score_id, label, planner)


# ---------------------------------------------------------------------------
# remove_notation: candidate discovery across every notation family the
# tools above create, disambiguation, and removal.


def _describe_articulation(art_obj) -> str:
    reverse = {cls: name for name, cls in ARTICULATION_MAP.items()}
    name = reverse.get(type(art_obj), art_obj.__class__.__name__.lower()).replace("_", " ")
    return f"a {name}"


def _describe_ornament(orn_obj) -> str:
    reverse = {cls: name for name, cls in ORNAMENT_MAP.items()}
    name = reverse.get(type(orn_obj), orn_obj.__class__.__name__.lower()).replace("_", " ")
    article = "an" if name[:1] in "aeiou" else "a"
    return f"{article} {name}"


def _describe_hairpin(wedge_obj) -> str:
    kind = "crescendo" if isinstance(wedge_obj, m21.dynamics.Crescendo) else "decrescendo"
    return f"a {kind} hairpin"


def _offset_matches(offset: float, target_offset: float | None) -> bool:
    return target_offset is None or abs(offset - target_offset) < 1e-6


def _spanner_touches_measure(spanner_obj, measure_obj, target_offset: float | None) -> bool:
    for endpoint in spanner_obj.getSpannedElements():
        if endpoint.getContextByClass(m21.stream.Measure) is not measure_obj:
            continue
        if target_offset is None:
            return True
        if _offset_matches(endpoint.getOffsetInHierarchy(measure_obj), target_offset):
            return True
    return False


def _find_removal_candidates(
    part_obj, measure_obj, target_offset: float | None, families: set[str]
) -> list[dict]:
    """Return every notation-family candidate at `measure_obj` (optionally
    filtered to a single beat's offset via `target_offset`) whose family is
    in `families`. Each candidate is a dict with a human-readable
    `description` and a zero-arg `remove` callable.
    """
    candidates: list[dict] = []

    if "dynamic" in families:
        for dyn in measure_obj.recurse().getElementsByClass(m21.dynamics.Dynamic):
            if _offset_matches(dyn.getOffsetInHierarchy(measure_obj), target_offset):
                site = dyn.activeSite
                candidates.append(
                    {
                        "family": "dynamic",
                        "description": f"a {dyn.value} dynamic",
                        "remove": (lambda obj=dyn, s=site: s.remove(obj)),
                    }
                )

    if "text_expression" in families:
        for te in measure_obj.recurse().getElementsByClass(m21.expressions.TextExpression):
            if _offset_matches(te.getOffsetInHierarchy(measure_obj), target_offset):
                site = te.activeSite
                candidates.append(
                    {
                        "family": "text_expression",
                        "description": f'the text "{te.content}"',
                        "remove": (lambda obj=te, s=site: s.remove(obj)),
                    }
                )

    if "rehearsal_mark" in families:
        for rm in measure_obj.recurse().getElementsByClass(m21.expressions.RehearsalMark):
            if _offset_matches(rm.getOffsetInHierarchy(measure_obj), target_offset):
                site = rm.activeSite
                candidates.append(
                    {
                        "family": "rehearsal_mark",
                        "description": f'a rehearsal mark "{rm.content}"',
                        "remove": (lambda obj=rm, s=site: s.remove(obj)),
                    }
                )

    if "tempo" in families:
        for mark in measure_obj.recurse().getElementsByClass(m21.tempo.MetronomeMark):
            if _offset_matches(mark.getOffsetInHierarchy(measure_obj), target_offset):
                site = mark.activeSite
                candidates.append(
                    {
                        "family": "tempo",
                        "description": "a tempo marking",
                        "remove": (lambda obj=mark, s=site: s.remove(obj)),
                    }
                )

    if "articulation" in families:
        for note_obj in measure_obj.recurse().notes:
            if not _offset_matches(note_obj.getOffsetInHierarchy(measure_obj), target_offset):
                continue
            for art in list(note_obj.articulations):
                candidates.append(
                    {
                        "family": "articulation",
                        "description": _describe_articulation(art),
                        "remove": (lambda n=note_obj, a=art: n.articulations.remove(a)),
                    }
                )

    if "ornament" in families:
        for note_obj in measure_obj.recurse().notes:
            if not _offset_matches(note_obj.getOffsetInHierarchy(measure_obj), target_offset):
                continue
            for expr in list(note_obj.expressions):
                if isinstance(expr, (m21.expressions.Ornament, m21.expressions.Fermata)):
                    candidates.append(
                        {
                            "family": "ornament",
                            "description": _describe_ornament(expr),
                            "remove": (lambda n=note_obj, e=expr: n.expressions.remove(e)),
                        }
                    )

    if "slur" in families:
        for slur in part_obj.recurse().getElementsByClass(m21.spanner.Slur):
            if _spanner_touches_measure(slur, measure_obj, target_offset):
                candidates.append(
                    {
                        "family": "slur",
                        "description": "a slur",
                        "remove": (lambda s=slur: part_obj.remove(s)),
                    }
                )

    if "hairpin" in families:
        for wedge in part_obj.recurse().getElementsByClass((m21.dynamics.Crescendo, m21.dynamics.Diminuendo)):
            if _spanner_touches_measure(wedge, measure_obj, target_offset):
                candidates.append(
                    {
                        "family": "hairpin",
                        "description": _describe_hairpin(wedge),
                        "remove": (lambda s=wedge: part_obj.remove(s)),
                    }
                )

    return candidates


def _join_descriptions(descriptions: list[str]) -> str:
    if len(descriptions) == 1:
        return descriptions[0]
    if len(descriptions) == 2:
        return f"{descriptions[0]} and {descriptions[1]}"
    return ", ".join(descriptions[:-1]) + f", and {descriptions[-1]}"


def remove_notation(
    score_id: str,
    measure: int,
    beat: float | None = None,
    notation_type: str | None = None,
    part: str | None = None,
) -> dict:
    """Remove a notation marking at a measure (optionally narrowed to a
    beat and/or a notation family). If exactly one marking matches, it is
    removed. If several match, returns AMBIGUOUS_TARGET listing each
    candidate so the caller can narrow with `notation_type` or `beat`. If
    none match, returns NOTHING_TO_REMOVE.
    """
    undo_label = f"remove_notation m{measure}" + (
        f"b{_format_beat(beat)}" if beat is not None else ""
    ) + (f" {notation_type}" if notation_type else "")

    def planner(score: m21.stream.Score) -> ToolPlan:
        part_obj = location.resolve_part(score, part)

        if notation_type is not None and notation_type not in NOTATION_TYPE_LABELS:
            raise ToolError(
                ErrorCode.INVALID_ENUM_VALUE,
                f"Unknown notation_type '{notation_type}'. Valid values: "
                f"{', '.join(sorted(NOTATION_TYPE_LABELS))}.",
            )
        families = {notation_type} if notation_type else set(NOTATION_TYPE_LABELS)

        measure_obj = location.resolve_measure(part_obj, measure)
        target_offset = location.resolve_beat_offset(measure_obj, beat) if beat is not None else None

        location_phrase = f"measure {measure}" + (
            f" beat {_format_beat(beat)}" if beat is not None else ""
        )

        candidates = _find_removal_candidates(part_obj, measure_obj, target_offset, families)

        if not candidates:
            family_label = NOTATION_TYPE_LABELS[notation_type] if notation_type else "notation"
            hint = ""
            if beat is not None:
                wider = _find_removal_candidates(part_obj, measure_obj, None, families)
                if wider:
                    other_descriptions = sorted({c["description"] for c in wider})
                    hint = f" There is {_join_descriptions(other_descriptions)} elsewhere in that measure."
            raise ToolError(
                ErrorCode.NOTHING_TO_REMOVE,
                f"No {family_label} found at {location_phrase}.{hint}",
            )

        if len(candidates) > 1:
            descriptions = [c["description"] for c in candidates]
            raise ToolError(
                ErrorCode.AMBIGUOUS_TARGET,
                f"Found {_join_descriptions(descriptions)} at {location_phrase} — which one? "
                "Call again with notation_type to specify.",
            )

        candidate = candidates[0]

        def apply() -> tuple[list[str], str]:
            candidate["remove"]()
            summary = f"Removed {candidate['description']} at {location_phrase}"
            return [], summary

        return ToolPlan(apply=apply)

    return run_tool(score_id, undo_label, planner)


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
