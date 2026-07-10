"""Tests for nota.mcp_server.tools.add_articulation (single-note and range mode)."""

from __future__ import annotations

import music21 as m21

from nota import storage
from nota.mcp_server import tools
from nota.mcp_server.errors import ErrorCode

from .assertions import (
    assert_error,
    assert_ids_present,
    assert_renders_with_verovio,
    assert_round_trips,
    assert_success,
)


def _reparse(score_id: str) -> m21.stream.Score:
    xml = storage.read_xml(score_id)
    return m21.converter.parse(xml.encode("utf-8"), format="musicxml")


def _notes_with_articulation(score, articulation_cls) -> list:
    return [
        n
        for n in score.recurse().notes
        if any(isinstance(a, articulation_cls) for a in n.articulations)
    ]


# ---------------------------------------------------------------- single note


def test_add_staccato_single_note_simple_4_4(make_score):
    sid = make_score("simple_4_4")
    result = assert_success(tools.add_articulation(sid, measure=1, beat=2, articulation="staccato"))

    assert len(result["changed_element_ids"]) == 1
    assert_round_trips(sid)
    assert_ids_present(sid, result["changed_element_ids"])
    assert_renders_with_verovio(sid)

    reparsed = _reparse(sid)
    assert len(_notes_with_articulation(reparsed, m21.articulations.Staccato)) == 1


def test_add_articulation_every_enum_value(make_score):
    sid = make_score("simple_4_4")
    beats_and_measures = [
        (1, 1), (1, 2), (1, 3), (1, 4),
        (2, 1), (2, 2), (2, 3), (2, 4),
    ]
    for name, (measure, beat) in zip(sorted(tools.ARTICULATION_MAP), beats_and_measures):
        result = assert_success(
            tools.add_articulation(sid, measure=measure, beat=beat, articulation=name)
        )
        assert_ids_present(sid, result["changed_element_ids"])
    assert_round_trips(sid)
    assert_renders_with_verovio(sid)


def test_add_articulation_compound_6_8_second_beat(make_score):
    sid = make_score("compound_6_8")
    # In 6/8, beat 2 is the second dotted-quarter beat (the fourth eighth note).
    result = assert_success(tools.add_articulation(sid, measure=1, beat=2, articulation="accent"))
    assert_round_trips(sid)
    assert_ids_present(sid, result["changed_element_ids"])

    reparsed = _reparse(sid)
    marked = _notes_with_articulation(reparsed, m21.articulations.Accent)
    assert len(marked) == 1
    assert marked[0].beat == 2.0


def test_add_articulation_pickup_measure(make_score):
    sid = make_score("pickup")
    # The pickup fixture's only note sits on beat 4 of measure 0.
    result = assert_success(tools.add_articulation(sid, measure=0, beat=4, articulation="tenuto"))
    assert_round_trips(sid)
    assert_ids_present(sid, result["changed_element_ids"])
    assert_renders_with_verovio(sid)


def test_add_articulation_chord_counts_as_one_target(make_score):
    sid = make_score("chords")
    result = assert_success(tools.add_articulation(sid, measure=1, beat=1, articulation="accent"))

    assert len(result["changed_element_ids"]) == 1
    assert_round_trips(sid)
    assert_ids_present(sid, result["changed_element_ids"])

    reparsed = _reparse(sid)
    marked = _notes_with_articulation(reparsed, m21.articulations.Accent)
    assert len(marked) == 1
    assert isinstance(marked[0], m21.chord.Chord)


def test_add_articulation_grace_note_position_prefers_main_note(make_score):
    sid = make_score("grace_notes")
    result = assert_success(tools.add_articulation(sid, measure=1, beat=1, articulation="staccato"))
    assert_round_trips(sid)
    assert_ids_present(sid, result["changed_element_ids"])

    reparsed = _reparse(sid)
    marked = _notes_with_articulation(reparsed, m21.articulations.Staccato)
    assert len(marked) == 1
    assert not marked[0].duration.isGrace


def test_add_articulation_two_voices_targets_one_note(make_score):
    sid = make_score("two_voices")
    # Beat 2 exists only in voice 1 (voice 2 holds half notes on beats 1/3),
    # so exactly one note should be marked.
    result = assert_success(tools.add_articulation(sid, measure=1, beat=2, articulation="staccato"))
    assert len(result["changed_element_ids"]) == 1
    assert_round_trips(sid)
    assert_ids_present(sid, result["changed_element_ids"])


# ------------------------------------------------------------------ range mode


