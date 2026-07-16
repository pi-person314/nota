"""Tests for nota.mcp_server.tools.remove_notation."""

from __future__ import annotations

import music21 as m21

from nota import storage
from nota.mcp_server import tools
from nota.mcp_server.errors import ErrorCode

from .assertions import assert_error, assert_round_trips, assert_success


def _reparse(score_id: str) -> m21.stream.Score:
    xml = storage.read_xml(score_id)
    return m21.converter.parse(xml.encode("utf-8"), format="musicxml")


# ------------------------------------------------------------- single-family


def test_remove_dynamic(make_score):
    sid = make_score("simple_4_4")
    tools.add_dynamic(sid, measure=1, beat=1, dynamic="f")

    result = assert_success(tools.remove_notation(sid, measure=1, beat=1))
    assert result["changed_element_ids"] == []
    assert "dynamic" in result["summary"]
    assert_round_trips(sid)

    reparsed = _reparse(sid)
    assert not list(reparsed.recurse().getElementsByClass(m21.dynamics.Dynamic))


def test_remove_slur(make_score):
    sid = make_score("simple_4_4")
    tools.draw_slur(sid, start_measure=1, start_beat=1, end_measure=1, end_beat=4)

    result = assert_success(tools.remove_notation(sid, measure=1, beat=1, notation_type="slur"))
    assert "slur" in result["summary"]
    reparsed = _reparse(sid)
    assert not list(reparsed.recurse().getElementsByClass(m21.spanner.Slur))


def test_remove_slur_by_end_position(make_score):
    sid = make_score("simple_4_4")
    tools.draw_slur(sid, start_measure=1, start_beat=1, end_measure=1, end_beat=4)

    result = assert_success(tools.remove_notation(sid, measure=1, beat=4, notation_type="slur"))
    assert result["success"]
    reparsed = _reparse(sid)
    assert not list(reparsed.recurse().getElementsByClass(m21.spanner.Slur))


def test_remove_hairpin(make_score):
    sid = make_score("simple_4_4")
    tools.draw_hairpin(
        sid, start_measure=1, start_beat=1, end_measure=1, end_beat=4, direction="crescendo"
    )

    result = assert_success(tools.remove_notation(sid, measure=1, beat=1, notation_type="hairpin"))
    assert "hairpin" in result["summary"] or "crescendo" in result["summary"]
    reparsed = _reparse(sid)
    assert not list(reparsed.recurse().getElementsByClass(m21.dynamics.Crescendo))


def test_remove_articulation(make_score):
    sid = make_score("simple_4_4")
    tools.add_articulation(sid, measure=1, beat=1, articulation="staccato")

    result = assert_success(
        tools.remove_notation(sid, measure=1, beat=1, notation_type="articulation")
    )
    assert "staccato" in result["summary"]
    reparsed = _reparse(sid)
    note = next(n for n in reparsed.recurse().notes if n.beat == 1.0 and n.measureNumber == 1)
    assert not note.articulations


def test_remove_ornament(make_score):
    sid = make_score("simple_4_4")
    tools.add_ornament(sid, measure=1, beat=1, ornament="trill")

    result = assert_success(tools.remove_notation(sid, measure=1, beat=1, notation_type="ornament"))
    assert "trill" in result["summary"]
    reparsed = _reparse(sid)
    note = next(n for n in reparsed.recurse().notes if n.beat == 1.0 and n.measureNumber == 1)
    assert not note.expressions


def test_remove_text_expression(make_score):
    sid = make_score("simple_4_4")
    tools.add_text_expression(sid, measure=1, beat=1, text="dolce")

    result = assert_success(
        tools.remove_notation(sid, measure=1, beat=1, notation_type="text_expression")
    )
    assert "dolce" in result["summary"]
    reparsed = _reparse(sid)
    assert not list(reparsed.recurse().getElementsByClass(m21.expressions.TextExpression))


def test_remove_tempo(make_score):
    sid = make_score("simple_4_4")
    tools.add_tempo(sid, measure=1, bpm=120)

    result = assert_success(tools.remove_notation(sid, measure=1, notation_type="tempo"))
    assert "tempo" in result["summary"]
    reparsed = _reparse(sid)
    assert not list(reparsed.recurse().getElementsByClass(m21.tempo.MetronomeMark))


