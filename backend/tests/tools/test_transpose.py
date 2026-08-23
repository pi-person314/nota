"""Tests for nota.mcp_server.pitch_tools.transpose."""

from __future__ import annotations

import music21 as m21

from nota import storage
from nota.mcp_server.errors import ErrorCode
from nota.mcp_server.pitch_tools import transpose
from nota.services.musicxml_repair import repair_spanner_order

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


def _write_score(score_id: str, score: m21.stream.Score) -> None:
    path = storage.path_for(score_id)
    score.write("musicxml", fp=path)
    with open(path, "r", encoding="utf-8") as f:
        xml = f.read()
    repaired = repair_spanner_order(xml)
    with open(path, "w", encoding="utf-8") as f:
        f.write(repaired)


def _make_score_with_empty_measure(make_score) -> str:
    """A score whose measure 2 is a full measure of rest (no notes at all)."""
    sid = make_score("simple_4_4")

    part = m21.stream.Part()
    part.id = "P1"
    part.partName = "Violin"

    m1 = m21.stream.Measure(number=1)
    m1.timeSignature = m21.meter.TimeSignature("4/4")
    m1.append([m21.note.Note(p, quarterLength=1) for p in ["C4", "D4", "E4", "F4"]])

    m2 = m21.stream.Measure(number=2)
    m2.append(m21.note.Rest(quarterLength=4))

    part.append([m1, m2])
    score = m21.stream.Score()
    score.append(part)

    _write_score(sid, score)
    return sid


# ---------------------------------------------------------------- basic transposition


def test_transpose_single_measure_up(make_score):
    sid = make_score("simple_4_4")
    # Measure 1: C4 D4 E4 F4.
    result = assert_success(
        transpose(sid, interval="major_second", direction="up", start_measure=1)
    )
    assert len(result["changed_element_ids"]) == 4
    assert_round_trips(sid)
    assert_ids_present(sid, result["changed_element_ids"])
    assert_renders_with_verovio(sid)
    assert "measure 1" in result["summary"]
    assert "up" in result["summary"]

    reparsed = _reparse(sid)
    measure1 = list(reparsed.parts)[0].measure(1)
    pitches = [n.pitch.nameWithOctave for n in sorted(measure1.recurse().notes, key=lambda n: n.offset)]
    assert pitches == ["D4", "E4", "F#4", "G4"]


def test_transpose_range_down(make_score):
    sid = make_score("simple_4_4")
    result = assert_success(
        transpose(sid, interval="octave", direction="down", start_measure=1, end_measure=2)
    )
    assert len(result["changed_element_ids"]) == 8
    assert_round_trips(sid)
    assert_ids_present(sid, result["changed_element_ids"])
    assert "measures 1" in result["summary"] and "2" in result["summary"]

    reparsed = _reparse(sid)
    part = list(reparsed.parts)[0]
    m1_pitches = [n.pitch.nameWithOctave for n in sorted(part.measure(1).recurse().notes, key=lambda n: n.offset)]
    m2_pitches = [n.pitch.nameWithOctave for n in sorted(part.measure(2).recurse().notes, key=lambda n: n.offset)]
    assert m1_pitches == ["C3", "D3", "E3", "F3"]
    assert m2_pitches == ["G3", "A3", "B3", "C4"]


def test_transpose_chords_transposed(make_score):
    sid = make_score("chords")
    result = assert_success(
        transpose(sid, interval="minor_third", direction="up", start_measure=1)
    )
    assert_round_trips(sid)
    assert_ids_present(sid, result["changed_element_ids"])

    reparsed = _reparse(sid)
    measure1 = list(reparsed.parts)[0].measure(1)
    chords = [n for n in measure1.recurse().notes if isinstance(n, m21.chord.Chord)]
    assert chords
    first_chord_pitches = {p.nameWithOctave for p in chords[0].pitches}
    assert first_chord_pitches == {"E-4", "G4", "B-4"}


def test_transpose_grace_note_transposed(make_score):
    sid = make_score("grace_notes")
    result = assert_success(
        transpose(sid, interval="whole_step", direction="up", start_measure=1)
    )
    assert_round_trips(sid)
    assert_ids_present(sid, result["changed_element_ids"])

    reparsed = _reparse(sid)
    measure1 = list(reparsed.parts)[0].measure(1)
    all_notes = sorted(measure1.recurse().notes, key=lambda n: n.offset)
    grace_notes = [n for n in all_notes if n.duration.isGrace]
    assert grace_notes
    # Original grace notes in the fixture are B4 and E5.
    grace_pitch_names = {n.pitch.nameWithOctave for n in grace_notes}
    assert grace_pitch_names == {"C#5", "F#5"}


