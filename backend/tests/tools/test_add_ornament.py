"""Tests for nota.mcp_server.tools.add_ornament."""

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


def test_add_ornament_every_enum_value(make_score):
    sid = make_score("simple_4_4")
    beats_and_measures = [(1, 1), (1, 2), (1, 3), (1, 4), (2, 1), (2, 2)]
    for name, (measure, beat) in zip(sorted(tools.ORNAMENT_MAP), beats_and_measures):
        result = assert_success(
            tools.add_ornament(sid, measure=measure, beat=beat, ornament=name)
        )
        assert len(result["changed_element_ids"]) == 1
        assert_ids_present(sid, result["changed_element_ids"])
    assert_round_trips(sid)
    assert_renders_with_verovio(sid)


def test_add_ornament_trill_falls_back_to_note_id(make_score):
    """Regression-pin: music21's writer drops a Trill's own id (it never
    reaches the <trill-mark> it emits), so the tool must fall back to
    reporting the note's id instead — mirroring ids.py's chord fallback.
    """
    sid = make_score("simple_4_4")
    result = assert_success(tools.add_ornament(sid, measure=1, beat=1, ornament="trill"))
    xml = storage.read_xml(sid)
    assert_ids_present(sid, result["changed_element_ids"])

    reparsed = _reparse(sid)
    note = next(n for n in reparsed.recurse().notes if n.beat == 1.0 and n.measureNumber == 1)
    assert any(isinstance(e, m21.expressions.Trill) for e in note.expressions)
    # The reported id is the note's id (a <note id="...">), not an id
    # anywhere inside <ornaments>/<trill-mark>.
    assert f'id="{result["changed_element_ids"][0]}"' in xml
    assert "trill-mark" in xml


def test_add_ornament_mordent_falls_back_to_note_id(make_score):
    sid = make_score("simple_4_4")
    result = assert_success(tools.add_ornament(sid, measure=1, beat=1, ornament="mordent"))
    assert_ids_present(sid, result["changed_element_ids"])


def test_add_ornament_inverted_mordent_falls_back_to_note_id(make_score):
    sid = make_score("simple_4_4")
    result = assert_success(
        tools.add_ornament(sid, measure=1, beat=1, ornament="inverted_mordent")
    )
    assert_ids_present(sid, result["changed_element_ids"])


def test_add_ornament_turn_falls_back_to_note_id(make_score):
    sid = make_score("simple_4_4")
    result = assert_success(tools.add_ornament(sid, measure=1, beat=1, ornament="turn"))
    assert_ids_present(sid, result["changed_element_ids"])


def test_add_ornament_tremolo_falls_back_to_note_id(make_score):
    sid = make_score("simple_4_4")
    result = assert_success(tools.add_ornament(sid, measure=1, beat=1, ornament="tremolo"))
    assert_ids_present(sid, result["changed_element_ids"])


def test_add_ornament_fermata_id_survives_export(make_score):
    """Regression-pin: unlike the other ornament types, music21 does carry
    a Fermata's own id through to the <fermata> element, so the tool
    reports that id directly rather than falling back to the note.
    """
    sid = make_score("simple_4_4")
    result = assert_success(tools.add_ornament(sid, measure=1, beat=1, ornament="fermata"))
    xml = storage.read_xml(sid)
    assert_ids_present(sid, result["changed_element_ids"])
    assert f'<fermata id="{result["changed_element_ids"][0]}"' in xml

    reparsed = _reparse(sid)
    note = next(n for n in reparsed.recurse().notes if n.beat == 1.0 and n.measureNumber == 1)
    assert any(isinstance(e, m21.expressions.Fermata) for e in note.expressions)


def test_add_ornament_chord_target(make_score):
    sid = make_score("chords")
    result = assert_success(tools.add_ornament(sid, measure=1, beat=1, ornament="trill"))
    assert len(result["changed_element_ids"]) == 1
    assert_round_trips(sid)
    assert_ids_present(sid, result["changed_element_ids"])

    reparsed = _reparse(sid)
    chords = [
        c
        for c in reparsed.recurse().getElementsByClass(m21.chord.Chord)
        if any(isinstance(e, m21.expressions.Trill) for e in c.expressions)
    ]
    assert len(chords) == 1


