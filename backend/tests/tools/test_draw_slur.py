"""Tests for nota.mcp_server.tools.draw_slur."""

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


def test_draw_slur_within_one_measure(make_score):
    sid = make_score("simple_4_4")
    result = assert_success(
        tools.draw_slur(sid, start_measure=1, start_beat=1, end_measure=1, end_beat=4)
    )
    assert len(result["changed_element_ids"]) == 2
    xml = assert_round_trips(sid)
    assert_ids_present(sid, result["changed_element_ids"])
    assert_renders_with_verovio(sid)

    reparsed = m21.converter.parse(xml.encode("utf-8"), format="musicxml")
    slurs = list(reparsed.recurse().getElementsByClass(m21.spanner.Slur))
    assert len(slurs) == 1


def test_draw_slur_across_barline(make_score):
    sid = make_score("simple_4_4")
    result = assert_success(
        tools.draw_slur(sid, start_measure=1, start_beat=4, end_measure=2, end_beat=1)
    )
    assert len(result["changed_element_ids"]) == 2
    assert_round_trips(sid)
    assert_ids_present(sid, result["changed_element_ids"])


def test_draw_slur_across_meter_change(make_score):
    sid = make_score("meter_change")
    result = assert_success(
        tools.draw_slur(sid, start_measure=4, start_beat=4, end_measure=5, end_beat=1)
    )
    assert_round_trips(sid)
    assert_ids_present(sid, result["changed_element_ids"])


def test_draw_slur_chords_count_as_one_note(make_score):
    sid = make_score("chords")
    result = assert_success(
        tools.draw_slur(sid, start_measure=1, start_beat=1, end_measure=1, end_beat=2)
    )
    assert_round_trips(sid)
    assert_ids_present(sid, result["changed_element_ids"])


def test_draw_slur_no_note_at_start_position(make_score):
    sid = make_score("simple_4_4")
    # Beat 1.5 has no note starting there in the simple quarter-note fixture.
    result = tools.draw_slur(sid, start_measure=1, start_beat=1.5, end_measure=1, end_beat=4)
    err = assert_error(result, ErrorCode.NO_NOTE_AT_POSITION)
    assert "measure 1" in err["message"]


def test_draw_slur_no_note_at_end_position(make_score):
    sid = make_score("simple_4_4")
    result = tools.draw_slur(sid, start_measure=1, start_beat=1, end_measure=1, end_beat=3.5)
    assert_error(result, ErrorCode.NO_NOTE_AT_POSITION)


def test_draw_slur_measure_out_of_range(make_score):
    sid = make_score("simple_4_4")
    result = tools.draw_slur(sid, start_measure=1, start_beat=1, end_measure=50, end_beat=1)
    err = assert_error(result, ErrorCode.MEASURE_OUT_OF_RANGE)
    assert "4 measures" in err["message"]


def test_draw_slur_beat_out_of_range(make_score):
    sid = make_score("simple_4_4")
    result = tools.draw_slur(sid, start_measure=1, start_beat=1, end_measure=1, end_beat=9)
    err = assert_error(result, ErrorCode.BEAT_OUT_OF_RANGE)
    assert "4 beats" in err["message"]


def test_draw_slur_part_not_found(make_score):
    sid = make_score("simple_4_4")
    result = tools.draw_slur(
        sid, start_measure=1, start_beat=1, end_measure=1, end_beat=4, part="Tuba"
    )
    err = assert_error(result, ErrorCode.PART_NOT_FOUND)
    assert "Violin" in err["message"]


def test_draw_slur_validation_failure_leaves_no_snapshot(make_score, snapshot_count):
    sid = make_score("simple_4_4")
    tools.draw_slur(sid, start_measure=1, start_beat=1.5, end_measure=1, end_beat=4)
    assert snapshot_count(sid) == 0


def test_draw_slur_success_creates_snapshot_and_undo_restores(make_score, snapshot_count):
    sid = make_score("simple_4_4")
    before = storage.read_xml(sid)

    tools.draw_slur(sid, start_measure=1, start_beat=1, end_measure=1, end_beat=4)
    assert snapshot_count(sid) == 1
    after = storage.read_xml(sid)
    assert after != before

    storage.undo(sid)
    assert storage.read_xml(sid) == before


def test_draw_slur_grace_note_endpoint_prefers_main_note(make_score):
    sid = make_score("grace_notes")
    # Beat 1 in the grace_notes fixture has both a grace note and the main
    # note sharing beat==1.0; the main note should be the resolved target.
    result = assert_success(
        tools.draw_slur(sid, start_measure=1, start_beat=1, end_measure=1, end_beat=2)
    )
    assert_round_trips(sid)
    assert_ids_present(sid, result["changed_element_ids"])
