"""Notation-tool pipeline tests against real, complex scores pulled from
the music21-bundled corpus, rather than the small hand-built fixtures the
rest of this suite uses. See `real_score_builders.py` for what each score
was chosen for and why it's kept out of the synthetic fixture matrix.

Positions used below (pickup beats, chord offsets, rest measures, etc.)
were determined by directly inspecting each real score's parsed content,
not guessed — real scores don't follow the synthetic fixtures' "measure 1
always has notes on beats 1 and 2" convention.
"""

from __future__ import annotations

import music21 as m21
import pytest

from nota import storage
from nota.mcp_server import location, tools
from nota.mcp_server.errors import ErrorCode

from .assertions import (
    assert_error,
    assert_ids_present,
    assert_renders_with_verovio,
    assert_round_trips,
    assert_success,
)
from .real_score_builders import REAL_SCORE_BUILDERS

ALL_REAL_FIXTURES = sorted(REAL_SCORE_BUILDERS)


# ------------------------------------------------------------------ shapes


def test_real_fixture_shapes(real_fixture_xml_cache):
    assert real_fixture_xml_cache["bach_bwv1_6"].has_pickup
    assert real_fixture_xml_cache["bach_bwv1_6"].measure_count == 20
    assert not real_fixture_xml_cache["mozart_k545_exposition"].has_pickup
    assert real_fixture_xml_cache["mozart_k545_exposition"].measure_count == 12
    assert real_fixture_xml_cache["schumann_op41no1_mvt3"].measure_count == 114
    assert real_fixture_xml_cache["haydn_op74no1_mvt3"].measure_count == 113
    assert real_fixture_xml_cache["beethoven_op18no1_mvt1"].measure_count == 313


@pytest.mark.parametrize("fixture_name", ALL_REAL_FIXTURES)
def test_real_fixture_round_trips_with_music21(real_fixture_xml_cache, fixture_name):
    info = real_fixture_xml_cache[fixture_name]
    reparsed = m21.converter.parse(info.xml.encode("utf-8"), format="musicxml")
    assert list(reparsed.recurse().notes), fixture_name


@pytest.mark.parametrize("fixture_name", ALL_REAL_FIXTURES)
def test_real_fixture_renders_with_verovio(real_fixture_xml_cache, fixture_name):
    pytest.importorskip("verovio")
    import verovio

    toolkit = verovio.toolkit()
    assert toolkit.loadData(real_fixture_xml_cache[fixture_name].xml)
    svg = toolkit.renderToSVG(1)
    assert svg and "<svg" in svg


# -------------------------------------------------------- bach: full sweep


def test_bach_chorale_full_tool_lifecycle(make_score):
    """One real, multi-part, pickup-measure score exercised through every
    tool plus an undo/redo cycle — the "does the whole pipeline actually
    work end to end on a real score" test. Bach bwv1.6 has 5 parts (one
    doubling the soprano) and a one-beat pickup measure numbered 0.
    """
    sid = make_score("bach_bwv1_6")

    add_dynamic = assert_success(tools.add_dynamic(sid, measure=0, beat=4, dynamic="p"))
    assert_round_trips(sid)
    assert_ids_present(sid, add_dynamic["changed_element_ids"])

    slur = assert_success(
        tools.draw_slur(sid, start_measure=1, start_beat=1, end_measure=1, end_beat=2)
    )
    assert_round_trips(sid)
    assert_ids_present(sid, slur["changed_element_ids"])

    articulation = assert_success(
        tools.add_articulation(sid, measure=20, beat=1, articulation="tenuto")
    )
    assert_round_trips(sid)
    assert_ids_present(sid, articulation["changed_element_ids"])

    hairpin = assert_success(
        tools.draw_hairpin(
            sid, start_measure=1, start_beat=1, end_measure=1, end_beat=4, direction="crescendo"
        )
    )
    assert_round_trips(sid)
    assert_ids_present(sid, hairpin["changed_element_ids"])

    text = assert_success(tools.add_text_expression(sid, measure=1, beat=1, text="dolce"))
    assert_round_trips(sid)

    tempo = assert_success(tools.add_tempo(sid, measure=1, bpm=88, text="Andante"))
    assert_round_trips(sid)
    assert_ids_present(sid, tempo["changed_element_ids"])

    rehearsal = assert_success(tools.add_rehearsal_mark(sid, measure=2, label="A"))
    assert_round_trips(sid)

    ornament = assert_success(
        tools.add_ornament(sid, measure=20, beat=1, ornament="fermata", part="Alto")
    )
    assert_round_trips(sid)
    assert_ids_present(sid, ornament["changed_element_ids"])

    before_removal = storage.read_xml(sid)
    removal = assert_success(tools.remove_notation(sid, measure=2, notation_type="rehearsal_mark"))
    assert removal["success"]
    assert storage.read_xml(sid) != before_removal

    undo_result = tools.undo(sid)
    assert undo_result["success"]
    redo_result = tools.redo(sid)
    assert redo_result["success"]
    assert_round_trips(sid)

    assert_renders_with_verovio(sid)


