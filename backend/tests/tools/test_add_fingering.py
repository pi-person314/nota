"""Tests for nota.mcp_server.tools.add_fingering."""

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


def _notes_with_fingering(score, finger: int | None = None) -> list:
    matches = []
    for n in score.recurse().notes:
        for art in n.articulations:
            if isinstance(art, m21.articulations.Fingering) and (
                finger is None or art.fingerNumber == finger
            ):
                matches.append(n)
    return matches


# ---------------------------------------------------------------- happy path


def test_add_fingering_single_note_simple_4_4(make_score):
    sid = make_score("simple_4_4")
    result = assert_success(tools.add_fingering(sid, measure=1, beat=2, finger=3))

    assert len(result["changed_element_ids"]) == 1
    assert "3" in result["summary"]
    assert "measure 1" in result["summary"]
    assert "beat 2" in result["summary"]
    assert_round_trips(sid)
    assert_ids_present(sid, result["changed_element_ids"])
    assert_renders_with_verovio(sid)

    reparsed = _reparse(sid)
    marked = _notes_with_fingering(reparsed, finger=3)
    assert len(marked) == 1


def test_add_fingering_reported_id_is_the_note_id_not_inside_technical(make_score):
    """Regression-pin: music21's MusicXML writer drops a Fingering
    object's own id (it never reaches the <fingering> element it writes
    inside <notations><technical>), so the tool must fall back to
    reporting the parent note's id instead -- the same fallback idea as
    ORNAMENT_ID_SURVIVES_EXPORT's False entries.
    """
    sid = make_score("simple_4_4")
    result = assert_success(tools.add_fingering(sid, measure=1, beat=1, finger=2))
    xml = storage.read_xml(sid)
    assert_ids_present(sid, result["changed_element_ids"])

    reparsed = _reparse(sid)
    note = next(n for n in reparsed.recurse().notes if n.beat == 1.0 and n.measureNumber == 1)
    assert any(isinstance(a, m21.articulations.Fingering) for a in note.articulations)
    # The reported id lands on a <note id="...">, not inside <technical>.
    assert f'<note id="{result["changed_element_ids"][0]}"' in xml
    assert "<fingering" in xml


def test_add_fingering_open_string_zero(make_score):
    sid = make_score("simple_4_4")
    result = assert_success(tools.add_fingering(sid, measure=1, beat=1, finger=0))
    assert "0" in result["summary"]
    assert_round_trips(sid)
    assert_ids_present(sid, result["changed_element_ids"])

    reparsed = _reparse(sid)
    marked = _notes_with_fingering(reparsed, finger=0)
    assert len(marked) == 1


def test_add_fingering_every_valid_value(make_score):
    sid = make_score("simple_4_4")
    beats_and_measures = [(1, 1), (1, 2), (1, 3), (1, 4), (2, 1), (2, 2)]
    for finger, (measure, beat) in zip(sorted(tools.FINGER_VALUES), beats_and_measures):
        result = assert_success(
            tools.add_fingering(sid, measure=measure, beat=beat, finger=finger)
        )
        assert_ids_present(sid, result["changed_element_ids"])
    assert_round_trips(sid)
    assert_renders_with_verovio(sid)


def test_add_fingering_chord_target(make_score):
    sid = make_score("chords")
    result = assert_success(tools.add_fingering(sid, measure=1, beat=1, finger=4))
    assert len(result["changed_element_ids"]) == 1
    assert_round_trips(sid)
    assert_ids_present(sid, result["changed_element_ids"])

    reparsed = _reparse(sid)
    chords = [
        c
        for c in reparsed.recurse().getElementsByClass(m21.chord.Chord)
        if any(isinstance(a, m21.articulations.Fingering) for a in c.articulations)
    ]
    assert len(chords) == 1


def test_add_fingering_grace_note_position_prefers_main_note(make_score):
    sid = make_score("grace_notes")
    result = assert_success(tools.add_fingering(sid, measure=1, beat=1, finger=1))
    assert_round_trips(sid)
    assert_ids_present(sid, result["changed_element_ids"])

    reparsed = _reparse(sid)
    marked = _notes_with_fingering(reparsed, finger=1)
    assert len(marked) == 1
    assert not marked[0].duration.isGrace


