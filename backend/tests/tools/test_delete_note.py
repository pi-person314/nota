"""Tests for nota.mcp_server.rhythm_tools.delete_note."""

from __future__ import annotations

import os
import uuid

import music21 as m21

from nota import db as db_module
from nota import models, storage
from nota.mcp_server import rhythm_tools
from nota.mcp_server.errors import ErrorCode
from nota.services.musicxml_repair import repair_spanner_order

from .assertions import assert_error, assert_round_trips, assert_success


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
    """See test_add_note.py's helper of the same name/purpose."""
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


def _build_score_with_tie() -> m21.stream.Score:
    m1 = m21.stream.Measure(number=1)
    m1.timeSignature = m21.meter.TimeSignature("4/4")
    n1 = m21.note.Note("C4", quarterLength=1)
    n1.tie = m21.tie.Tie("start")
    n2 = m21.note.Note("C4", quarterLength=1)
    n2.tie = m21.tie.Tie("stop")
    m1.append([n1, n2, m21.note.Note("D4", quarterLength=1), m21.note.Note("E4", quarterLength=1)])
    part = m21.stream.Part()
    part.id = "P1"
    part.partName = "Test"
    part.append(m1)
    score = m21.stream.Score()
    score.append(part)
    return score


def _build_all_rests_score() -> m21.stream.Score:
    measures = []
    for m_num in range(1, 3):
        measure = m21.stream.Measure(number=m_num)
        if m_num == 1:
            measure.timeSignature = m21.meter.TimeSignature("4/4")
        measure.append(m21.note.Rest(quarterLength=4))
        measures.append(measure)
    part = m21.stream.Part()
    part.id = "P1"
    part.partName = "Test"
    for measure in measures:
        part.append(measure)
    score = m21.stream.Score()
    score.append(part)
    return score


# ------------------------------------------------------------------- single


def test_delete_note_single_note_becomes_rest(make_score):
    sid = make_score("simple_4_4")
    result = assert_success(rhythm_tools.delete_note(sid, measure=1, beat=2))
    assert result["changed_element_ids"] == []
    assert "measure 1" in result["summary"]
    assert "beat 2" in result["summary"]
    assert_round_trips(sid)

    measure = _reparse_measure(sid, 1)
    rest = next(n for n in measure.notesAndRests if abs(n.offset - 1.0) < 1e-6)
    assert isinstance(rest, m21.note.Rest)
    assert rest.duration.quarterLength == 1.0
    pitches = [n.pitch.nameWithOctave for n in measure.notesAndRests if isinstance(n, m21.note.Note)]
    assert "D4" not in pitches  # the D4 that was at beat 2
    _assert_measure_sums(measure)


def test_delete_note_chord_becomes_rest(make_score):
    sid = make_score("chords")
    result = assert_success(rhythm_tools.delete_note(sid, measure=1, beat=1))
    assert result["changed_element_ids"] == []

    measure = _reparse_measure(sid, 1)
    rest = next(n for n in measure.notesAndRests if abs(n.offset) < 1e-6)
    assert isinstance(rest, m21.note.Rest)
    assert rest.duration.quarterLength == 1.0
    assert not any(isinstance(n, m21.chord.Chord) and abs(n.offset) < 1e-6 for n in measure.notesAndRests)
    _assert_measure_sums(measure)


def test_delete_note_tied_note_leaves_no_dangling_tie(storage_env):
    sid = _make_custom_score(storage_env, _build_score_with_tie())
    result = assert_success(rhythm_tools.delete_note(sid, measure=1, beat=1))
    assert result["changed_element_ids"] == []

    measure = _reparse_measure(sid, 1)
    rest = next(n for n in measure.notesAndRests if abs(n.offset) < 1e-6)
    assert isinstance(rest, m21.note.Rest)

    remaining_c4 = next(n for n in measure.notesAndRests if isinstance(n, m21.note.Note) and n.pitch.nameWithOctave == "C4" and abs(n.offset - 1.0) < 1e-6)
    assert remaining_c4.tie is None

    xml = storage.read_xml(sid)
    assert "<tie " not in xml and "<tied " not in xml
    _assert_measure_sums(measure)


def test_delete_note_no_note_at_position(make_score):
    sid = make_score("simple_4_4")
    result = rhythm_tools.delete_note(sid, measure=1, beat=1.5)
    assert_error(result, ErrorCode.NO_NOTE_AT_POSITION)


# ------------------------------------------------------------------ whole measure


def test_delete_note_whole_measure_clear(make_score):
    sid = make_score("simple_4_4")
    result = assert_success(rhythm_tools.delete_note(sid, measure=1))
    assert result["changed_element_ids"] == []
    assert "measure 1" in result["summary"]
    assert "rests" in result["summary"]

    measure = _reparse_measure(sid, 1)
    elements = list(measure.notesAndRests)
    assert len(elements) == 1
    assert isinstance(elements[0], m21.note.Rest)
    assert elements[0].duration.quarterLength == 4.0
    _assert_measure_sums(measure)


def test_delete_note_whole_measure_no_op_when_already_rests(storage_env):
    sid = _make_custom_score(storage_env, _build_all_rests_score())
    result = assert_success(rhythm_tools.delete_note(sid, measure=1))
    assert result["changed_element_ids"] == []
    assert "already" in result["summary"]
    assert "measure 1" in result["summary"].lower() or "Measure 1" in result["summary"]