def test_range_within_one_measure(make_score):
    sid = make_score("simple_4_4")
    result = assert_success(
        tools.add_articulation(
            sid, measure=1, beat=2, articulation="staccato", end_measure=1, end_beat=4
        )
    )
    # Beats 2, 3, 4 of measure 1 => exactly 3 notes.
    assert len(result["changed_element_ids"]) == 3
    assert_round_trips(sid)
    assert_ids_present(sid, result["changed_element_ids"])
    assert_renders_with_verovio(sid)

    reparsed = _reparse(sid)
    assert len(_notes_with_articulation(reparsed, m21.articulations.Staccato)) == 3


def test_range_across_barline_exact_note_count(make_score):
    sid = make_score("simple_4_4")
    result = assert_success(
        tools.add_articulation(
            sid, measure=1, beat=3, articulation="staccato", end_measure=2, end_beat=2
        )
    )
    # m1 beats 3,4 + m2 beats 1,2 => exactly 4 notes across the barline.
    assert len(result["changed_element_ids"]) == 4
    assert_round_trips(sid)
    assert_ids_present(sid, result["changed_element_ids"])

    reparsed = _reparse(sid)
    marked = _notes_with_articulation(reparsed, m21.articulations.Staccato)
    assert len(marked) == 4
    positions = sorted((n.measureNumber, n.beat) for n in marked)
    assert positions == [(1, 3.0), (1, 4.0), (2, 1.0), (2, 2.0)]


def test_range_whole_measures(make_score):
    sid = make_score("simple_4_4")
    result = assert_success(
        tools.add_articulation(
            sid, measure=2, beat=1, articulation="tenuto", end_measure=3, end_beat=4
        )
    )
    # All 8 quarter notes in measures 2-3, inclusive endpoints.
    assert len(result["changed_element_ids"]) == 8
    assert_ids_present(sid, result["changed_element_ids"])


def test_range_across_meter_change(make_score):
    sid = make_score("meter_change")
    result = assert_success(
        tools.add_articulation(
            sid, measure=4, beat=1, articulation="accent", end_measure=5, end_beat=3
        )
    )
    # All of measure 4 (4 quarter notes in 4/4) + all of measure 5
    # (3 quarter notes in 3/4) => 7 notes.
    assert len(result["changed_element_ids"]) == 7
    assert_round_trips(sid)
    assert_ids_present(sid, result["changed_element_ids"])


def test_range_includes_chords_as_single_targets(make_score):
    sid = make_score("chords")
    result = assert_success(
        tools.add_articulation(
            sid, measure=1, beat=1, articulation="staccato", end_measure=2, end_beat=3
        )
    )
    # Fixture content: m1 = chord, note, chord (beats 1, 2, 3);
    # m2 = note, chord (beats 1, 3). All 5 fall inside the range.
    assert len(result["changed_element_ids"]) == 5
    assert_round_trips(sid)
    assert_ids_present(sid, result["changed_element_ids"])


def test_range_covers_both_voices(make_score):
    sid = make_score("two_voices")
    result = assert_success(
        tools.add_articulation(
            sid, measure=1, beat=1, articulation="staccato", end_measure=1, end_beat=4
        )
    )
    # Voice 1: quarter notes on beats 1-4 (4 notes); voice 2: half notes
    # on beats 1 and 3 (2 notes) => 6 notes total.
    assert len(result["changed_element_ids"]) == 6
    assert_round_trips(sid)
    assert_ids_present(sid, result["changed_element_ids"])


def test_range_includes_grace_notes_inside_span(make_score):
    sid = make_score("grace_notes")
    result = assert_success(
        tools.add_articulation(
            sid, measure=1, beat=1, articulation="staccato", end_measure=1, end_beat=4
        )
    )
    # 4 main notes + 2 grace notes share offsets within the span => 6.
    assert len(result["changed_element_ids"]) == 6
    assert_round_trips(sid)
    assert_ids_present(sid, result["changed_element_ids"])


def test_range_with_zero_notes_errors(make_score):
    sid = make_score("chords")
    # In measure 2 the notes start on beats 1 and 3; beat 2 to beat 2.5
    # spans no note onsets.
    result = tools.add_articulation(
        sid, measure=2, beat=2, articulation="staccato", end_measure=2, end_beat=2.5
    )
    err = assert_error(result, ErrorCode.NO_NOTE_AT_POSITION)
    assert "measure 2" in err["message"]


# ----------------------------------------------------------------- error paths


def test_add_articulation_score_not_found():
    result = tools.add_articulation("nope", measure=1, beat=1, articulation="staccato")
    err = assert_error(result, ErrorCode.SCORE_NOT_FOUND)
    assert "nope" in err["message"]