# ---------------------------------------------------------------- measure range handling


def test_transpose_end_before_start_is_swapped(make_score):
    sid = make_score("simple_4_4")
    forward = assert_success(
        transpose(sid, interval="major_second", direction="up", start_measure=1, end_measure=2)
    )
    swapped_sid = make_score("simple_4_4")
    swapped = assert_success(
        transpose(swapped_sid, interval="major_second", direction="up", start_measure=2, end_measure=1)
    )

    def _all_pitches(score_id: str) -> list[str]:
        part = list(_reparse(score_id).parts)[0]
        return [n.pitch.nameWithOctave for n in sorted(part.recurse().notes, key=lambda n: n.offset)]

    assert len(forward["changed_element_ids"]) == len(swapped["changed_element_ids"]) == 8
    assert _all_pitches(sid) == _all_pitches(swapped_sid)
    assert "1" in forward["summary"] and "2" in forward["summary"]
    assert "1" in swapped["summary"] and "2" in swapped["summary"]


def test_transpose_default_end_measure_is_start_measure(make_score):
    sid = make_score("simple_4_4")
    result = assert_success(transpose(sid, interval="perfect_fifth", direction="up", start_measure=2))
    reparsed = _reparse(sid)
    part = list(reparsed.parts)[0]
    # Measure 1 (untouched) should still read its original pitches.
    m1_pitches = [n.pitch.nameWithOctave for n in sorted(part.measure(1).recurse().notes, key=lambda n: n.offset)]
    assert m1_pitches == ["C4", "D4", "E4", "F4"]
    assert len(result["changed_element_ids"]) == 4


def test_transpose_no_notes_in_range_is_no_op(make_score, snapshot_count):
    sid = _make_score_with_empty_measure(make_score)
    result = assert_success(transpose(sid, interval="major_second", direction="up", start_measure=2))
    assert result["changed_element_ids"] == []
    assert "no notes" in result["summary"].lower()
    assert snapshot_count(sid) == 0


# ---------------------------------------------------------------- errors


def test_transpose_invalid_interval(make_score):
    sid = make_score("simple_4_4")
    result = transpose(sid, interval="not_a_real_interval", direction="up", start_measure=1)
    err = assert_error(result, ErrorCode.INVALID_INTERVAL)
    assert "not_a_real_interval" in err["message"]


def test_transpose_invalid_direction(make_score):
    sid = make_score("simple_4_4")
    result = transpose(sid, interval="major_second", direction="sideways", start_measure=1)
    err = assert_error(result, ErrorCode.INVALID_INTERVAL)
    assert "sideways" in err["message"]


def test_transpose_measure_out_of_range(make_score):
    sid = make_score("simple_4_4")
    result = transpose(sid, interval="major_second", direction="up", start_measure=99)
    err = assert_error(result, ErrorCode.MEASURE_OUT_OF_RANGE)
    assert "4 measures" in err["message"]


def test_transpose_end_measure_out_of_range(make_score):
    sid = make_score("simple_4_4")
    result = transpose(sid, interval="major_second", direction="up", start_measure=1, end_measure=99)
    assert_error(result, ErrorCode.MEASURE_OUT_OF_RANGE)


def test_transpose_score_not_found():
    result = transpose("does-not-exist", interval="major_second", direction="up", start_measure=1)
    assert_error(result, ErrorCode.SCORE_NOT_FOUND)


def test_transpose_part_not_found(make_score):
    sid = make_score("simple_4_4")
    result = transpose(sid, interval="major_second", direction="up", start_measure=1, part="Tuba")
    err = assert_error(result, ErrorCode.PART_NOT_FOUND)
    assert "Violin" in err["message"]


def test_transpose_validation_failure_leaves_file_and_undo_stack_unchanged(
    make_score, snapshot_count
):
    sid = make_score("simple_4_4")
    before = storage.read_xml(sid)
    assert snapshot_count(sid) == 0

    transpose(sid, interval="major_second", direction="up", start_measure=99)
    assert snapshot_count(sid) == 0
    assert storage.read_xml(sid) == before


def test_transpose_success_creates_snapshot_and_undo_restores(make_score, snapshot_count):
    sid = make_score("simple_4_4")
    before = storage.read_xml(sid)

    transpose(sid, interval="major_second", direction="up", start_measure=1)
    assert snapshot_count(sid) == 1
    after = storage.read_xml(sid)
    assert after != before

    storage.undo(sid)
    assert storage.read_xml(sid) == before