def test_add_ornament_compound_6_8(make_score):
    sid = make_score("compound_6_8")
    result = assert_success(tools.add_ornament(sid, measure=1, beat=2, ornament="turn"))
    assert_round_trips(sid)
    assert_ids_present(sid, result["changed_element_ids"])


def test_add_ornament_pickup_measure(make_score):
    sid = make_score("pickup")
    result = assert_success(tools.add_ornament(sid, measure=0, beat=4, ornament="fermata"))
    assert_round_trips(sid)
    assert_ids_present(sid, result["changed_element_ids"])
    assert_renders_with_verovio(sid)


def test_add_ornament_grace_note_position_prefers_main_note(make_score):
    sid = make_score("grace_notes")
    result = assert_success(tools.add_ornament(sid, measure=1, beat=1, ornament="trill"))
    assert_round_trips(sid)
    assert_ids_present(sid, result["changed_element_ids"])

    reparsed = _reparse(sid)
    marked = [
        n
        for n in reparsed.recurse().notes
        if any(isinstance(e, m21.expressions.Trill) for e in n.expressions)
    ]
    assert len(marked) == 1
    assert not marked[0].duration.isGrace


def test_add_ornament_two_voices_targets_one_note(make_score):
    sid = make_score("two_voices")
    result = assert_success(tools.add_ornament(sid, measure=1, beat=2, ornament="trill"))
    assert len(result["changed_element_ids"]) == 1
    assert_round_trips(sid)
    assert_ids_present(sid, result["changed_element_ids"])


# ----------------------------------------------------------------- error paths


def test_add_ornament_score_not_found():
    result = tools.add_ornament("nope", measure=1, beat=1, ornament="trill")
    err = assert_error(result, ErrorCode.SCORE_NOT_FOUND)
    assert "nope" in err["message"]


def test_add_ornament_invalid_enum(make_score):
    sid = make_score("simple_4_4")
    result = tools.add_ornament(sid, measure=1, beat=1, ornament="wiggle")
    err = assert_error(result, ErrorCode.INVALID_ENUM_VALUE)
    assert "wiggle" in err["message"]
    assert "trill" in err["message"]


def test_add_ornament_measure_out_of_range(make_score):
    sid = make_score("simple_4_4")
    result = tools.add_ornament(sid, measure=99, beat=1, ornament="trill")
    err = assert_error(result, ErrorCode.MEASURE_OUT_OF_RANGE)
    assert "4 measures" in err["message"]


def test_add_ornament_beat_out_of_range(make_score):
    sid = make_score("simple_4_4")
    result = tools.add_ornament(sid, measure=1, beat=9, ornament="trill")
    err = assert_error(result, ErrorCode.BEAT_OUT_OF_RANGE)
    assert "4 beats" in err["message"]


def test_add_ornament_no_note_at_position(make_score):
    sid = make_score("simple_4_4")
    result = tools.add_ornament(sid, measure=1, beat=1.5, ornament="trill")
    assert_error(result, ErrorCode.NO_NOTE_AT_POSITION)


def test_add_ornament_part_not_found(make_score):
    sid = make_score("simple_4_4")
    result = tools.add_ornament(sid, measure=1, beat=1, ornament="trill", part="Tuba")
    err = assert_error(result, ErrorCode.PART_NOT_FOUND)
    assert "Violin" in err["message"]


# ------------------------------------------------------------------ snapshots


def test_add_ornament_validation_failure_leaves_no_snapshot(make_score, snapshot_count):
    sid = make_score("simple_4_4")
    tools.add_ornament(sid, measure=99, beat=1, ornament="trill")
    tools.add_ornament(sid, measure=1, beat=9, ornament="trill")
    tools.add_ornament(sid, measure=1, beat=1, ornament="wiggle")
    tools.add_ornament(sid, measure=1, beat=1.5, ornament="trill")
    assert snapshot_count(sid) == 0


def test_add_ornament_success_creates_snapshot_and_undo_restores(make_score, snapshot_count):
    sid = make_score("simple_4_4")
    before = storage.read_xml(sid)

    tools.add_ornament(sid, measure=1, beat=1, ornament="trill")
    assert snapshot_count(sid) == 1
    assert storage.read_xml(sid) != before

    storage.undo(sid)
    assert storage.read_xml(sid) == before
