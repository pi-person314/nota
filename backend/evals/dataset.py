"""The eval dataset: spoken-command transcripts paired with the tool calls
(or lack of them) the orchestrator is expected to produce.

Every case runs against a fresh copy of the sixteen-measure fixture score
(see `evals/fixture.py`) unless it declares `setup_transcripts`, in which
case those transcripts run first through the *same* score (building
server-side `CommandLog` history) before the scored transcript -- this is
how context carry-over ("beat 3" with no measure, "same thing at measure
15") is tested without the runner having to fake conversation state itself.

Helper functions below keep individual cases terse:

    tc(tool, **args)          -- one expected {tool, args} entry
    expect_tools(*calls)      -- pass iff exactly these tool calls happened
                                  (any bijection unless ordered=True)
    expect_no_tools()         -- pass iff zero tools were called and Claude
                                  produced a clarifying/correcting response
    expect_any_of(*expects)   -- pass iff any one alternative expectation
                                  passes (for genuinely acceptable variants,
                                  e.g. "decrescendo" vs. "diminuendo")
    case(id, category, transcript, expectation, setup_transcripts=None)

See `evals/scoring.py` for exactly how each expectation shape is matched,
and `evals/README.md` for how to add a case.
"""

from __future__ import annotations

CATEGORIES = (
    "simple",
    "synonyms",
    "ranges",
    "compound",
    "transcription_artifacts",
    "context_carryover",
    "undo_redo",
    "out_of_range",
    "ambiguous",
)


def tc(tool: str, **args) -> dict:
    return {"tool": tool, "args": args}


def expect_tools(*calls: dict, ordered: bool = False) -> dict:
    return {"tool_calls": list(calls), "ordered": ordered}


def expect_no_tools() -> dict:
    return {"no_tools": True, "expect_clarification_or_correction": True}


def expect_any_of(*expectations: dict) -> dict:
    return {"any_of": list(expectations)}


def case(
    id: str,
    category: str,
    transcript: str,
    expectation: dict,
    setup_transcripts: list[str] | None = None,
) -> dict:
    return {
        "id": id,
        "category": category,
        "transcript": transcript,
        "expectation": expectation,
        "setup_transcripts": list(setup_transcripts or []),
    }


