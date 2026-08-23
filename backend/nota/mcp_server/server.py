"""MCP stdio server exposing the notation tools in `tools.py`.

Thin wrapper only: every tool here does nothing but forward its arguments
to the corresponding plain function and return the structured result dict.
All parsing, validation, mutation, and persistence logic lives in
`tools.py`/`harness.py`/`location.py` so it can be exercised directly in
tests (and, later, called straight from Flask) without going through MCP at
all.

Runnable standalone with only `DATABASE_URL` and `SCORE_STORAGE_DIR` set in
the environment (see `nota.storage.ensure_initialized`, which every tool
call triggers indirectly via `nota.storage.path_for`): `python -m
nota.mcp_server`.
"""

from __future__ import annotations

from typing import Annotated, Optional

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from . import pitch_tools, rhythm_tools, tools
from .. import storage

mcp = FastMCP(
    name="nota-notation-tools",
    instructions=(
        "Tools for editing a music notation score stored by the Nota backend. "
        "Every tool requires score_id, identifying which score to edit; measures "
        "and beats are 1-based and counted the way a musician would count them "
        "(e.g. beat 1 is the downbeat; a 6/8 measure has 2 beats). Measure 0 is "
        "only valid for scores with a pickup measure. Every tool returns "
        "{success: true, changed_element_ids, summary} on success or "
        "{success: false, error_code, message} on failure; on failure, relay "
        "the message to the user rather than retrying blindly."
    ),
)

ScoreId = Annotated[str, Field(description="The id of the score to edit.")]
PartArg = Annotated[
    Optional[str],
    Field(
        default=None,
        description=(
            "Name (or internal id) of the part/instrument to edit, e.g. 'Violin I'. "
            "Omit for single-part scores or to target the first part."
        ),
    ),
]
MeasureArg = Annotated[
    int,
    Field(description="1-based measure number. Use 0 only if the score has a pickup measure."),
]
BeatArg = Annotated[
    float,
    Field(
        description=(
            "1-based beat within the measure, counted the way a musician counts "
            "(beat 1 is the downbeat). Fractional beats (e.g. 1.5) address off-beat "
            "positions. The valid range depends on the measure's time signature."
        )
    ),
]


@mcp.tool(
    description=(
        "Add a dynamic marking (e.g. p, mf, f, sfz) at a measure/beat. If the same "
        "dynamic is already present at that exact position, this is a no-op that "
        "still reports success — safe to call again if unsure a command landed."
    )
)
def add_dynamic(
    score_id: ScoreId,
    measure: MeasureArg,
    beat: BeatArg,
    dynamic: Annotated[
        str,
        Field(description="Dynamic marking, e.g. 'pp', 'p', 'mp', 'mf', 'f', 'ff', 'sfz', 'fp'."),
    ],
    part: PartArg = None,
) -> dict:
    return tools.add_dynamic(score_id, measure=measure, beat=beat, dynamic=dynamic, part=part)


@mcp.tool(
    description=(
        "Draw a slur between two notes identified by their measure/beat positions. "
        "Both positions must have an actual note (or chord) starting there."
    )
)
def draw_slur(
    score_id: ScoreId,
    start_measure: MeasureArg,
    start_beat: BeatArg,
    end_measure: MeasureArg,
    end_beat: BeatArg,
    part: PartArg = None,
) -> dict:
    return tools.draw_slur(
        score_id,
        start_measure=start_measure,
        start_beat=start_beat,
        end_measure=end_measure,
        end_beat=end_beat,
        part=part,
    )