def test_add_fingering_two_voices_targets_one_note(make_score):
    sid = make_score("two_voices")
    result = assert_success(tools.add_fingering(sid, measure=1, beat=2, finger=2))
    assert len(result["changed_element_ids"]) == 1
    assert_round_trips(sid)
    assert_ids_present(sid, result["changed_element_ids"])


def test_add_fingering_pickup_measure(make_score):
    sid = make_score("pickup")
    result = assert_success(tools.add_fingering(sid, measure=0, beat=4, finger=1))
    assert_round_trips(sid)
    assert_ids_present(sid, result["changed_element_ids"])
    assert_renders_with_verovio(sid)


# ---------------------------------------------------------------------- no-op


def test_add_fingering_duplicate_is_no_op(make_score, snapshot_count):
    sid = make_score("simple_4_4")
    first = assert_success(tools.add_fingering(sid, measure=1, beat=1, finger=3))
    assert snapshot_count(sid) == 1
    before = storage.read_xml(sid)

    second = assert_success(tools.add_fingering(sid, measure=1, beat=1, finger=3))
    assert second["changed_element_ids"] == []
    assert "already present" in second["summary"]
    # No new snapshot, and the file is untouched.
    assert snapshot_count(sid) == 1
    assert storage.read_xml(sid) == before
    assert first["changed_element_ids"]  # sanity: first call did change something


def test_add_fingering_different_finger_replaces_rather_than_stacks(make_score):
    """music21's MusicXML writer keeps only the first Fingering on a note
    and silently drops any later one, so the tool must replace the
    existing fingering rather than appending a second -- otherwise the
    "changed" call would report success while the old number stayed on
    disk. (See the add_fingering docstring for the empirical detail.)
    """
    sid = make_score("simple_4_4")
    tools.add_fingering(sid, measure=1, beat=1, finger=1)
    result = assert_success(tools.add_fingering(sid, measure=1, beat=1, finger=2))
    assert result["changed_element_ids"]

    reparsed = _reparse(sid)
    note = next(n for n in reparsed.recurse().notes if n.beat == 1.0 and n.measureNumber == 1)
    fingers = [a.fingerNumber for a in note.articulations if isinstance(a, m21.articulations.Fingering)]
    assert fingers == [2]


# ----------------------------------------------------------------- error paths


def test_add_fingering_score_not_found():
    result = tools.add_fingering("nope", measure=1, beat=1, finger=1)
    err = assert_error(result, ErrorCode.SCORE_NOT_FOUND)
    assert "nope" in err["message"]


def test_add_fingering_invalid_finger_negative(make_score):
    sid = make_score("simple_4_4")
    result = tools.add_fingering(sid, measure=1, beat=1, finger=-1)
    err = assert_error(result, ErrorCode.INVALID_ENUM_VALUE)
    assert "-1" in err["message"]
    assert "0" in err["message"] and "5" in err["message"]


def test_add_fingering_invalid_finger_too_high(make_score):
    sid = make_score("simple_4_4")
    result = tools.add_fingering(sid, measure=1, beat=1, finger=6)
    err = assert_error(result, ErrorCode.INVALID_ENUM_VALUE)
    assert "6" in err["message"]


def test_add_fingering_invalid_finger_nonsense(make_score):
    sid = make_score("simple_4_4")
    result = tools.add_fingering(sid, measure=1, beat=1, finger="banana")
    err = assert_error(result, ErrorCode.INVALID_ENUM_VALUE)
    assert "banana" in err["message"]


def test_add_fingering_invalid_finger_part_not_found(make_score):
    sid = make_score("chords")
    result = tools.add_fingering(sid, measure=1, beat=1, finger=1, part="Cello")
    err = assert_error(result, ErrorCode.PART_NOT_FOUND)
    assert "Guitar" in err["message"]


def test_add_fingering_measure_out_of_range(make_score):
    sid = make_score("simple_4_4")
    result = tools.add_fingering(sid, measure=99, beat=1, finger=1)
    err = assert_error(result, ErrorCode.MEASURE_OUT_OF_RANGE)
    assert "4 measures" in err["message"]


def test_add_fingering_beat_out_of_range(make_score):
    sid = make_score("simple_4_4")
    result = tools.add_fingering(sid, measure=1, beat=9, finger=1)
    err = assert_error(result, ErrorCode.BEAT_OUT_OF_RANGE)
    assert "4 beats" in err["message"]


