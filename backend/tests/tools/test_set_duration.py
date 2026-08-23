"""Tests for nota.mcp_server.rhythm_tools.set_duration."""

from __future__ import annotations

import os
import uuid

import music21 as m21

from nota import db as db_module
from nota import models, storage
from nota.mcp_server import rhythm_tools, tools
from nota.mcp_server.errors import ErrorCode
from nota.services.musicxml_repair import repair_spanner_order

from .assertions import assert_error, assert_ids_present, assert_round_trips, assert_success


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
    measure = m21.stream.Measure(number=1)
    measure.timeSignature = m21.meter.TimeSignature("4/4")
    n1 = m21.note.Note("C4", quarterLength=1)
    n1.tie = m21.tie.Tie("start")
    n2 = m21.note.Note("C4", quarterLength=1)
    n2.tie = m21.tie.Tie("stop")
    measure.append([n1, n2, m21.note.Note("D4", quarterLength=1), m21.note.Note("E4", quarterLength=1)])
    part = m21.stream.Part()
    part.id = "P1"
    part.partName = "Test"
    part.append(measure)
    score = m21.stream.Score()
    score.append(part)
    return score


# --------------------------------------------------------------------- basics


def test_set_duration_shorten_leaves_trailing_rest(make_score):
    sid = make_score("simple_4_4")
    result = assert_success(rhythm_tools.set_duration(sid, measure=1, beat=1, duration="eighth"))
    assert_ids_present(sid, result["changed_element_ids"])
    assert_round_trips(sid)

    measure = _reparse_measure(sid, 1)
    note = next(n for n in measure.notesAndRests if abs(n.offset) < 1e-6)
    assert note.pitch.nameWithOctave == "C4"
    assert note.duration.quarterLength == 0.5

    rest = next(n for n in measure.notesAndRests if abs(n.offset - 0.5) < 1e-6)
    assert isinstance(rest, m21.note.Rest)
    assert rest.duration.quarterLength == 0.5
    _assert_measure_sums(measure)


def test_set_duration_lengthen_consumes_following_note(make_score):
    sid = make_score("simple_4_4")
    result = assert_success(rhythm_tools.set_duration(sid, measure=1, beat=1, duration="half"))
    assert_ids_present(sid, result["changed_element_ids"])

    measure = _reparse_measure(sid, 1)
    note = next(n for n in measure.notesAndRests if abs(n.offset) < 1e-6)
    assert note.pitch.nameWithOctave == "C4"
    assert note.duration.quarterLength == 2.0

    remaining_pitches = [n.pitch.nameWithOctave for n in measure.notesAndRests if isinstance(n, m21.note.Note)]
    assert "D4" not in remaining_pitches  # consumed by the extension
    assert remaining_pitches == ["C4", "E4", "F4"]
    _assert_measure_sums(measure)


def test_set_duration_lengthen_past_barline(make_score, snapshot_count):
    sid = make_score("simple_4_4")
    before = storage.read_xml(sid)

    result = rhythm_tools.set_duration(sid, measure=1, beat=4, duration="half")
    err = assert_error(result, ErrorCode.DURATION_CROSSES_BARLINE)
    assert "Measure 1" in err["message"]
    assert snapshot_count(sid) == 0
    assert storage.read_xml(sid) == before


def test_set_duration_no_note_at_position(make_score):
    sid = make_score("simple_4_4")
    result = rhythm_tools.set_duration(sid, measure=1, beat=1.5, duration="quarter")
    assert_error(result, ErrorCode.NO_NOTE_AT_POSITION)


def test_set_duration_no_op_when_unchanged(make_score, snapshot_count):
    sid = make_score("simple_4_4")
    result = assert_success(rhythm_tools.set_duration(sid, measure=1, beat=1, duration="quarter"))
    assert result["changed_element_ids"] == []
    assert "already" in result["summary"]
    assert snapshot_count(sid) == 0


# ---------------------------------------------------------------- content preservation


def test_set_duration_preserves_articulation(make_score):
    sid = make_score("simple_4_4")
    tools.add_articulation(sid, measure=1, beat=1, articulation="staccato")

    assert_success(rhythm_tools.set_duration(sid, measure=1, beat=1, duration="half"))

    measure = _reparse_measure(sid, 1)
    note = next(n for n in measure.notesAndRests if abs(n.offset) < 1e-6)
    assert note.duration.quarterLength == 2.0
    assert any(isinstance(a, m21.articulations.Staccato) for a in note.articulations)


