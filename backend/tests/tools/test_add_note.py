"""Tests for nota.mcp_server.rhythm_tools.add_note."""

from __future__ import annotations

import os
import uuid

import music21 as m21

from nota import db as db_module
from nota import models, storage
from nota.mcp_server import notes, rhythm_tools
from nota.mcp_server.errors import ErrorCode
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


def _reparse_measure(score_id: str, measure_number: int, part_index: int = 0) -> m21.stream.Measure:
    reparsed = _reparse(score_id)
    parts = list(reparsed.parts) if list(reparsed.parts) else [reparsed]
    part = parts[part_index]
    return next(m for m in part.getElementsByClass(m21.stream.Measure) if m.number == measure_number)


def _assert_measure_sums(measure: m21.stream.Measure) -> None:
    writable = measure.barDuration.quarterLength - (measure.paddingLeft or 0)
    voices = list(measure.getElementsByClass(m21.stream.Voice))
    streams = voices if voices else [measure]
    for stream_obj in streams:
        total = sum(e.duration.quarterLength for e in stream_obj.notesAndRests)
        assert abs(float(total) - writable) < 1e-6, (measure.number, total, writable)


def _make_custom_score(storage_env, score_obj: m21.stream.Score) -> str:
    """Insert a one-off, hand-built score into storage, the same way
    conftest.py's `make_score` factory does for the shared fixture matrix
    -- used here for shapes (a measure containing a rest, a tuplet, or no
    notes at all) that aren't in that shared matrix.
    """
    user_id = uuid.uuid4().hex
    score_id = uuid.uuid4().hex
    os.makedirs(str(storage_env), exist_ok=True)
    file_path = os.path.join(str(storage_env), f"{score_id}.musicxml")

    score_obj.write("musicxml", fp=file_path)
    with open(file_path, "r", encoding="utf-8") as f:
        xml = repair_spanner_order(f.read())
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(xml)

    part = score_obj.parts[0] if list(score_obj.parts) else score_obj
    measure_numbers = [m.number for m in part.getElementsByClass(m21.stream.Measure)]
    has_pickup = 0 in measure_numbers
    real_measures = [n for n in measure_numbers if n >= 1]
    measure_count = max(real_measures) if real_measures else 0

    with db_module.session_scope() as session:
        session.add(models.User(id=user_id, name="Test User", email=f"{user_id}@example.com"))
        session.add(
            models.Score(
                id=score_id,
                user_id=user_id,
                name="custom",
                file_path=file_path,
                measure_count=measure_count,
                has_pickup=has_pickup,
                parts_json="[]",
                time_signatures_json="[]",
            )
        )
    return score_id


def _build_score_with_rest() -> m21.stream.Score:
    measure = m21.stream.Measure(number=1)
    measure.timeSignature = m21.meter.TimeSignature("4/4")
    measure.append(
        [
            m21.note.Note("C4", quarterLength=1),
            m21.note.Note("D4", quarterLength=1),
            m21.note.Rest(quarterLength=1),
            m21.note.Note("F4", quarterLength=1),
        ]
    )
    part = m21.stream.Part()
    part.id = "P1"
    part.partName = "Test"
    part.append(measure)
    score = m21.stream.Score()
    score.append(part)
    return score


def _build_score_with_tuplet() -> m21.stream.Score:
    measure = m21.stream.Measure(number=1)
    measure.timeSignature = m21.meter.TimeSignature("4/4")
    for pitch in ["C4", "D4", "E4"]:
        tuplet_note = m21.note.Note(pitch, quarterLength=1 / 3)
        tuplet_note.duration.appendTuplet(m21.duration.Tuplet(3, 2))
        measure.append(tuplet_note)
    for pitch in ["F4", "G4", "A4"]:
        measure.append(m21.note.Note(pitch, quarterLength=1))
    part = m21.stream.Part()
    part.id = "P1"
    part.partName = "Test"
    part.append(measure)
    score = m21.stream.Score()
    score.append(part)
    return score


def _build_score_with_no_notes() -> m21.stream.Score:
    measure = m21.stream.Measure(number=1)
    measure.timeSignature = m21.meter.TimeSignature("4/4")
    measure.append(m21.note.Rest(quarterLength=4))
    part = m21.stream.Part()
    part.id = "P1"
    part.partName = "Test"
    part.append(measure)
    score = m21.stream.Score()
    score.append(part)
    return score


# --------------------------------------------------------------------- basics