def test_add_fingering_no_note_at_position(make_score):
    sid = make_score("simple_4_4")
    result = tools.add_fingering(sid, measure=1, beat=1.5, finger=1)
    assert_error(result, ErrorCode.NO_NOTE_AT_POSITION)


# ------------------------------------------------------------------ snapshots


def test_add_fingering_validation_failure_leaves_no_snapshot(make_score, snapshot_count):
    sid = make_score("simple_4_4")
    before = storage.read_xml(sid)

    tools.add_fingering(sid, measure=99, beat=1, finger=1)
    tools.add_fingering(sid, measure=1, beat=9, finger=1)
    tools.add_fingering(sid, measure=1, beat=1, finger=-1)
    tools.add_fingering(sid, measure=1, beat=1, finger=6)
    tools.add_fingering(sid, measure=1, beat=1, finger="banana")
    tools.add_fingering(sid, measure=1, beat=1.5, finger=1)
    tools.add_fingering(sid, measure=1, beat=1, finger=1, part="Nope")

    assert snapshot_count(sid) == 0
    assert storage.read_xml(sid) == before


def test_add_fingering_success_creates_snapshot_and_undo_restores(make_score, snapshot_count, undo_stack_labels):
    sid = make_score("simple_4_4")
    before = storage.read_xml(sid)

    tools.add_fingering(sid, measure=4, beat=2, finger=3)
    assert snapshot_count(sid) == 1
    labels = undo_stack_labels(sid)
    assert labels == ["add_fingering 3 m4 b2"]
    assert storage.read_xml(sid) != before

    restored_label = storage.undo(sid)
    assert restored_label == "add_fingering 3 m4 b2"
    assert storage.read_xml(sid) == before


# ------------------------------------------------------------ remove_notation


def test_remove_notation_fingering_family(make_score):
    sid = make_score("simple_4_4")
    tools.add_fingering(sid, measure=1, beat=1, finger=3)

    result = assert_success(
        tools.remove_notation(sid, measure=1, beat=1, notation_type="fingering")
    )
    assert "fingering 3" in result["summary"]
    assert_round_trips(sid)

    reparsed = _reparse(sid)
    note = next(n for n in reparsed.recurse().notes if n.beat == 1.0 and n.measureNumber == 1)
    assert not any(isinstance(a, m21.articulations.Fingering) for a in note.articulations)


def test_remove_notation_articulation_family_excludes_fingering(make_score):
    """A note carrying both a staccato and a fingering: removing the
    "articulation" family must take only the staccato, never the
    fingering (music21 models Fingering as an Articulation subclass, so
    without an explicit exclusion the articulation family would
    ambiguously or silently pick it up too).
    """
    sid = make_score("simple_4_4")
    tools.add_articulation(sid, measure=1, beat=1, articulation="staccato")
    tools.add_fingering(sid, measure=1, beat=1, finger=2)

    result = assert_success(
        tools.remove_notation(sid, measure=1, beat=1, notation_type="articulation")
    )
    assert "staccato" in result["summary"]

    reparsed = _reparse(sid)
    note = next(n for n in reparsed.recurse().notes if n.beat == 1.0 and n.measureNumber == 1)
    remaining = list(note.articulations)
    assert not any(isinstance(a, m21.articulations.Staccato) for a in remaining)
    assert any(
        isinstance(a, m21.articulations.Fingering) and a.fingerNumber == 2 for a in remaining
    )


def test_remove_notation_ambiguous_between_articulation_and_fingering(make_score):
    sid = make_score("simple_4_4")
    tools.add_articulation(sid, measure=1, beat=1, articulation="staccato")
    tools.add_fingering(sid, measure=1, beat=1, finger=2)

    result = tools.remove_notation(sid, measure=1, beat=1)
    err = assert_error(result, ErrorCode.AMBIGUOUS_TARGET)
    assert "staccato" in err["message"]
    assert "fingering 2" in err["message"]


def test_remove_notation_nothing_of_fingering_type(make_score):
    sid = make_score("simple_4_4")
    tools.add_articulation(sid, measure=1, beat=1, articulation="staccato")

    result = tools.remove_notation(sid, measure=1, beat=1, notation_type="fingering")
    err = assert_error(result, ErrorCode.NOTHING_TO_REMOVE)
    assert "fingering" in err["message"]