@mcp.tool(
    description=(
        "Add an articulation or bowing mark to a note. Provide only measure/beat "
        "to mark a single note. Provide end_measure and end_beat as well to apply "
        "the same articulation to every note between the start and end positions "
        "(inclusive) in one call — use this for range commands like 'staccato in "
        "measures 8 through 12' instead of calling this tool once per note."
    )
)
def add_articulation(
    score_id: ScoreId,
    measure: MeasureArg,
    beat: BeatArg,
    articulation: Annotated[
        str,
        Field(
            description=(
                "One of: staccato, staccatissimo, accent, marcato, tenuto, "
                "down_bow, up_bow, spiccato."
            )
        ),
    ],
    part: PartArg = None,
    end_measure: Annotated[
        Optional[int],
        Field(default=None, description="End of a range; provide together with end_beat."),
    ] = None,
    end_beat: Annotated[
        Optional[float],
        Field(default=None, description="End of a range; provide together with end_measure."),
    ] = None,
) -> dict:
    return tools.add_articulation(
        score_id,
        measure=measure,
        beat=beat,
        articulation=articulation,
        part=part,
        end_measure=end_measure,
        end_beat=end_beat,
    )


@mcp.tool(
    description=(
        "Draw a crescendo or decrescendo hairpin between two notes identified by "
        "their measure/beat positions. Both positions must have an actual note "
        "(or chord) starting there."
    )
)
def draw_hairpin(
    score_id: ScoreId,
    start_measure: MeasureArg,
    start_beat: BeatArg,
    end_measure: MeasureArg,
    end_beat: BeatArg,
    direction: Annotated[
        str,
        Field(
            description=(
                "One of: crescendo, decrescendo. 'diminuendo' is also accepted as a "
                "synonym for decrescendo."
            )
        ),
    ],
    part: PartArg = None,
) -> dict:
    return tools.draw_hairpin(
        score_id,
        start_measure=start_measure,
        start_beat=start_beat,
        end_measure=end_measure,
        end_beat=end_beat,
        direction=direction,
        part=part,
    )


@mcp.tool(
    description=(
        "Add a free-text expression marking (e.g. 'dolce', 'espressivo', 'sotto "
        "voce') at a measure/beat. Unlike dynamics or articulations, no note has "
        "to start exactly at that position."
    )
)
def add_text_expression(
    score_id: ScoreId,
    measure: MeasureArg,
    beat: BeatArg,
    text: Annotated[str, Field(description="The expression text to display, e.g. 'dolce'.")],
    part: PartArg = None,
) -> dict:
    return tools.add_text_expression(score_id, measure=measure, beat=beat, text=text, part=part)


@mcp.tool(
    description=(
        "Add a tempo marking at the start of a measure (tempo marks are "
        "measure-level, not tied to a specific beat). Provide bpm, text (e.g. "
        "'Andante'), or both — at least one is required."
    )
)
def add_tempo(
    score_id: ScoreId,
    measure: MeasureArg,
    bpm: Annotated[
        Optional[float],
        Field(default=None, description="Beats per minute, in the range 10-400."),
    ] = None,
    text: Annotated[
        Optional[str],
        Field(default=None, description="Tempo text, e.g. 'Andante', 'Allegro con brio'."),
    ] = None,
    unit: Annotated[
        Optional[str],
        Field(
            default=None,
            description=(
                "The note value the bpm number refers to. One of: sixteenth, eighth, "
                "dotted_eighth, quarter, dotted_quarter, half, dotted_half, whole. "
                "Defaults to quarter."
            ),
        ),
    ] = None,
    part: PartArg = None,
) -> dict:
    return tools.add_tempo(score_id, measure=measure, bpm=bpm, text=text, unit=unit, part=part)


@mcp.tool(
    description=(
        "Add a rehearsal mark (e.g. 'A', 'B', 'Coda') at the start of a measure. "
        "If the same label is already present at that measure, this is a no-op "
        "that still reports success — safe to call again if unsure a command landed."
    )
)
def add_rehearsal_mark(
    score_id: ScoreId,
    measure: MeasureArg,
    label: Annotated[str, Field(description="The rehearsal mark's text, e.g. 'A' or 'Coda'.")],
    part: PartArg = None,
) -> dict:
    return tools.add_rehearsal_mark(score_id, measure=measure, label=label, part=part)


@mcp.tool(
    description=(
        "Attach an ornament to the note at a measure/beat. Must target a note "
        "(or chord) starting there."
    )
)
def add_ornament(
    score_id: ScoreId,
    measure: MeasureArg,
    beat: BeatArg,
    ornament: Annotated[
        str,
        Field(
            description=(
                "One of: trill, mordent, inverted_mordent, turn, tremolo, fermata."
            )
        ),
    ],
    part: PartArg = None,
) -> dict:
    return tools.add_ornament(score_id, measure=measure, beat=beat, ornament=ornament, part=part)