def test_add_note_onto_rest(storage_env):
    sid = _make_custom_score(storage_env, _build_score_with_rest())
    result = assert_success(rhythm_tools.add_note(sid, measure=1, beat=3, pitch="E4", duration="quarter"))

    assert len(result["changed_element_ids"]) == 1
    assert "replacing" not in result["summary"]
    assert_round_trips(sid)
    assert_ids_present(sid, result["changed_element_ids"])
    assert_renders_with_verovio(sid)

    measure = _reparse_measure(sid, 1)
    note = next(n for n in measure.notesAndRests if abs(n.offset - 2.0) < 1e-6)
    assert isinstance(note, m21.note.Note)
    assert note.pitch.nameWithOctave == "E4"
    _assert_measure_sums(measure)


def test_add_note_overwrite_exact(make_score):
    sid = make_score("simple_4_4")
    result = assert_success(rhythm_tools.add_note(sid, measure=1, beat=1, pitch="G3", duration="quarter"))

    assert "replacing the existing notes there" in result["summary"]
    assert_ids_present(sid, result["changed_element_ids"])

    measure = _reparse_measure(sid, 1)
    note = next(n for n in measure.notesAndRests if abs(n.offset) < 1e-6)
    assert isinstance(note, m21.note.Note)
    assert note.pitch.nameWithOctave == "G3"
    assert note.duration.quarterLength == 1.0
    _assert_measure_sums(measure)


def test_add_note_overwrite_spanning_several_notes(make_score):
    sid = make_score("simple_4_4")
    # Measure 1 is 4 quarter notes; a whole note at beat 1 overwrites all four.
    result = assert_success(rhythm_tools.add_note(sid, measure=1, beat=1, pitch="C5", duration="whole"))
    assert "replacing the existing notes there" in result["summary"]

    measure = _reparse_measure(sid, 1)
    assert len(list(measure.notesAndRests)) == 1
    note = list(measure.notesAndRests)[0]
    assert note.pitch.nameWithOctave == "C5"
    assert note.duration.quarterLength == 4.0
    _assert_measure_sums(measure)


def test_add_note_partial_overwrite_leaves_trailing_backfill_rest(make_score):
    sid = make_score("chords")
    # Measure 1 beat 1 holds a quarter-length chord (C4/E4/G4); writing an
    # eighth note there only covers the front half, leaving the back half
    # as a backfill rest.
    result = assert_success(rhythm_tools.add_note(sid, measure=1, beat=1, pitch="C5", duration="eighth"))
    assert_round_trips(sid)

    measure = _reparse_measure(sid, 1)
    new_note = next(n for n in measure.notesAndRests if abs(n.offset) < 1e-6)
    assert isinstance(new_note, m21.note.Note)
    assert new_note.pitch.nameWithOctave == "C5"
    assert new_note.duration.quarterLength == 0.5

    backfill = next(n for n in measure.notesAndRests if abs(n.offset - 0.5) < 1e-6)
    assert isinstance(backfill, m21.note.Rest)
    assert backfill.duration.quarterLength == 0.5

    # The rest of the measure (D4 quarter note, then the two-beat chord) is untouched.
    later = [n for n in measure.notesAndRests if n.offset >= 1.0 - 1e-6]
    assert len(later) == 2
    _assert_measure_sums(measure)


# --------------------------------------------------------------------- octave


def test_add_note_octave_picked_nearest_preceding_note(make_score):
    sid = make_score("simple_4_4")
    # Measure 1 beat 4 is F4; overwriting measure 2 beat 1 (currently G4)
    # with a bare "C" should place it at the octave nearest to that F4.
    result = assert_success(rhythm_tools.add_note(sid, measure=2, beat=1, pitch="C", duration="quarter"))

    expected = notes.realize_pitch(notes.parse_pitch_spec("C"), m21.pitch.Pitch("F4"))
    measure = _reparse_measure(sid, 2)
    note = next(n for n in measure.notesAndRests if abs(n.offset) < 1e-6)
    assert note.pitch.nameWithOctave == expected.nameWithOctave
    assert_ids_present(sid, result["changed_element_ids"])


def test_add_note_explicit_octave_honored(make_score):
    sid = make_score("simple_4_4")
    assert_success(rhythm_tools.add_note(sid, measure=1, beat=2, pitch="D3", duration="quarter"))

    measure = _reparse_measure(sid, 1)
    note = next(n for n in measure.notesAndRests if abs(n.offset - 1.0) < 1e-6)
    assert note.pitch.nameWithOctave == "D3"


