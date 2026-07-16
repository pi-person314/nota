"""Tests for nota.mcp_server.tools.draw_hairpin."""

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


def test_draw_hairpin_crescendo_within_one_measure(make_score):
    sid = make_score("simple_4_4")
    result = assert_success(
        tools.draw_hairpin(
            sid, start_measure=1, start_beat=1, end_measure=1, end_beat=4, direction="crescendo"
        )
    )
    assert len(result["changed_element_ids"]) == 2
    xml = assert_round_trips(sid)
    assert_ids_present(sid, result["changed_element_ids"])
    assert_renders_with_verovio(sid)

    reparsed = m21.converter.parse(xml.encode("utf-8"), format="musicxml")
    wedges = list(reparsed.recurse().getElementsByClass(m21.dynamics.Crescendo))
    assert len(wedges) == 1


def test_draw_hairpin_decrescendo(make_score):
    sid = make_score("simple_4_4")
    result = assert_success(
        tools.draw_hairpin(
            sid, start_measure=1, start_beat=1, end_measure=1, end_beat=4, direction="decrescendo"
        )
    )
    xml = assert_round_trips(sid)
    assert_ids_present(sid, result["changed_element_ids"])
    reparsed = m21.converter.parse(xml.encode("utf-8"), format="musicxml")
    assert list(reparsed.recurse().getElementsByClass(m21.dynamics.Diminuendo))


def test_draw_hairpin_diminuendo_synonym_maps_to_decrescendo(make_score):
    sid = make_score("simple_4_4")
    result = assert_success(
        tools.draw_hairpin(
            sid, start_measure=1, start_beat=1, end_measure=1, end_beat=4, direction="diminuendo"
        )
    )
    xml = assert_round_trips(sid)
    assert_ids_present(sid, result["changed_element_ids"])
    reparsed = m21.converter.parse(xml.encode("utf-8"), format="musicxml")
    assert list(reparsed.recurse().getElementsByClass(m21.dynamics.Diminuendo))
    assert not list(reparsed.recurse().getElementsByClass(m21.dynamics.Crescendo))


def test_draw_hairpin_across_barline(make_score):
    sid = make_score("simple_4_4")
    result = assert_success(
        tools.draw_hairpin(
            sid, start_measure=1, start_beat=4, end_measure=2, end_beat=1, direction="crescendo"
        )
    )
    assert_round_trips(sid)
    assert_ids_present(sid, result["changed_element_ids"])


def test_draw_hairpin_across_meter_change(make_score):
    sid = make_score("meter_change")
    result = assert_success(
        tools.draw_hairpin(
            sid, start_measure=4, start_beat=4, end_measure=5, end_beat=1, direction="crescendo"
        )
    )
    assert_round_trips(sid)
    assert_ids_present(sid, result["changed_element_ids"])


def test_draw_hairpin_chords_count_as_one_note(make_score):
    sid = make_score("chords")
    result = assert_success(
        tools.draw_hairpin(
            sid, start_measure=1, start_beat=1, end_measure=1, end_beat=2, direction="crescendo"
        )
    )
    assert_round_trips(sid)
    assert_ids_present(sid, result["changed_element_ids"])


def test_draw_hairpin_pickup_measure(make_score):
    sid = make_score("pickup")
    result = assert_success(
        tools.draw_hairpin(
            sid, start_measure=0, start_beat=4, end_measure=1, end_beat=1, direction="crescendo"
        )
    )
    assert_round_trips(sid)
    assert_ids_present(sid, result["changed_element_ids"])
    assert_renders_with_verovio(sid)


def test_draw_hairpin_grace_note_endpoint_prefers_main_note(make_score):
    sid = make_score("grace_notes")
    result = assert_success(
        tools.draw_hairpin(
            sid, start_measure=1, start_beat=1, end_measure=1, end_beat=2, direction="crescendo"
        )
    )
    assert_round_trips(sid)
    assert_ids_present(sid, result["changed_element_ids"])


def test_draw_hairpin_two_voices(make_score):
    sid = make_score("two_voices")
    result = assert_success(
        tools.draw_hairpin(
            sid, start_measure=1, start_beat=1, end_measure=1, end_beat=4, direction="crescendo"
        )
    )
    assert_round_trips(sid)
    assert_ids_present(sid, result["changed_element_ids"])


# ----------------------------------------------------------------- error paths


