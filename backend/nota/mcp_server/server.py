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

from . import tools
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
                "ornament, text_expression, tempo, rehearsal_mark."
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