def test_bach_chorale_addressing_by_part_name(make_score):
    """Every one of the 5 real parts (distinct names) is independently
    addressable, including the 4th/5th.
    """
    sid = make_score("bach_bwv1_6")
    for part_name in ["Horn 2", "Soprano", "Alto", "Tenor", "Bass"]:
        result = assert_success(
            tools.add_dynamic(sid, measure=1, beat=1, dynamic="mf", part=part_name)
        )
        assert result["changed_element_ids"]


def test_bach_chorale_pickup_beat_out_of_range(make_score):
    sid = make_score("bach_bwv1_6")
    result = tools.add_dynamic(sid, measure=0, beat=1, dynamic="f")
    err = assert_error(result, ErrorCode.BEAT_OUT_OF_RANGE)
    assert "pickup" in err["message"]


# ------------------------------------------------------ mozart: chords, staves


def test_mozart_chord_in_second_staff_gets_note_level_id(make_score):
    """The left-hand staff (P1-Staff2) has a real block chord at measure 6
    beat 1; both staves share the same part *name* ("MusicXML Part"), so
    addressing the second one by name would be ambiguous — this uses the
    part id instead, exactly as a real duplicate-named-parts score
    requires.
    """
    sid = make_score("mozart_k545_exposition")
    result = assert_success(
        tools.add_dynamic(sid, measure=6, beat=1, dynamic="p", part="P1-Staff2")
    )
    assert len(result["changed_element_ids"]) == 1
    assert_round_trips(sid)
    assert_ids_present(sid, result["changed_element_ids"])

    reparsed = m21.converter.parse(storage.read_xml(sid).encode("utf-8"), format="musicxml")
    assert list(reparsed.recurse().getElementsByClass(m21.chord.Chord))
    assert list(reparsed.recurse().getElementsByClass(m21.dynamics.Dynamic))


def test_mozart_last_measure_chord_ornament(make_score):
    """The final measure's chord (measure 12 beat 2, right-hand staff) is
    a valid ornament target, and a chord's own id is expected to be
    dropped by music21's writer just like the synthetic 'chords' fixture
    documents — assign_id must still fall back correctly on real data.
    """
    sid = make_score("mozart_k545_exposition")
    result = assert_success(tools.add_ornament(sid, measure=12, beat=2, ornament="trill"))
    assert_round_trips(sid)
    assert_ids_present(sid, result["changed_element_ids"])


def test_mozart_duplicate_part_names_resolve_to_first_match(make_score):
    """Both staves report the same partName ("MusicXML Part"); resolving
    by that name must deterministically hit the first part rather than
    erroring or guessing, and the second staff must remain reachable via
    its part id. Pins current, documented resolve_part behavior for a
    real duplicate-name score (draw_hairpin/etc. rely on the same
    resolve_part call).
    """
    sid = make_score("mozart_k545_exposition")
    by_name = assert_success(
        tools.add_dynamic(sid, measure=1, beat=1, dynamic="f", part="MusicXML Part")
    )
    by_first_id = assert_success(
        tools.add_dynamic(sid, measure=2, beat=1, dynamic="f", part="P1-Staff1")
    )
    assert by_name["changed_element_ids"] and by_first_id["changed_element_ids"]