def test_set_duration_chord(make_score):
    sid = make_score("chords")
    result = assert_success(rhythm_tools.set_duration(sid, measure=1, beat=1, duration="half"))
    assert_ids_present(sid, result["changed_element_ids"])

    measure = _reparse_measure(sid, 1)
    chord = next(n for n in measure.notesAndRests if abs(n.offset) < 1e-6)
    assert isinstance(chord, m21.chord.Chord)
    assert chord.duration.quarterLength == 2.0
    assert {p.nameWithOctave for p in chord.pitches} == {"C4", "E4", "G4"}
    _assert_measure_sums(measure)


def test_set_duration_forward_tie_cleared_no_dangling_tie(storage_env):
    sid = _make_custom_score(storage_env, _build_score_with_tie())
    result = assert_success(rhythm_tools.set_duration(sid, measure=1, beat=1, duration="half"))

    measure = _reparse_measure(sid, 1)
    note = next(n for n in measure.notesAndRests if abs(n.offset) < 1e-6)
    assert note.duration.quarterLength == 2.0
    assert note.tie is None

    xml = storage.read_xml(sid)
    assert "<tie " not in xml and "<tied " not in xml
    assert_ids_present(sid, result["changed_element_ids"])
    _assert_measure_sums(measure)


def test_set_duration_shorten_clears_forward_tie(storage_env):
    """Shortening the tied-from note (rather than extending into its
    partner) exercises the manual tie-repair path, not carve_span's.
    """
    sid = _make_custom_score(storage_env, _build_score_with_tie())
    assert_success(rhythm_tools.set_duration(sid, measure=1, beat=1, duration="eighth"))

    measure = _reparse_measure(sid, 1)
    shortened = next(n for n in measure.notesAndRests if abs(n.offset) < 1e-6)
    assert shortened.duration.quarterLength == 0.5
    assert shortened.tie is None

    partner = next(n for n in measure.notesAndRests if abs(n.offset - 1.0) < 1e-6)
    assert partner.tie is None

    xml = storage.read_xml(sid)
    assert "<tie " not in xml and "<tied " not in xml
    _assert_measure_sums(measure)


# --------------------------------------------------------------------- errors


def test_set_duration_score_not_found():
    result = rhythm_tools.set_duration("does-not-exist", measure=1, beat=1, duration="quarter")
    assert_error(result, ErrorCode.SCORE_NOT_FOUND)


def test_set_duration_measure_out_of_range(make_score):
    sid = make_score("simple_4_4")
    result = rhythm_tools.set_duration(sid, measure=99, beat=1, duration="quarter")
    err = assert_error(result, ErrorCode.MEASURE_OUT_OF_RANGE)
    assert "4 measures" in err["message"]


def test_set_duration_invalid_duration(make_score):
    sid = make_score("simple_4_4")
    result = rhythm_tools.set_duration(sid, measure=1, beat=1, duration="banana")
    err = assert_error(result, ErrorCode.INVALID_DURATION)
    assert "banana" in err["message"]


def test_set_duration_part_not_found(make_score):
    sid = make_score("simple_4_4")
    result = rhythm_tools.set_duration(sid, measure=1, beat=1, duration="quarter", part="Tuba")
    err = assert_error(result, ErrorCode.PART_NOT_FOUND)
    assert "Violin" in err["message"]


# ---------------------------------------------------------------------- undo


def test_set_duration_undo_restores(make_score, snapshot_count):
    sid = make_score("simple_4_4")
    before = storage.read_xml(sid)

    rhythm_tools.set_duration(sid, measure=1, beat=1, duration="half")
    assert snapshot_count(sid) == 1
    assert storage.read_xml(sid) != before

    storage.undo(sid)
    assert storage.read_xml(sid) == before


def test_set_duration_summary_wording(make_score):
    sid = make_score("simple_4_4")
    result = assert_success(rhythm_tools.set_duration(sid, measure=1, beat=1, duration="dotted_half"))
    assert "dotted half note" in result["summary"]
    assert "measure 1" in result["summary"]
    assert "beat 1" in result["summary"]
