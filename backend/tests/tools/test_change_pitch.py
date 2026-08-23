"""Tests for nota.mcp_server.pitch_tools.change_pitch."""

from __future__ import annotations

import music21 as m21

from nota import storage
from nota.mcp_server import notes, tools
from nota.mcp_server.errors import ErrorCode
from nota.mcp_server.pitch_tools import change_pitch
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
    """Overwrite a score already registered via make_score with custom
    music21 content, repaired the same way a real upload's would be (see
    conftest.py's `_build_fixture_cache`) so it matches what the harness
    expects to find on disk.
    """
    path = storage.path_for(score_id)
    score.write("musicxml", fp=path)
    with open(path, "r", encoding="utf-8") as f:
        xml = f.read()
    repaired = repair_spanner_order(xml)
    with open(path, "w", encoding="utf-8") as f:
        f.write(repaired)


def _make_tied_score(make_score) -> str:
    """A fresh score (registered via make_score, then overwritten) with a
    tie chain: two half-note C4s tied together across beats 1 and 3 of
    measure 1, followed by a plain measure 2.
    """
    sid = make_score("simple_4_4")

    part = m21.stream.Part()
    part.id = "P1"
    part.partName = "Violin"

    m1 = m21.stream.Measure(number=1)
    m1.timeSignature = m21.meter.TimeSignature("4/4")
    n1 = m21.note.Note("C4", quarterLength=2)
    n1.tie = m21.tie.Tie("start")
    n2 = m21.note.Note("C4", quarterLength=2)
    n2.tie = m21.tie.Tie("stop")
    m1.append([n1, n2])

    m2 = m21.stream.Measure(number=2)
    m2.append([m21.note.Note(p, quarterLength=1) for p in ["D4", "E4", "F4", "G4"]])

    part.append([m1, m2])
    score = m21.stream.Score()
    score.append(part)

    _write_score(sid, score)
    return sid


# ---------------------------------------------------------------- basic targeting


def test_change_pitch_by_beat_simple(make_score):
    sid = make_score("simple_4_4")
    # Measure 1 beat 1 is C4 in simple_4_4.
    result = assert_success(change_pitch(sid, measure=1, beat=1, pitch="D"))
    assert len(result["changed_element_ids"]) == 1
    assert_round_trips(sid)
    assert_ids_present(sid, result["changed_element_ids"])
    assert_renders_with_verovio(sid)
    assert "C4" in result["summary"]
    assert "measure 1" in result["summary"]

    reparsed = _reparse(sid)
    measure1 = list(reparsed.parts)[0].measure(1)
    note1 = measure1.recurse().notes[0]
    assert note1.pitch.step == "D"


def test_change_pitch_preserves_duration_and_articulation(make_score):
    sid = make_score("simple_4_4")
    tools.add_articulation(sid, measure=1, beat=2, articulation="staccato")

    result = assert_success(change_pitch(sid, measure=1, beat=2, pitch="G"))
    assert_ids_present(sid, result["changed_element_ids"])

    reparsed = _reparse(sid)
    measure1 = list(reparsed.parts)[0].measure(1)
    target = [n for n in measure1.recurse().notes if abs(n.offset - 1.0) < 1e-6][0]
    assert target.pitch.step == "G"
    assert target.duration.quarterLength == 1.0
    assert any(isinstance(a, m21.articulations.Staccato) for a in target.articulations)


def test_change_pitch_octave_nearest_when_not_given(make_score):
    sid = make_score("simple_4_4")
    # Measure 1 beat 2 is D4. Asking for "A" with no octave should pick
    # the octave-nearest A to D4.
    reference = m21.pitch.Pitch("D4")
    expected = notes.realize_pitch(notes.parse_pitch_spec("A"), reference)

    result = assert_success(change_pitch(sid, measure=1, beat=2, pitch="A"))
    reparsed = _reparse(sid)
    measure1 = list(reparsed.parts)[0].measure(1)
    target = [n for n in measure1.recurse().notes if abs(n.offset - 1.0) < 1e-6][0]
    assert target.pitch.nameWithOctave == expected.nameWithOctave
    assert result["changed_element_ids"]