@mcp.tool(
    description=(
        "Attach a fingering number to the note at a measure/beat. 0 means an "
        "open string. If the same finger number is already on that note, this "
        "is a no-op that still reports success — safe to call again if unsure "
        "a command landed."
    )
)
def add_fingering(
    score_id: ScoreId,
    measure: MeasureArg,
    beat: BeatArg,
    finger: Annotated[
        int,
        Field(description="Finger number, 0-5 (0 = open string)."),
    ],
    part: PartArg = None,
) -> dict:
    return tools.add_fingering(score_id, measure=measure, beat=beat, finger=finger, part=part)


@mcp.tool(
    description=(
        "Remove a notation marking at a measure, optionally narrowed to a beat "
        "and/or a notation_type. If more than one marking matches, this returns "
        "AMBIGUOUS_TARGET listing each candidate so you can ask the user which one "
        "they mean, then call again with notation_type (and/or beat) to disambiguate. "
        "If nothing matches, returns NOTHING_TO_REMOVE."
    )
)
def remove_notation(
    score_id: ScoreId,
    measure: MeasureArg,
    beat: Annotated[
        Optional[float],
        Field(default=None, description="Narrow the search to a single beat within the measure."),
    ] = None,
    notation_type: Annotated[
        Optional[str],
        Field(
            default=None,
            description=(
                "Narrow the search to one family: dynamic, hairpin, slur, articulation, "
                "ornament, text_expression, tempo, rehearsal_mark, fingering."
            ),
        ),
    ] = None,
    part: PartArg = None,
) -> dict:
    return tools.remove_notation(
        score_id, measure=measure, beat=beat, notation_type=notation_type, part=part
    )


@mcp.tool(
    description=(
        "Change the pitch of an existing note, keeping its duration and any "
        "attached markings. Target the note by beat, or by from_pitch (its "
        "current pitch) when no beat was given — e.g. 'change the F in bar 3 "
        "to F sharp'. A chord requires from_pitch to say which of its notes to "
        "change. If the note is tied, the whole tied group changes together. "
        "A pitch with no octave number lands in the octave nearest the note's "
        "current pitch."
    )
)
def change_pitch(
    score_id: ScoreId,
    measure: MeasureArg,
    pitch: Annotated[
        str,
        Field(
            description=(
                "The new pitch, e.g. 'C#', 'B flat', 'F natural', optionally with an "
                "octave number: 'C#4'."
            )
        ),
    ],
    beat: Annotated[
        Optional[float],
        Field(default=None, description="Beat the note starts on. Omit to target by from_pitch."),
    ] = None,
    from_pitch: Annotated[
        Optional[str],
        Field(
            default=None,
            description=(
                "The note's current pitch, e.g. 'F' or 'Bb4'. Required when no beat is "
                "given, or when the target is a chord (to pick which of its notes)."
            ),
        ),
    ] = None,
    part: PartArg = None,
) -> dict:
    return pitch_tools.change_pitch(
        score_id, measure=measure, pitch=pitch, beat=beat, from_pitch=from_pitch, part=part
    )


@mcp.tool(
    description=(
        "Transpose every note in a measure range by a named interval, e.g. "
        "'transpose measures 1 through 8 up an octave'. Omit end_measure to "
        "transpose a single measure."
    )
)
def transpose(
    score_id: ScoreId,
    interval: Annotated[
        str,
        Field(description="One of: octave, half_step, semitone, whole_step, whole_tone, minor_second, major_second, minor_third, major_third, perfect_fourth, tritone, perfect_fifth, minor_sixth, major_sixth, minor_seventh, major_seventh."),
    ],
    direction: Annotated[str, Field(description="'up' or 'down'.")],
    start_measure: MeasureArg,
    end_measure: Annotated[
        Optional[int],
        Field(default=None, description="Last measure of the range. Omit for a single measure."),
    ] = None,
    part: PartArg = None,
) -> dict:
    return pitch_tools.transpose(
        score_id,
        interval=interval,
        direction=direction,
        start_measure=start_measure,
        end_measure=end_measure,
        part=part,
    )