def test_remove_rehearsal_mark(make_score):
    sid = make_score("simple_4_4")
    tools.add_rehearsal_mark(sid, measure=1, label="A")

    result = assert_success(tools.remove_notation(sid, measure=1, notation_type="rehearsal_mark"))
    assert "A" in result["summary"]
    reparsed = _reparse(sid)
    assert not list(reparsed.recurse().getElementsByClass(m21.expressions.RehearsalMark))


def test_remove_notation_without_beat_finds_measure_level_mark(make_score):
    sid = make_score("simple_4_4")
    tools.add_rehearsal_mark(sid, measure=2, label="B")

    result = assert_success(tools.remove_notation(sid, measure=2, notation_type="rehearsal_mark"))
    assert result["success"]


def test_remove_notation_single_candidate_without_notation_type_filter(make_score):
    sid = make_score("simple_4_4")
    tools.add_dynamic(sid, measure=1, beat=1, dynamic="f")

    # Only one family present at that beat, so no notation_type is needed.
    result = assert_success(tools.remove_notation(sid, measure=1, beat=1))
    assert result["success"]


# --------------------------------------------------------------- ambiguous


def test_remove_notation_ambiguous_two_candidates(make_score):
    sid = make_score("simple_4_4")
    tools.add_dynamic(sid, measure=1, beat=1, dynamic="f")
    tools.add_articulation(sid, measure=1, beat=1, articulation="staccato")

    result = tools.remove_notation(sid, measure=1, beat=1)
    err = assert_error(result, ErrorCode.AMBIGUOUS_TARGET)
    assert "dynamic" in err["message"]
    assert "staccato" in err["message"]
    assert "measure 1" in err["message"]
    assert "beat 1" in err["message"]


def test_remove_notation_ambiguous_resolved_by_notation_type(make_score):
    sid = make_score("simple_4_4")
    tools.add_dynamic(sid, measure=1, beat=1, dynamic="f")
    tools.add_articulation(sid, measure=1, beat=1, articulation="staccato")

    result = assert_success(
        tools.remove_notation(sid, measure=1, beat=1, notation_type="articulation")
    )
    assert "staccato" in result["summary"]

    reparsed = _reparse(sid)
    # The dynamic should still be there — only the articulation was removed.
    assert list(reparsed.recurse().getElementsByClass(m21.dynamics.Dynamic))


def test_remove_notation_ambiguous_multiple_articulations_on_same_note(make_score):
    sid = make_score("simple_4_4")
    tools.add_articulation(sid, measure=1, beat=1, articulation="staccato")
    tools.add_articulation(sid, measure=1, beat=1, articulation="accent")

    result = tools.remove_notation(sid, measure=1, beat=1, notation_type="articulation")
    err = assert_error(result, ErrorCode.AMBIGUOUS_TARGET)
    assert "staccato" in err["message"]
    assert "accent" in err["message"]


def test_remove_notation_ambiguous_lists_three_candidates(make_score):
    sid = make_score("simple_4_4")
    tools.add_dynamic(sid, measure=1, beat=1, dynamic="f")
    tools.add_articulation(sid, measure=1, beat=1, articulation="staccato")
    tools.add_ornament(sid, measure=1, beat=1, ornament="trill")

    result = tools.remove_notation(sid, measure=1, beat=1)
    err = assert_error(result, ErrorCode.AMBIGUOUS_TARGET)
    assert "dynamic" in err["message"]
    assert "staccato" in err["message"]
    assert "trill" in err["message"]
    assert ", and" in err["message"]


# ----------------------------------------------------------------- nothing


def test_remove_notation_nothing_at_position(make_score):
    sid = make_score("simple_4_4")
    result = tools.remove_notation(sid, measure=1, beat=1)
    err = assert_error(result, ErrorCode.NOTHING_TO_REMOVE)
    assert "measure 1" in err["message"]


def test_remove_notation_nothing_of_that_type(make_score):
    sid = make_score("simple_4_4")
    tools.add_dynamic(sid, measure=1, beat=1, dynamic="f")

    result = tools.remove_notation(sid, measure=1, beat=1, notation_type="slur")
    err = assert_error(result, ErrorCode.NOTHING_TO_REMOVE)
    assert "slur" in err["message"]