def test_change_pitch_explicit_octave_honored(make_score):
    sid = make_score("simple_4_4")
    result = assert_success(change_pitch(sid, measure=1, beat=2, pitch="G5"))
    reparsed = _reparse(sid)
    measure1 = list(reparsed.parts)[0].measure(1)
    target = [n for n in measure1.recurse().notes if abs(n.offset - 1.0) < 1e-6][0]
    assert target.pitch.nameWithOctave == "G5"
    assert result["changed_element_ids"]


# ---------------------------------------------------------------- chords


def test_change_pitch_chord_without_from_pitch_is_ambiguous(make_score):
    sid = make_score("chords")
    result = change_pitch(sid, measure=1, beat=1, pitch="D")
    err = assert_error(result, ErrorCode.AMBIGUOUS_TARGET)
    assert "C4" in err["message"] and "E4" in err["message"] and "G4" in err["message"]


def test_change_pitch_chord_with_from_pitch_changes_only_that_member(make_score):
    sid = make_score("chords")
    result = assert_success(
        change_pitch(sid, measure=1, beat=1, pitch="F", from_pitch="E")
    )
    assert_ids_present(sid, result["changed_element_ids"])

    reparsed = _reparse(sid)
    measure1 = list(reparsed.parts)[0].measure(1)
    chord_obj = [
        n for n in measure1.recurse().notes if isinstance(n, m21.chord.Chord) and abs(n.offset) < 1e-6
    ][0]
    names = {p.nameWithOctave for p in chord_obj.pitches}
    assert "C4" in names
    assert "G4" in names
    assert "E4" not in names
    assert any(name.startswith("F") for name in names)


def test_change_pitch_chord_member_not_found(make_score):
    sid = make_score("chords")
    result = change_pitch(sid, measure=1, beat=1, pitch="D", from_pitch="B")
    err = assert_error(result, ErrorCode.NO_NOTE_AT_POSITION)
    assert "C4" in err["message"] and "E4" in err["message"] and "G4" in err["message"]


# ---------------------------------------------------------------- targeting by from_pitch alone


def test_change_pitch_by_from_pitch_unique_match(make_score):
    sid = make_score("chords")
    # Measure 1: chord(C4,E4,G4) at beat1, D4 at beat2, chord(F4,A4,C5) at
    # beat3. "D" only matches the plain note at beat 2.
    result = assert_success(change_pitch(sid, measure=1, pitch="A", from_pitch="D"))
    assert_ids_present(sid, result["changed_element_ids"])

    reparsed = _reparse(sid)
    measure1 = list(reparsed.parts)[0].measure(1)
    target = [n for n in measure1.recurse().notes if abs(n.offset - 1.0) < 1e-6][0]
    assert target.pitch.step == "A"


def test_change_pitch_by_from_pitch_multiple_matches_is_ambiguous(make_score):
    sid = make_score("chords")
    # "C" matches C4 in the first chord and C5 in the third chord.
    result = change_pitch(sid, measure=1, pitch="D", from_pitch="C")
    err = assert_error(result, ErrorCode.AMBIGUOUS_TARGET)
    assert "beat" in err["message"].lower()


def test_change_pitch_by_from_pitch_no_match(make_score):
    sid = make_score("chords")
    result = change_pitch(sid, measure=1, pitch="D", from_pitch="B")
    err = assert_error(result, ErrorCode.NO_NOTE_AT_POSITION)
    assert "measure 1" in err["message"]


def test_change_pitch_neither_beat_nor_from_pitch_is_ambiguous(make_score):
    sid = make_score("simple_4_4")
    result = change_pitch(sid, measure=1, pitch="D")
    err = assert_error(result, ErrorCode.AMBIGUOUS_TARGET)
    assert "beat" in err["message"].lower()