# --------------------------------------------------- schoenberg: pickup@1, voices


def test_schoenberg_pickup_numbered_one_not_zero(make_score):
    """Regression test for a real breakage: this score's pickup measure is
    numbered 1 (there is no measure 0 at all), signaled only by
    `paddingLeft` — a different, equally valid MusicXML convention than
    the numbered-0 pickups every synthetic fixture uses. Before the fix,
    `location.has_pickup`/`resolve_measure` only recognized measure 0, so
    the out-of-range hint for this score wrongly implied there was no
    pickup at all.
    """
    sid = make_score("schoenberg_op19_no6")

    reparsed = m21.converter.parse(storage.read_xml(sid).encode("utf-8"), format="musicxml")
    part_obj = reparsed.parts[0]
    assert location.has_pickup(part_obj)

    result = tools.add_dynamic(sid, measure=99, beat=1, dynamic="f")
    err = assert_error(result, ErrorCode.MEASURE_OUT_OF_RANGE)
    assert "pickup measure, numbered 1" in err["message"]

    # Beat 1-3 fall in the missing opening span of the pickup; only beat 4
    # (the padded start) is real.
    out_of_range = tools.add_dynamic(sid, measure=1, beat=1, dynamic="f")
    assert_error(out_of_range, ErrorCode.BEAT_OUT_OF_RANGE)

    ok = assert_success(tools.add_dynamic(sid, measure=1, beat=4, dynamic="f"))
    assert_round_trips(sid)
    assert_ids_present(sid, ok["changed_element_ids"])


def test_schoenberg_dense_two_voice_measure_targets_one_note(make_score):
    """Measure 4 has two simultaneous voices; beat 3 only has a note in
    the second voice. Confirms note lookup reaches into voices on a real,
    densely polyphonic score (not just the synthetic two_voices fixture).
    """
    sid = make_score("schoenberg_op19_no6")
    result = assert_success(tools.add_articulation(sid, measure=4, beat=3, articulation="accent"))
    assert len(result["changed_element_ids"]) == 1
    assert_round_trips(sid)
    assert_ids_present(sid, result["changed_element_ids"])


def test_schoenberg_last_measure(make_score):
    sid = make_score("schoenberg_op19_no6")
    result = assert_success(tools.add_dynamic(sid, measure=10, beat=1, dynamic="pp"))
    assert_round_trips(sid)
    assert_ids_present(sid, result["changed_element_ids"])


# --------------------------------------------------------- schumann: meter change


def test_schumann_mid_score_meter_change_boundary(make_score):
    """Measure 33 is the last measure of a 2/2 span; measure 34 begins a
    6/8 span (real mid-piece meter change, not the synthetic
    meter_change fixture's hand-placed one). Both sides of the boundary
    must resolve correctly.
    """
    sid = make_score("schumann_op41no1_mvt3")

    before_change = assert_success(
        tools.add_dynamic(sid, measure=33, beat=2, dynamic="f", part="Viola")
    )
    assert_round_trips(sid)
    assert_ids_present(sid, before_change["changed_element_ids"])

    after_change = assert_success(
        tools.add_dynamic(sid, measure=34, beat=1, dynamic="p", part="Viola")
    )
    assert_round_trips(sid)
    assert_ids_present(sid, after_change["changed_element_ids"])

    # A beat that's only valid under the old 2/2 meter must be rejected
    # once inside the new 6/8 span.
    invalid = tools.add_dynamic(sid, measure=34, beat=3, dynamic="f", part="Viola")
    assert_error(invalid, ErrorCode.BEAT_OUT_OF_RANGE)


def test_schumann_distinct_part_names_all_addressable(make_score):
    sid = make_score("schumann_op41no1_mvt3")
    for part_name in ["1st Violin", "2nd Violin", "Viola", "Cello"]:
        result = assert_success(
            tools.add_dynamic(sid, measure=1, beat=1, dynamic="mp", part=part_name)
        )
        assert result["changed_element_ids"]