def test_remove_notation_nothing_hints_at_other_beat_in_measure(make_score):
    sid = make_score("simple_4_4")
    tools.add_dynamic(sid, measure=1, beat=2, dynamic="f")

    result = tools.remove_notation(sid, measure=1, beat=1, notation_type="dynamic")
    err = assert_error(result, ErrorCode.NOTHING_TO_REMOVE)
    assert "elsewhere in that measure" in err["message"]


# ----------------------------------------------------------------- error paths


def test_remove_notation_score_not_found():
    result = tools.remove_notation("nope", measure=1)
    assert_error(result, ErrorCode.SCORE_NOT_FOUND)


def test_remove_notation_measure_out_of_range(make_score):
    sid = make_score("simple_4_4")
    result = tools.remove_notation(sid, measure=99)
    err = assert_error(result, ErrorCode.MEASURE_OUT_OF_RANGE)
    assert "4 measures" in err["message"]


def test_remove_notation_beat_out_of_range(make_score):
    sid = make_score("simple_4_4")
    result = tools.remove_notation(sid, measure=1, beat=9)
    err = assert_error(result, ErrorCode.BEAT_OUT_OF_RANGE)
    assert "4 beats" in err["message"]


def test_remove_notation_invalid_notation_type(make_score):
    sid = make_score("simple_4_4")
    result = tools.remove_notation(sid, measure=1, beat=1, notation_type="wiggle")
    err = assert_error(result, ErrorCode.INVALID_ENUM_VALUE)
    assert "wiggle" in err["message"]
    assert "dynamic" in err["message"]


def test_remove_notation_part_not_found(make_score):
    sid = make_score("simple_4_4")
    result = tools.remove_notation(sid, measure=1, beat=1, part="Tuba")
    err = assert_error(result, ErrorCode.PART_NOT_FOUND)
    assert "Violin" in err["message"]


# ------------------------------------------------------------------ snapshots


def test_remove_notation_validation_failure_leaves_no_snapshot(make_score, snapshot_count):
    sid = make_score("simple_4_4")
    tools.add_dynamic(sid, measure=1, beat=1, dynamic="f")
    before_count = snapshot_count(sid)

    tools.remove_notation(sid, measure=99)
    tools.remove_notation(sid, measure=1, beat=1, notation_type="wiggle")
    tools.remove_notation(sid, measure=1, beat=9)
    tools.remove_notation(sid, measure=1, beat=1, part="Tuba")
    assert snapshot_count(sid) == before_count


def test_remove_notation_ambiguous_and_nothing_leave_no_snapshot(make_score, snapshot_count):
    sid = make_score("simple_4_4")
    tools.add_dynamic(sid, measure=1, beat=1, dynamic="f")
    tools.add_articulation(sid, measure=1, beat=1, articulation="staccato")
    before_count = snapshot_count(sid)

    tools.remove_notation(sid, measure=1, beat=1)  # ambiguous
    tools.remove_notation(sid, measure=3, beat=1)  # nothing to remove
    assert snapshot_count(sid) == before_count


def test_remove_notation_success_creates_snapshot_and_undo_restores_byte_identical(
    make_score, snapshot_count
):
    sid = make_score("simple_4_4")
    tools.add_dynamic(sid, measure=1, beat=1, dynamic="f")
    before_removal = storage.read_xml(sid)
    snapshots_before_removal = snapshot_count(sid)

    tools.remove_notation(sid, measure=1, beat=1)
    assert snapshot_count(sid) == snapshots_before_removal + 1
    after_removal = storage.read_xml(sid)
    assert after_removal != before_removal

    restored_label = storage.undo(sid)
    assert restored_label is not None
    assert storage.read_xml(sid) == before_removal


def test_remove_notation_changed_element_ids_is_always_empty_on_success(make_score):
    sid = make_score("simple_4_4")
    tools.add_dynamic(sid, measure=1, beat=1, dynamic="f")
    result = assert_success(tools.remove_notation(sid, measure=1, beat=1))
    assert result["changed_element_ids"] == []