# ---------------------------------------------------------------- ties


def test_change_pitch_tied_pair_changes_both_notes(make_score):
    sid = _make_tied_score(make_score)
    result = assert_success(change_pitch(sid, measure=1, beat=1, pitch="D"))
    assert len(result["changed_element_ids"]) == 2
    xml = assert_round_trips(sid)
    assert_ids_present(sid, result["changed_element_ids"])

    reparsed = m21.converter.parse(xml.encode("utf-8"), format="musicxml")
    measure1 = list(reparsed.parts)[0].measure(1)
    tied_notes = sorted(measure1.recurse().notes, key=lambda n: n.offset)
    assert len(tied_notes) == 2
    assert all(n.pitch.nameWithOctave == "D4" for n in tied_notes)
    assert tied_notes[0].tie is not None and tied_notes[0].tie.type == "start"
    assert tied_notes[1].tie is not None and tied_notes[1].tie.type == "stop"


# ---------------------------------------------------------------- no-op / errors


def test_change_pitch_no_op_when_already_that_pitch(make_score, snapshot_count):
    sid = make_score("simple_4_4")
    result = assert_success(change_pitch(sid, measure=1, beat=1, pitch="C4"))
    assert result["changed_element_ids"] == []
    assert "already" in result["summary"]
    assert snapshot_count(sid) == 0


def test_change_pitch_invalid_pitch_string(make_score):
    sid = make_score("simple_4_4")
    result = change_pitch(sid, measure=1, beat=1, pitch="H4")
    assert_error(result, ErrorCode.INVALID_PITCH)


def test_change_pitch_invalid_from_pitch_string(make_score):
    sid = make_score("simple_4_4")
    result = change_pitch(sid, measure=1, pitch="D", from_pitch="H")
    assert_error(result, ErrorCode.INVALID_PITCH)


def test_change_pitch_score_not_found():
    result = change_pitch("does-not-exist", measure=1, beat=1, pitch="D")
    assert_error(result, ErrorCode.SCORE_NOT_FOUND)


def test_change_pitch_measure_out_of_range(make_score):
    sid = make_score("simple_4_4")
    result = change_pitch(sid, measure=99, beat=1, pitch="D")
    err = assert_error(result, ErrorCode.MEASURE_OUT_OF_RANGE)
    assert "4 measures" in err["message"]


def test_change_pitch_beat_out_of_range(make_score):
    sid = make_score("simple_4_4")
    result = change_pitch(sid, measure=1, beat=9, pitch="D")
    assert_error(result, ErrorCode.BEAT_OUT_OF_RANGE)


def test_change_pitch_no_note_at_beat(make_score):
    sid = make_score("simple_4_4")
    result = change_pitch(sid, measure=1, beat=1.5, pitch="D")
    assert_error(result, ErrorCode.NO_NOTE_AT_POSITION)


def test_change_pitch_part_not_found(make_score):
    sid = make_score("simple_4_4")
    result = change_pitch(sid, measure=1, beat=1, pitch="D", part="Tuba")
    err = assert_error(result, ErrorCode.PART_NOT_FOUND)
    assert "Violin" in err["message"]


def test_change_pitch_validation_failure_leaves_file_and_undo_stack_unchanged(
    make_score, snapshot_count
):
    sid = make_score("simple_4_4")
    before = storage.read_xml(sid)
    assert snapshot_count(sid) == 0

    change_pitch(sid, measure=99, beat=1, pitch="D")
    assert snapshot_count(sid) == 0
    assert storage.read_xml(sid) == before


def test_change_pitch_success_creates_snapshot_and_undo_restores(make_score, snapshot_count):
    sid = make_score("simple_4_4")
    before = storage.read_xml(sid)

    change_pitch(sid, measure=1, beat=1, pitch="D")
    assert snapshot_count(sid) == 1
    after = storage.read_xml(sid)
    assert after != before

    storage.undo(sid)
    assert storage.read_xml(sid) == before