def test_add_articulation_invalid_enum(make_score):
    sid = make_score("simple_4_4")
    result = tools.add_articulation(sid, measure=1, beat=1, articulation="squeeze")
    err = assert_error(result, ErrorCode.INVALID_ENUM_VALUE)
    assert "squeeze" in err["message"]
    assert "staccato" in err["message"]  # message lists valid values


def test_add_articulation_measure_out_of_range_message_has_count(make_score):
    sid = make_score("compound_6_8")
    result = tools.add_articulation(sid, measure=10, beat=1, articulation="staccato")
    err = assert_error(result, ErrorCode.MEASURE_OUT_OF_RANGE)
    assert "2 measures" in err["message"]


def test_add_articulation_pickup_mentioned_in_out_of_range_message(make_score):
    sid = make_score("pickup")
    result = tools.add_articulation(sid, measure=10, beat=1, articulation="staccato")
    err = assert_error(result, ErrorCode.MEASURE_OUT_OF_RANGE)
    assert "3 measures" in err["message"]
    assert "pickup" in err["message"]


def test_add_articulation_beat_out_of_range_after_meter_change(make_score):
    sid = make_score("meter_change")
    # Measure 5 switched to 3/4; beat 4 no longer exists there.
    result = tools.add_articulation(sid, measure=5, beat=4, articulation="staccato")
    err = assert_error(result, ErrorCode.BEAT_OUT_OF_RANGE)
    assert "3 beats" in err["message"]
    assert "3/4" in err["message"]


def test_add_articulation_beat_still_valid_before_meter_change(make_score):
    sid = make_score("meter_change")
    # Measure 4 is still 4/4, so beat 4 is fine there.
    assert_success(tools.add_articulation(sid, measure=4, beat=4, articulation="staccato"))


def test_add_articulation_range_end_measure_out_of_range(make_score):
    sid = make_score("simple_4_4")
    result = tools.add_articulation(
        sid, measure=1, beat=1, articulation="staccato", end_measure=44, end_beat=1
    )
    err = assert_error(result, ErrorCode.MEASURE_OUT_OF_RANGE)
    assert "4 measures" in err["message"]


def test_add_articulation_range_end_beat_out_of_range(make_score):
    sid = make_score("simple_4_4")
    result = tools.add_articulation(
        sid, measure=1, beat=1, articulation="staccato", end_measure=2, end_beat=8
    )
    err = assert_error(result, ErrorCode.BEAT_OUT_OF_RANGE)
    assert "4 beats" in err["message"]


def test_add_articulation_no_note_at_position_lists_nearest(make_score):
    sid = make_score("chords")
    # Measure 2 has notes on beats 1 and 3 only.
    result = tools.add_articulation(sid, measure=2, beat=2, articulation="staccato")
    err = assert_error(result, ErrorCode.NO_NOTE_AT_POSITION)
    assert "1" in err["message"] and "3" in err["message"]


def test_add_articulation_part_not_found_lists_parts(make_score):
    sid = make_score("chords")
    result = tools.add_articulation(sid, measure=1, beat=1, articulation="staccato", part="Cello")
    err = assert_error(result, ErrorCode.PART_NOT_FOUND)
    assert "Guitar" in err["message"]


# ------------------------------------------------------------------ snapshots


def test_validation_failure_leaves_no_snapshot(make_score, snapshot_count):
    sid = make_score("simple_4_4")
    tools.add_articulation(sid, measure=99, beat=1, articulation="staccato")
    tools.add_articulation(sid, measure=1, beat=9, articulation="staccato")
    tools.add_articulation(sid, measure=1, beat=1, articulation="wiggle")
    tools.add_articulation(sid, measure=1, beat=1, articulation="staccato", part="Nope")
    assert snapshot_count(sid) == 0


def test_success_creates_snapshot_and_undo_restores_bytes(make_score, snapshot_count, undo_stack_labels):
    sid = make_score("simple_4_4")
    before = storage.read_xml(sid)

    tools.add_articulation(sid, measure=1, beat=1, articulation="staccato")
    assert snapshot_count(sid) == 1
    labels = undo_stack_labels(sid)
    assert labels == ["add_articulation staccato m1b1"]
    assert storage.read_xml(sid) != before

    restored_label = storage.undo(sid)
    assert restored_label == "add_articulation staccato m1b1"
    assert storage.read_xml(sid) == before


def test_range_mutation_single_snapshot_and_undo(make_score, snapshot_count):
    sid = make_score("simple_4_4")
    before = storage.read_xml(sid)

    tools.add_articulation(
        sid, measure=1, beat=1, articulation="staccato", end_measure=4, end_beat=4
    )
    # One call = one undo entry, no matter how many notes changed.
    assert snapshot_count(sid) == 1

    storage.undo(sid)
    assert storage.read_xml(sid) == before