# -------------------------------------------- beethoven: large score, full rests


def test_beethoven_large_score_last_measure(make_score):
    sid = make_score("beethoven_op18no1_mvt1")
    result = assert_success(tools.add_dynamic(sid, measure=313, beat=1, dynamic="ff"))
    assert_round_trips(sid)
    assert_ids_present(sid, result["changed_element_ids"])


def test_beethoven_full_measure_rest_has_no_note_position(make_score):
    """The cello sits out measure 13 entirely (a real, whole-measure rest
    in an inner part) — a shape none of the synthetic fixtures have.
    """
    sid = make_score("beethoven_op18no1_mvt1")
    result = tools.add_articulation(
        sid, measure=13, beat=1, articulation="staccato", part="Violoncello"
    )
    err = assert_error(result, ErrorCode.NO_NOTE_AT_POSITION)
    assert "no notes" in err["message"]


def test_beethoven_duplicate_violin_parts_addressable_by_ordinal_alias(make_score):
    """Real finding: this score's two violin parts are both named plain
    "Violin" (no "I"/"II" suffix) in the source MusicXML. music21's
    round-trip through our storage layer (parse -> write, exactly what
    every upload does) also collapses each part's *id* to match its
    display name, so after upload both parts are `id="Violin"`,
    `partName="Violin"` — not just same-named but fully identical on
    every field `resolve_part` matches against by default. Ordinal aliases
    ("Violin 1", "Violin 2", assigned in score order) make the second
    violin addressable: this drives a distinct dynamic into each one and
    confirms, by reparsing, that "Violin 1" really lands on part index 0
    and "Violin 2" on part index 1 — not just that both calls succeeded.
    """
    sid = make_score("beethoven_op18no1_mvt1")

    reparsed = m21.converter.parse(storage.read_xml(sid).encode("utf-8"), format="musicxml")
    violin_parts = [p for p in reparsed.parts if p.partName == "Violin"]
    assert len(violin_parts) == 2
    assert violin_parts[0].id == violin_parts[1].id == "Violin"

    # measure 2 (not measure 1, which already carries a pre-existing "p"
    # on both violins in the real score) beat 1 is otherwise untouched, so
    # a fresh, distinctive marking on each violin there can only have come
    # from the call that targeted it.
    first_call = assert_success(
        tools.add_dynamic(sid, measure=2, beat=1, dynamic="ff", part="Violin 1")
    )
    second_call = assert_success(
        tools.add_dynamic(sid, measure=2, beat=1, dynamic="ppp", part="Violin 2")
    )
    assert first_call["changed_element_ids"] and second_call["changed_element_ids"]

    reparsed_after = m21.converter.parse(storage.read_xml(sid).encode("utf-8"), format="musicxml")
    all_parts = list(reparsed_after.parts)

    def _measure_2_dynamics(part_obj) -> set[str]:
        measure = [m for m in part_obj.getElementsByClass(m21.stream.Measure) if m.number == 2][0]
        return {d.value for d in measure.recurse().getElementsByClass(m21.dynamics.Dynamic)}

    violin_1_dynamics = _measure_2_dynamics(all_parts[0])
    violin_2_dynamics = _measure_2_dynamics(all_parts[1])
    assert "ff" in violin_1_dynamics
    assert "ppp" not in violin_1_dynamics
    assert "ppp" in violin_2_dynamics
    assert "ff" not in violin_2_dynamics

    # A bare, still-ambiguous "Violin" keeps resolving to the first part --
    # pinned behavior other tests rely on (see
    # test_mozart_duplicate_part_names_resolve_to_first_match).
    bare = assert_success(tools.add_dynamic(sid, measure=3, beat=1, dynamic="mf", part="Violin"))
    assert bare["changed_element_ids"]

    unknown = tools.add_dynamic(sid, measure=1, beat=1, dynamic="f", part="Cello")
    err = assert_error(unknown, ErrorCode.PART_NOT_FOUND)
    assert "Violin 1" in err["message"]
    assert "Violin 2" in err["message"]