def test_delete_note_measure_out_of_range(make_score):
    sid = make_score("simple_4_4")
    result = rhythm_tools.delete_note(sid, measure=99)
    err = assert_error(result, ErrorCode.MEASURE_OUT_OF_RANGE)
    assert "4 measures" in err["message"]


# ------------------------------------------------------------------------ range


def test_delete_note_range_across_measures(make_score):
    sid = make_score("simple_4_4")
    result = assert_success(rhythm_tools.delete_note(sid, measure=2, end_measure=3))
    assert result["changed_element_ids"] == []

    measure2 = _reparse_measure(sid, 2)
    measure3 = _reparse_measure(sid, 3)
    for measure in (measure2, measure3):
        elements = list(measure.notesAndRests)
        assert len(elements) == 1
        assert isinstance(elements[0], m21.note.Rest)
        assert elements[0].duration.quarterLength == 4.0
        _assert_measure_sums(measure)

    # Measures outside the range are untouched.
    measure1 = _reparse_measure(sid, 1)
    assert any(isinstance(n, m21.note.Note) for n in measure1.notesAndRests)


def test_delete_note_range_with_start_and_end_beat(make_score):
    sid = make_score("simple_4_4")
    # Clear from measure 1 beat 3 through measure 2 beat 2.
    result = assert_success(
        rhythm_tools.delete_note(sid, measure=1, beat=3, end_measure=2, end_beat=2)
    )
    assert result["changed_element_ids"] == []

    measure1 = _reparse_measure(sid, 1)
    # Beats 1-2 (C4, D4) survive untouched; beats 3-4 become one rest.
    early = [n for n in measure1.notesAndRests if n.offset < 2.0 - 1e-6]
    assert [n.pitch.nameWithOctave for n in early if isinstance(n, m21.note.Note)] == ["C4", "D4"]
    tail_rest = next(n for n in measure1.notesAndRests if abs(n.offset - 2.0) < 1e-6)
    assert isinstance(tail_rest, m21.note.Rest)
    assert tail_rest.duration.quarterLength == 2.0
    _assert_measure_sums(measure1)

    measure2 = _reparse_measure(sid, 2)
    # Beats 1-2 (G4, A4) become one rest; beats 3-4 (B4, C5) survive.
    head_rest = next(n for n in measure2.notesAndRests if abs(n.offset) < 1e-6)
    assert isinstance(head_rest, m21.note.Rest)
    assert head_rest.duration.quarterLength == 2.0
    tail = [n for n in measure2.notesAndRests if n.offset >= 2.0 - 1e-6]
    assert [n.pitch.nameWithOctave for n in tail if isinstance(n, m21.note.Note)] == ["B4", "C5"]
    _assert_measure_sums(measure2)


def test_delete_note_range_reversed_measures_swaps(make_score):
    sid = make_score("simple_4_4")
    # end_measure < measure: should behave the same as measure=2, end_measure=3.
    forward = rhythm_tools.delete_note(sid, measure=3, end_measure=2)
    assert_success(forward)

    measure2 = _reparse_measure(sid, 2)
    measure3 = _reparse_measure(sid, 3)
    for measure in (measure2, measure3):
        elements = list(measure.notesAndRests)
        assert len(elements) == 1
        assert isinstance(elements[0], m21.note.Rest)


def test_delete_note_changed_element_ids_always_empty(make_score):
    sid = make_score("simple_4_4")
    r1 = assert_success(rhythm_tools.delete_note(sid, measure=1, beat=1))
    assert r1["changed_element_ids"] == []
    r2 = assert_success(rhythm_tools.delete_note(sid, measure=2))
    assert r2["changed_element_ids"] == []
    r3 = assert_success(rhythm_tools.delete_note(sid, measure=3, end_measure=4))
    assert r3["changed_element_ids"] == []


# --------------------------------------------------------------------- errors


def test_delete_note_score_not_found():
    result = rhythm_tools.delete_note("does-not-exist", measure=1)
    assert_error(result, ErrorCode.SCORE_NOT_FOUND)


def test_delete_note_part_not_found(make_score):
    sid = make_score("simple_4_4")
    result = rhythm_tools.delete_note(sid, measure=1, beat=1, part="Tuba")
    err = assert_error(result, ErrorCode.PART_NOT_FOUND)
    assert "Violin" in err["message"]


# ---------------------------------------------------------------------- undo


def test_delete_note_undo_restores(make_score, snapshot_count):
    sid = make_score("simple_4_4")
    before = storage.read_xml(sid)

    rhythm_tools.delete_note(sid, measure=1, beat=1)
    assert snapshot_count(sid) == 1
    assert storage.read_xml(sid) != before

    storage.undo(sid)
    assert storage.read_xml(sid) == before


def test_delete_note_validation_failure_leaves_no_snapshot(make_score, snapshot_count):
    sid = make_score("simple_4_4")
    rhythm_tools.delete_note(sid, measure=99)
    rhythm_tools.delete_note(sid, measure=1, beat=99)
    assert snapshot_count(sid) == 0