CASES: list[dict] = [
    # -- simple: one case per tool -------------------------------------------
    case(
        "simple_add_dynamic",
        "simple",
        "forte at measure 12 beat 1",
        expect_tools(tc("add_dynamic", measure=12, beat=1, dynamic="f")),
    ),
    case(
        "simple_draw_slur",
        "simple",
        "slur from measure 3 beat 1 to measure 4 beat 2",
        expect_tools(tc("draw_slur", start_measure=3, start_beat=1, end_measure=4, end_beat=2)),
    ),
    case(
        "simple_add_articulation",
        "simple",
        "staccato on beat 2 of measure 5",
        expect_tools(tc("add_articulation", measure=5, beat=2, articulation="staccato")),
    ),
    case(
        "simple_draw_hairpin",
        "simple",
        "crescendo from bar 2 beat 1 to bar 3 beat 1",
        expect_tools(
            tc("draw_hairpin", start_measure=2, start_beat=1, end_measure=3, end_beat=1, direction="crescendo")
        ),
    ),
    case(
        "simple_add_text_expression",
        "simple",
        "write dolce at measure 6 beat 1",
        expect_tools(tc("add_text_expression", measure=6, beat=1, text="dolce")),
    ),
    case(
        "simple_add_tempo",
        "simple",
        "quarter equals 120 at measure 1",
        expect_tools(tc("add_tempo", measure=1, bpm=120)),
    ),
    case(
        "simple_add_rehearsal_mark",
        "simple",
        "rehearsal mark A at measure 10",
        expect_tools(tc("add_rehearsal_mark", measure=10, label="A")),
    ),
    case(
        "simple_add_ornament",
        "simple",
        "trill on beat 2 of measure 5",
        expect_tools(tc("add_ornament", measure=5, beat=2, ornament="trill")),
    ),
    case(
        "simple_add_fingering",
        "simple",
        "third finger on beat 2 of measure 5",
        expect_tools(tc("add_fingering", measure=5, beat=2, finger=3)),
    ),
    case(
        "simple_remove_notation",
        "simple",
        "remove the dynamic at measure 12 beat 1",
        expect_tools(tc("remove_notation", measure=12, beat=1)),
        setup_transcripts=["forte at measure 12 beat 1"],
    ),
    case(
        "simple_undo",
        "simple",
        "undo that",
        expect_tools(tc("undo")),
        setup_transcripts=["forte at measure 4 beat 1"],
    ),
    case(
        "simple_redo",
        "simple",
        "redo that",
        expect_tools(tc("redo")),
        setup_transcripts=["forte at measure 4 beat 1", "undo that"],
    ),
    case(
        "simple_change_pitch",
        "simple",
        "change the note at measure 4 beat 2 to a C sharp",
        expect_tools(tc("change_pitch", measure=4, beat=2)),
    ),
    case(
        "simple_add_note",
        "simple",
        "add a quarter note G on beat 3 of measure 5",
        expect_tools(tc("add_note", measure=5, beat=3, duration="quarter")),
    ),
    case(
        "simple_set_duration",
        "simple",
        "make the note at measure 6 beat 1 a half note",
        expect_tools(tc("set_duration", measure=6, beat=1, duration="half")),
    ),
    case(
        "simple_delete_note",
        "simple",
        "delete the note at measure 7 beat 2",
        expect_tools(tc("delete_note", measure=7, beat=2)),
    ),
    case(
        "simple_transpose",
        "simple",
        "transpose measures 1 through 8 up an octave",
        expect_tools(
            tc("transpose", interval="octave", direction="up", start_measure=1, end_measure=8)
        ),
    ),
    # -- synonyms --------------------------------------------------------------
    case(
        "syn_bar_for_measure",
        "synonyms",
        "bar 5 beat 1 mezzo forte",
        expect_tools(tc("add_dynamic", measure=5, beat=1, dynamic="mf")),
    ),
    case(
        "syn_cresc",
        "synonyms",
        "cresc from measure 1 beat 1 to measure 2 beat 1",
        expect_tools(
            tc("draw_hairpin", start_measure=1, start_beat=1, end_measure=2, end_beat=1, direction="crescendo")
        ),
    ),
    case(
        "syn_dim",
        "synonyms",
        "dim from measure 5 beat 1 to measure 6 beat 1",
        expect_any_of(
            expect_tools(
                tc("draw_hairpin", start_measure=5, start_beat=1, end_measure=6, end_beat=1, direction="decrescendo")
            ),
            expect_tools(
                tc("draw_hairpin", start_measure=5, start_beat=1, end_measure=6, end_beat=1, direction="diminuendo")
            ),
        ),
    ),
    case(
        "syn_decresc",
        "synonyms",
        "decresc from measure 7 beat 1 to measure 8 beat 1",
        expect_any_of(
            expect_tools(
                tc("draw_hairpin", start_measure=7, start_beat=1, end_measure=8, end_beat=1, direction="decrescendo")
            ),
            expect_tools(
                tc("draw_hairpin", start_measure=7, start_beat=1, end_measure=8, end_beat=1, direction="diminuendo")
            ),
        ),
    ),
    case(
        "syn_stacc",
        "synonyms",
        "stacc on beat 3 of measure 9",
        expect_tools(tc("add_articulation", measure=9, beat=3, articulation="staccato")),
    ),
    case(
        "syn_marc",
        "synonyms",
        "marc on beat 1 of measure 10",
        expect_tools(tc("add_articulation", measure=10, beat=1, articulation="marcato")),
    ),
    case(
        "syn_sfz",
        "synonyms",
        "put an sfz on beat 2 of bar 11",
        expect_any_of(
            expect_tools(tc("add_dynamic", measure=11, beat=2, dynamic="sfz")),
            expect_tools(tc("add_dynamic", measure=11, beat=2, dynamic="sf")),
        ),
    ),
    case(
        "syn_rest_for_delete",
        "synonyms",
        "put a rest on beat 2 of measure 3",
        expect_tools(tc("delete_note", measure=3, beat=2)),
    ),
    # -- ranges: one ranged call, never per-note calls --------------------------
    case(
        "rng_staccato_bars_8_12",
        "ranges",
        "staccato on every note from bars 8 to 12",
        expect_tools(tc("add_articulation", measure=8, beat=1, end_measure=12, articulation="staccato")),
    ),
    case(
        "rng_accent_measures_3_4",
        "ranges",
        "accent every note in measures 3 through 4",
        expect_tools(tc("add_articulation", measure=3, beat=1, end_measure=4, articulation="accent")),
    ),
    case(
        "rng_down_bow_6_7",
        "ranges",
        "down bow from measure 6 to measure 7",
        expect_tools(tc("add_articulation", measure=6, beat=1, end_measure=7, articulation="down_bow")),
    ),
    case(
        "rng_tenuto_within_measure",
        "ranges",
        "tenuto on every note from beat 2 of measure 9 to beat 4 of measure 9",
        expect_tools(
            tc("add_articulation", measure=9, beat=2, end_measure=9, end_beat=4, articulation="tenuto")
        ),
    ),
    case(
        "rng_up_bow_14_15",
        "ranges",
        "up bow on all notes from measures 14 to 15",
        expect_tools(tc("add_articulation", measure=14, beat=1, end_measure=15, articulation="up_bow")),
    ),
    # -- compound: multiple tool calls from one command --------------------------
    case(
        "cmp_dynamic_and_articulation",
        "compound",
        "forte at measure 3 beat 1 and staccato on beat 2 of measure 3",
        expect_tools(
            tc("add_dynamic", measure=3, beat=1, dynamic="f"),
            tc("add_articulation", measure=3, beat=2, articulation="staccato"),
        ),
    ),
    case(
        "cmp_two_dynamics",
        "compound",
        "piano at measure 5 beat 1 and mezzo forte at measure 6 beat 1",
        expect_tools(
            tc("add_dynamic", measure=5, beat=1, dynamic="p"),
            tc("add_dynamic", measure=6, beat=1, dynamic="mf"),
        ),
    ),
    case(
        "cmp_two_ornaments",
        "compound",
        "add a trill on beat 1 of measure 7 and a fermata on beat 3 of measure 7",
        expect_tools(
            tc("add_ornament", measure=7, beat=1, ornament="trill"),
            tc("add_ornament", measure=7, beat=3, ornament="fermata"),
        ),
    ),
    case(
        "cmp_slur_and_text",
        "compound",
        "slur from measure 2 beat 1 to measure 3 beat 1 and add dolce at measure 2 beat 1",
        expect_tools(
            tc("draw_slur", start_measure=2, start_beat=1, end_measure=3, end_beat=1),
            tc("add_text_expression", measure=2, beat=1, text="dolce"),
        ),
    ),
    case(
        "cmp_rehearsal_and_dynamic",
        "compound",
        "rehearsal mark B at measure 9 and forte at measure 9 beat 1",
        expect_tools(
            tc("add_rehearsal_mark", measure=9, label="B"),
            tc("add_dynamic", measure=9, beat=1, dynamic="f"),
        ),
    ),
    case(
        "cmp_hairpin_and_articulation",
        "compound",
        "crescendo from measure 10 beat 1 to measure 11 beat 1 and accent on beat 1 of measure 10",
        expect_tools(
            tc("draw_hairpin", start_measure=10, start_beat=1, end_measure=11, end_beat=1, direction="crescendo"),
            tc("add_articulation", measure=10, beat=1, articulation="accent"),
        ),
    ),
    # -- transcription artifacts -------------------------------------------------
    case(
        "art_for_tay",
        "transcription_artifacts",
        "add a for tay at measure twelve beat one",
        expect_tools(tc("add_dynamic", measure=12, beat=1, dynamic="f")),
    ),
    case(
        "art_sforzando",
        "transcription_artifacts",
        "sfor zando on beat 2 of measure 4",
        expect_any_of(
            expect_tools(tc("add_dynamic", measure=4, beat=2, dynamic="sfz")),
            expect_tools(tc("add_dynamic", measure=4, beat=2, dynamic="sf")),
        ),
    ),
    case(
        "art_measure_to",
        "transcription_artifacts",
        "measure to beat one forte",
        expect_tools(tc("add_dynamic", measure=2, beat=1, dynamic="f")),
    ),
    case(
        "art_mets_a_forte",
        "transcription_artifacts",
        "mets a forte at measure eight beat one",
        expect_tools(tc("add_dynamic", measure=8, beat=1, dynamic="f")),
    ),
    case(
        "art_beat_free",
        "transcription_artifacts",
        "staccato on beat free of measure five",
        expect_tools(tc("add_articulation", measure=5, beat=3, articulation="staccato")),
    ),
    case(
        "art_measure_won",
        "transcription_artifacts",
        "put a piano at measure won beat one",
        expect_tools(tc("add_dynamic", measure=1, beat=1, dynamic="p")),
    ),
    case(
        "art_measure_for",
        "transcription_artifacts",
        "crescendo hairpin from measure for beat one to measure five beat one",
        expect_tools(
            tc("draw_hairpin", start_measure=4, start_beat=1, end_measure=5, end_beat=1, direction="crescendo")
        ),
    ),
    case(
        "art_beat_too",
        "transcription_artifacts",
        "trill on beat too of measure six",
        expect_tools(tc("add_ornament", measure=6, beat=2, ornament="trill")),
    ),
    case(
        "art_rehearsal_sea",
        "transcription_artifacts",
        "add a rehearsal mark sea at measure fourteen",
        expect_tools(tc("add_rehearsal_mark", measure=14, label="C")),
    ),
    # -- context carry-over: history is server-side, via setup_transcripts -------
    case(
        "ctx_same_thing_measure",
        "context_carryover",
        "same thing at measure 15",
        expect_tools(tc("add_dynamic", measure=15, beat=1, dynamic="f")),
        setup_transcripts=["forte at measure 2 beat 1"],
    ),
    case(
        "ctx_beat_only_repeat",
        "context_carryover",
        "do that again on beat 3",
        expect_tools(tc("add_articulation", measure=4, beat=3, articulation="staccato")),
        setup_transcripts=["staccato on beat 1 of measure 4"],
    ),
    case(
        "ctx_same_crescendo",
        "context_carryover",
        "now do the same crescendo from measure 9 beat 1 to measure 10 beat 1",
        expect_tools(
            tc("draw_hairpin", start_measure=9, start_beat=1, end_measure=10, end_beat=1, direction="crescendo")
        ),
        setup_transcripts=["crescendo from measure 5 beat 1 to measure 6 beat 1"],
    ),
    case(
        "ctx_beat_only_no_marking",
        "context_carryover",
        "beat 3",
        expect_tools(tc("add_dynamic", measure=7, beat=3, dynamic="mp")),
        setup_transcripts=["mezzo piano at measure 7 beat 1"],
    ),
    case(
        "ctx_ornament_beat_only",
        "context_carryover",
        "also add one on beat 3",
        expect_tools(tc("add_ornament", measure=8, beat=3, ornament="trill")),
        setup_transcripts=["trill on beat 1 of measure 8"],
    ),
    case(
        "ctx_deep_chain_beat_only",
        "context_carryover",
        "beat 4",
        expect_tools(tc("add_articulation", measure=12, beat=4, articulation="staccato")),
        setup_transcripts=["staccato on beat 1 of measure 12", "and again on beat 2"],
    ),
    # -- undo/redo phrases ---------------------------------------------------------
    case(
        "undo_go_back",
        "undo_redo",
        "go back",
        expect_tools(tc("undo")),
        setup_transcripts=["forte at measure 1 beat 1"],
    ),
    case(
        "undo_never_mind",
        "undo_redo",
        "never mind",
        expect_tools(tc("undo")),
        setup_transcripts=["forte at measure 1 beat 1"],
    ),
    case(
        "undo_put_that_back",
        "undo_redo",
        "put that back",
        expect_tools(tc("redo")),
        setup_transcripts=["forte at measure 1 beat 1", "undo that"],
    ),
    case(
        "undo_bare_undo",
        "undo_redo",
        "undo",
        expect_tools(tc("undo")),
        setup_transcripts=["piano at measure 2 beat 1"],
    ),
    case(
        "undo_nothing_to_undo",
        "undo_redo",
        "undo that",
        expect_tools(tc("undo")),
    ),
    # -- out of range: zero tools + conversational correction -----------------------
    case(
        "oor_measure_200",
        "out_of_range",
        "fortissimo at measure 200",
        expect_no_tools(),
    ),
    case(
        "oor_slur_out_of_range",
        "out_of_range",
        "add a slur from measure 25 beat 1 to measure 26 beat 1",
        expect_no_tools(),
    ),
    case(
        "oor_rehearsal_measure_50",
        "out_of_range",
        "rehearsal mark Z at measure 50",
        expect_no_tools(),
    ),
    case(
        "oor_hairpin_endpoint",
        "out_of_range",
        "crescendo from measure 16 beat 1 to measure 30 beat 1",
        expect_no_tools(),
    ),
    case(
        "oor_staccato_measure_99",
        "out_of_range",
        "staccato at measure 99 beat 1",
        expect_no_tools(),
    ),
    # -- genuinely ambiguous: zero tools + clarifying question -----------------------
    case(
        "amb_make_it_louder",
        "ambiguous",
        "make it louder",
        expect_no_tools(),
    ),
    case(
        "amb_add_accent_no_location",
        "ambiguous",
        "add an accent",
        expect_no_tools(),
    ),
    case(
        "amb_slur_there",
        "ambiguous",
        "put a slur there",
        expect_no_tools(),
    ),
    case(
        "amb_change_tempo",
        "ambiguous",
        "change the tempo",
        expect_no_tools(),
    ),
]