@mcp.tool(
    description=(
        "Write a note at a measure/beat, overwriting whatever currently occupies "
        "that time span (a partially covered note keeps its remainder as a rest; "
        "nothing shifts). The duration must fit inside the measure — a value that "
        "would cross the barline returns DURATION_CROSSES_BARLINE. A pitch with "
        "no octave number lands in the octave nearest the surrounding notes."
    )
)
def add_note(
    score_id: ScoreId,
    measure: MeasureArg,
    beat: BeatArg,
    pitch: Annotated[
        str,
        Field(
            description=(
                "The pitch to write, e.g. 'C#', 'B flat', optionally with an octave "
                "number: 'C#4'."
            )
        ),
    ],
    duration: Annotated[
        str,
        Field(description="One of: whole, dotted_whole, half, dotted_half, quarter, dotted_quarter, eighth, dotted_eighth, sixteenth, dotted_sixteenth, thirty_second."),
    ],
    part: PartArg = None,
) -> dict:
    return rhythm_tools.add_note(
        score_id, measure=measure, beat=beat, pitch=pitch, duration=duration, part=part
    )


@mcp.tool(
    description=(
        "Change the written duration of the note starting at a measure/beat, "
        "keeping its pitch and attached markings. Lengthening overwrites what "
        "follows within the measure; shortening fills the freed time with a rest."
    )
)
def set_duration(
    score_id: ScoreId,
    measure: MeasureArg,
    beat: BeatArg,
    duration: Annotated[
        str,
        Field(description="One of: whole, dotted_whole, half, dotted_half, quarter, dotted_quarter, eighth, dotted_eighth, sixteenth, dotted_sixteenth, thirty_second."),
    ],
    part: PartArg = None,
) -> dict:
    return rhythm_tools.set_duration(
        score_id, measure=measure, beat=beat, duration=duration, part=part
    )


@mcp.tool(
    description=(
        "Delete notes, replacing them with rests of the same length (nothing "
        "shifts). With measure and beat: the single note starting there — also "
        "use this for 'put a rest on beat 2'. With only measure: clears the "
        "whole measure to rests. With end_measure (and optionally end_beat): "
        "clears the whole range."
    )
)
def delete_note(
    score_id: ScoreId,
    measure: MeasureArg,
    beat: Annotated[
        Optional[float],
        Field(default=None, description="Beat the note starts on. Omit to clear the whole measure."),
    ] = None,
    end_measure: Annotated[
        Optional[int],
        Field(default=None, description="Last measure of a range to clear. Omit for a single measure."),
    ] = None,
    end_beat: Annotated[
        Optional[float],
        Field(
            default=None,
            description=(
                "Beat in end_measure the cleared range runs through (the note starting "
                "there is included). Omit to clear through the end of end_measure."
            ),
        ),
    ] = None,
    part: PartArg = None,
) -> dict:
    return rhythm_tools.delete_note(
        score_id,
        measure=measure,
        beat=beat,
        end_measure=end_measure,
        end_beat=end_beat,
        part=part,
    )


@mcp.tool(
    description=(
        "Undo the most recent change to the score. Use this for phrases like "
        "'undo', 'go back', 'never mind', or 'undo that'. Returns NOTHING_TO_UNDO "
        "if there is no change to undo."
    )
)
def undo(score_id: ScoreId) -> dict:
    return tools.undo(score_id)


@mcp.tool(
    description=(
        "Redo the most recently undone change to the score. Use this for phrases "
        "like 'redo', 'redo that', or 'put it back'. Returns NOTHING_TO_REDO if "
        "there is no change to redo."
    )
)
def redo(score_id: ScoreId) -> dict:
    return tools.redo(score_id)


def main() -> None:
    """Entry point for `python -m nota.mcp_server`."""
    storage.ensure_initialized()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