def test_draw_hairpin_score_not_found():
    result = tools.draw_hairpin(
        "nope", start_measure=1, start_beat=1, end_measure=1, end_beat=2, direction="crescendo"
    )
    assert_error(result, ErrorCode.SCORE_NOT_FOUND)


def test_draw_hairpin_invalid_direction(make_score):
    sid = make_score("simple_4_4")
    result = tools.draw_hairpin(
        sid, start_measure=1, start_beat=1, end_measure=1, end_beat=2, direction="louder"
    )
    err = assert_error(result, ErrorCode.INVALID_ENUM_VALUE)
    assert "louder" in err["message"]
    assert "crescendo" in err["message"]


def test_draw_hairpin_no_note_at_start_position(make_score):
    sid = make_score("simple_4_4")
    result = tools.draw_hairpin(
        sid, start_measure=1, start_beat=1.5, end_measure=1, end_beat=4, direction="crescendo"
    )
    err = assert_error(result, ErrorCode.NO_NOTE_AT_POSITION)
    assert "measure 1" in err["message"]


def test_draw_hairpin_no_note_at_end_position(make_score):
    sid = make_score("simple_4_4")
    result = tools.draw_hairpin(
        sid, start_measure=1, start_beat=1, end_measure=1, end_beat=3.5, direction="crescendo"
    )
    assert_error(result, ErrorCode.NO_NOTE_AT_POSITION)


def test_draw_hairpin_measure_out_of_range(make_score):
    sid = make_score("simple_4_4")
    result = tools.draw_hairpin(
        sid, start_measure=1, start_beat=1, end_measure=50, end_beat=1, direction="crescendo"
    )
    err = assert_error(result, ErrorCode.MEASURE_OUT_OF_RANGE)
    assert "4 measures" in err["message"]


def test_draw_hairpin_beat_out_of_range(make_score):
    sid = make_score("simple_4_4")
    result = tools.draw_hairpin(
        sid, start_measure=1, start_beat=1, end_measure=1, end_beat=9, direction="crescendo"
    )
    err = assert_error(result, ErrorCode.BEAT_OUT_OF_RANGE)
    assert "4 beats" in err["message"]


def test_draw_hairpin_part_not_found(make_score):
    sid = make_score("simple_4_4")
    result = tools.draw_hairpin(
        sid,
        start_measure=1,
        start_beat=1,
        end_measure=1,
        end_beat=4,
        direction="crescendo",
        part="Tuba",
    )
    err = assert_error(result, ErrorCode.PART_NOT_FOUND)
    assert "Violin" in err["message"]


# ------------------------------------------------------------------ snapshots


def test_draw_hairpin_validation_failure_leaves_no_snapshot(make_score, snapshot_count):
    sid = make_score("simple_4_4")
    tools.draw_hairpin(
        sid, start_measure=1, start_beat=1.5, end_measure=1, end_beat=4, direction="crescendo"
    )
    assert snapshot_count(sid) == 0


def test_draw_hairpin_success_creates_snapshot_and_undo_restores(make_score, snapshot_count):
    sid = make_score("simple_4_4")
    before = storage.read_xml(sid)

    tools.draw_hairpin(
        sid, start_measure=1, start_beat=1, end_measure=1, end_beat=4, direction="crescendo"
    )
    assert snapshot_count(sid) == 1
    after = storage.read_xml(sid)
    assert after != before

    storage.undo(sid)
    assert storage.read_xml(sid) == before


def test_draw_hairpin_wedge_id_serializes_but_tool_still_returns_note_ids(make_score):
    """Documentation/regression test: unlike Slur, music21's writer *does*
    carry a Crescendo/Diminuendo spanner's own id through to the <wedge>
    elements it emits. draw_hairpin still reports the two endpoint note
    ids (not the wedge's id) for consistency with draw_slur's highlighting
    contract; this pins that choice so a future refactor notices if it
    silently changes.
    """
    sid = make_score("simple_4_4")
    result = assert_success(
        tools.draw_hairpin(
            sid, start_measure=1, start_beat=1, end_measure=1, end_beat=2, direction="crescendo"
        )
    )
    xml = storage.read_xml(sid)
    assert "<wedge" in xml
    for element_id in result["changed_element_ids"]:
        # The reported ids are note ids, not the wedge's — confirm they
        # land on <note> elements, not on the <wedge>/<direction> markup.
        assert f'id="{element_id}"' in xml