def test_beethoven_undo_redo_cycle_on_large_score(make_score):
    sid = make_score("beethoven_op18no1_mvt1")
    before = storage.read_xml(sid)

    tools.add_dynamic(sid, measure=100, beat=1, dynamic="f")
    after_edit = storage.read_xml(sid)
    assert after_edit != before

    undo_result = tools.undo(sid)
    assert undo_result["success"]
    assert storage.read_xml(sid) == before

    redo_result = tools.redo(sid)
    assert redo_result["success"]
    assert storage.read_xml(sid) == after_edit


# ------------------------------------------- haydn: pre-existing hairpins


def test_haydn_hairpin_add_and_remove_amid_real_hairpins(make_score):
    """This real score already has 11 crescendo/decrescendo hairpins of
    its own; adding and then removing a new one at a clean spot (measure
    1, which none of the originals touch) must not get confused by them.
    """
    sid = make_score("haydn_op74no1_mvt3")

    hairpin = assert_success(
        tools.draw_hairpin(
            sid, start_measure=1, start_beat=1, end_measure=2, end_beat=1, direction="crescendo"
        )
    )
    assert_round_trips(sid)
    assert_ids_present(sid, hairpin["changed_element_ids"])

    removal = assert_success(
        tools.remove_notation(sid, measure=1, beat=1, notation_type="hairpin")
    )
    assert removal["success"]
    assert_round_trips(sid)


def test_haydn_pre_existing_hairpins_all_survive_repaired_roundtrip(
    real_fixture_xml_cache, make_score
):
    """This score has 11 real crescendo/decrescendo hairpins, 2 of which
    used to be silently dropped on round-trip by a music21 writer defect
    (see `nota.services.musicxml_repair`'s module docstring): music21's
    MusicXML writer doesn't always keep each concurrently-open hairpin's
    `number` attribute distinct, so a `<wedge number="N" type="stop">`
    would sometimes be written *before* its own `<wedge number="N"
    type="...">` opener elsewhere in the same part -- music21's reader
    processes directions strictly in document order, so it hit the stop
    with nothing open for that number and dropped the pair, logging
    "Could not import wedge: ...".

    `repair_spanner_order` reorders exactly that shape wherever this app
    writes score MusicXML (upload ingestion and every tool call's
    rewrite), so all 11 must now survive every round trip: the initial
    corpus.parse -> write that seeds this fixture, and a second full
    parse+write cycle triggered by an ordinary, unrelated tool call (the
    harness always rewrites the whole score on every accepted mutation).
    """
    from music21 import corpus

    original = corpus.parse("haydn/opus74no1/movement3")
    original_wedges = len(
        list(original.recurse().getElementsByClass((m21.dynamics.Crescendo, m21.dynamics.Diminuendo)))
    )
    assert original_wedges == 11

    # The fixture cache already round-tripped the score once (corpus.parse
    # -> score.write -> repair_spanner_order, exactly what a real upload
    # does) -- all 11 must still be there.
    once_roundtripped = m21.converter.parse(
        real_fixture_xml_cache["haydn_op74no1_mvt3"].xml.encode("utf-8"), format="musicxml"
    )
    once_count = len(
        list(
            once_roundtripped.recurse().getElementsByClass(
                (m21.dynamics.Crescendo, m21.dynamics.Diminuendo)
            )
        )
    )
    assert once_count == 11

    # A normal, unrelated tool call triggers a second full parse+write
    # cycle. The tool's own reported id must be present and correct, and
    # all 11 pre-existing hairpins must still be there afterward too.
    sid = make_score("haydn_op74no1_mvt3")
    result = assert_success(tools.add_dynamic(sid, measure=50, beat=1, dynamic="mf"))
    assert_round_trips(sid)
    assert_ids_present(sid, result["changed_element_ids"])

    twice_roundtripped = m21.converter.parse(
        storage.read_xml(sid).encode("utf-8"), format="musicxml"
    )
    twice_count = len(
        list(
            twice_roundtripped.recurse().getElementsByClass(
                (m21.dynamics.Crescendo, m21.dynamics.Diminuendo)
            )
        )
    )
    assert twice_count == 11