def test_add_note_empty_part_default_octave_four(storage_env):
    sid = _make_custom_score(storage_env, _build_score_with_no_notes())
    assert_success(rhythm_tools.add_note(sid, measure=1, beat=1, pitch="C", duration="whole"))

    measure = _reparse_measure(sid, 1)
    note = next(n for n in measure.notesAndRests if abs(n.offset) < 1e-6)
    assert note.pitch.nameWithOctave == "C4"


# --------------------------------------------------------------------- errors


def test_add_note_duration_crosses_barline(make_score, snapshot_count):
    sid = make_score("simple_4_4")
    before = storage.read_xml(sid)

    result = rhythm_tools.add_note(sid, measure=1, beat=4, pitch="C4", duration="half")
    err = assert_error(result, ErrorCode.DURATION_CROSSES_BARLINE)
    assert "Measure 1" in err["message"]

    assert snapshot_count(sid) == 0
    assert storage.read_xml(sid) == before


def test_add_note_unsupported_tuplet(storage_env, snapshot_count):
    sid = _make_custom_score(storage_env, _build_score_with_tuplet())
    before = storage.read_xml(sid)

    result = rhythm_tools.add_note(sid, measure=1, beat=1, pitch="B4", duration="quarter")
    assert_error(result, ErrorCode.UNSUPPORTED_TUPLET)

    assert snapshot_count(sid) == 0
    assert storage.read_xml(sid) == before


def test_add_note_invalid_pitch(make_score):
    sid = make_score("simple_4_4")
    result = rhythm_tools.add_note(sid, measure=1, beat=1, pitch="Z9", duration="quarter")
    err = assert_error(result, ErrorCode.INVALID_PITCH)
    assert "Z9" in err["message"]


def test_add_note_invalid_duration(make_score):
    sid = make_score("simple_4_4")
    result = rhythm_tools.add_note(sid, measure=1, beat=1, pitch="C4", duration="banana")
    err = assert_error(result, ErrorCode.INVALID_DURATION)
    assert "banana" in err["message"]


def test_add_note_score_not_found():
    result = rhythm_tools.add_note("does-not-exist", measure=1, beat=1, pitch="C4", duration="quarter")
    assert_error(result, ErrorCode.SCORE_NOT_FOUND)


def test_add_note_measure_out_of_range(make_score):
    sid = make_score("simple_4_4")
    result = rhythm_tools.add_note(sid, measure=99, beat=1, pitch="C4", duration="quarter")
    err = assert_error(result, ErrorCode.MEASURE_OUT_OF_RANGE)
    assert "4 measures" in err["message"]


def test_add_note_beat_out_of_range(make_score):
    sid = make_score("simple_4_4")
    result = rhythm_tools.add_note(sid, measure=1, beat=9, pitch="C4", duration="quarter")
    assert_error(result, ErrorCode.BEAT_OUT_OF_RANGE)


def test_add_note_part_not_found(make_score):
    sid = make_score("simple_4_4")
    result = rhythm_tools.add_note(sid, measure=1, beat=1, pitch="C4", duration="quarter", part="Tuba")
    err = assert_error(result, ErrorCode.PART_NOT_FOUND)
    assert "Violin" in err["message"]


# ---------------------------------------------------------------- undo / misc


def test_add_note_undo_restores(make_score, snapshot_count):
    sid = make_score("simple_4_4")
    before = storage.read_xml(sid)

    rhythm_tools.add_note(sid, measure=1, beat=1, pitch="G3", duration="quarter")
    assert snapshot_count(sid) == 1
    assert storage.read_xml(sid) != before

    storage.undo(sid)
    assert storage.read_xml(sid) == before


def test_add_note_summary_wording(make_score):
    sid = make_score("simple_4_4")
    result = assert_success(
        rhythm_tools.add_note(sid, measure=2, beat=1, pitch="C#5", duration="dotted_quarter")
    )
    assert "dotted quarter note" in result["summary"]
    assert "C#5" in result["summary"]
    assert "measure 2" in result["summary"]
    assert "beat 1" in result["summary"]


# ---------------------------------------------------------------------- pickup


def test_add_note_pickup_measure(make_score):
    sid = make_score("pickup")
    result = assert_success(rhythm_tools.add_note(sid, measure=0, beat=4, pitch="A4", duration="quarter"))
    assert "replacing the existing notes there" in result["summary"]
    assert_round_trips(sid)

    measure = _reparse_measure(sid, 0)
    note = next(n for n in measure.notesAndRests if isinstance(n, m21.note.Note))
    assert note.pitch.nameWithOctave == "A4"
    _assert_measure_sums(measure)
