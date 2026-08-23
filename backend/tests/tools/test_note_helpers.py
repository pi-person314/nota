"""Tests for nota.mcp_server.notes: pitch parsing, octave realization,
duration/interval vocabularies, voice targeting, and span carving.

These are pure-helper tests: most of them build small music21 objects
directly rather than going through `make_score`/`tools.py`, since
`notes.py` has no `score_id` argument and never touches storage. The one
score-storage-backed test is the end-to-end sanity check at the bottom,
which exercises a real parse -> carve -> insert -> export -> reparse
round trip.
"""

from __future__ import annotations

import re

import music21 as m21
import pytest

from nota.mcp_server import notes
from nota.mcp_server.errors import ErrorCode, ToolError

# ---------------------------------------------------------------------------
# parse_pitch_spec


@pytest.mark.parametrize(
    "text,step,alter,octave",
    [
        ("C", "C", 0, None),
        ("c", "C", 0, None),
        ("G", "G", 0, None),
        ("C#4", "C", 1, 4),
        ("c#4", "C", 1, 4),
        ("Db5", "D", -1, 5),
        ("c sharp 4", "C", 1, 4),
        ("F natural 3", "F", 0, 3),
        ("B flat", "B", -1, None),
        ("c##", "C", 2, None),
        ("cx", "C", 2, None),
        ("c double sharp", "C", 2, None),
        ("c-double-flat", "C", -2, None),
        ("g♯3", "G", 1, 3),  # g♯3
        ("a♭", "A", -1, None),  # a♭
        ("e♮4", "E", 0, 4),  # e♮4
    ],
)
def test_parse_pitch_spec_valid_forms(text, step, alter, octave):
    spec = notes.parse_pitch_spec(text)
    assert spec.step == step
    assert spec.alter == alter
    assert spec.octave == octave


def test_parse_pitch_spec_bare_b_is_note_b_natural():
    spec = notes.parse_pitch_spec("b")
    assert spec.step == "B"
    assert spec.alter == 0


def test_parse_pitch_spec_bb_is_b_flat_not_double_b():
    spec = notes.parse_pitch_spec("bb")
    assert spec.step == "B"
    assert spec.alter == -1


def test_parse_pitch_spec_bbb_is_b_double_flat():
    spec = notes.parse_pitch_spec("bbb")
    assert spec.step == "B"
    assert spec.alter == -2


def test_parse_pitch_spec_bb4_with_octave():
    spec = notes.parse_pitch_spec("bb4")
    assert spec.step == "B"
    assert spec.alter == -1
    assert spec.octave == 4


@pytest.mark.parametrize("bad", ["", "   ", "H4", "C99", "C#sharp", "Cq", "9C"])
def test_parse_pitch_spec_invalid_raises(bad):
    with pytest.raises(ToolError) as exc:
        notes.parse_pitch_spec(bad)
    assert exc.value.code == ErrorCode.INVALID_PITCH
    assert exc.value.message


def test_parse_pitch_spec_error_message_is_actionable():
    with pytest.raises(ToolError) as exc:
        notes.parse_pitch_spec("H4")
    assert "H4" in exc.value.message
    assert "e.g." in exc.value.message


# ---------------------------------------------------------------------------
# realize_pitch


def test_realize_pitch_explicit_octave_used_directly():
    spec = notes.PitchSpec(step="C", alter=0, octave=5)
    result = notes.realize_pitch(spec, m21.pitch.Pitch("C4"))
    assert result.nameWithOctave == "C5"


def test_realize_pitch_no_reference_defaults_to_octave_4():
    spec = notes.PitchSpec(step="B", alter=0, octave=None)
    result = notes.realize_pitch(spec, None)
    assert result.octave == 4
    assert result.step == "B"


def test_realize_pitch_nearest_octave_down():
    # B natural nearest to C4 (ps 60): B3 (ps 59, distance 1) beats
    # B4 (ps 71, distance 11).
    spec = notes.PitchSpec(step="B", alter=0, octave=None)
    result = notes.realize_pitch(spec, m21.pitch.Pitch("C4"))
    assert result.nameWithOctave == "B3"


def test_realize_pitch_nearest_octave_up():
    # C-sharp nearest to B3 (ps 59): C#4 (ps 61, distance 2) beats
    # C#3 (ps 49, distance 10).
    spec = notes.PitchSpec(step="C", alter=1, octave=None)
    result = notes.realize_pitch(spec, m21.pitch.Pitch("B3"))
    assert result.nameWithOctave == "C#4"


def test_realize_pitch_exact_tie_prefers_higher_octave():
    # F-sharp nearest to C4 (ps 60): F#3 (ps 54) and F#4 (ps 66) are
    # both exactly 6 semitones away.
    spec = notes.PitchSpec(step="F", alter=1, octave=None)
    result = notes.realize_pitch(spec, m21.pitch.Pitch("C4"))
    assert result.nameWithOctave == "F#4"


def test_realize_pitch_preserves_flat_spelling():
    spec = notes.PitchSpec(step="D", alter=-1, octave=None)
    result = notes.realize_pitch(spec, m21.pitch.Pitch("C4"))
    assert result.name == "D-"
    assert result.name != "C#"


# ---------------------------------------------------------------------------
# parse_duration / parse_interval


@pytest.mark.parametrize(
    "name,expected",
    [
        ("whole", 4.0),
        ("dotted_half", 3.0),
        ("half", 2.0),
        ("dotted_quarter", 1.5),
        ("quarter", 1.0),
        ("dotted_eighth", 0.75),
        ("eighth", 0.5),
        ("dotted_sixteenth", 0.375),
        ("sixteenth", 0.25),
        ("thirty_second", 0.125),
        ("dotted_whole", 6.0),
    ],
)
def test_parse_duration_valid(name, expected):
    assert notes.parse_duration(name) == expected


def test_parse_duration_invalid_raises_and_lists_values():
    with pytest.raises(ToolError) as exc:
        notes.parse_duration("nonexistent")
    assert exc.value.code == ErrorCode.INVALID_DURATION
    assert "quarter" in exc.value.message


@pytest.mark.parametrize(
    "name,expected_str",
    [
        ("octave", "P8"),
        ("half_step", "m2"),
        ("semitone", "m2"),
        ("whole_step", "M2"),
        ("whole_tone", "M2"),
        ("minor_third", "m3"),
        ("major_third", "M3"),
        ("perfect_fourth", "P4"),
        ("tritone", "A4"),
        ("perfect_fifth", "P5"),
        ("minor_sixth", "m6"),
        ("major_sixth", "M6"),
        ("minor_seventh", "m7"),
        ("major_seventh", "M7"),
    ],
)
def test_parse_interval_up(name, expected_str):
    interval_obj = notes.parse_interval(name, "up")
    assert interval_obj.directedName == expected_str


def test_parse_interval_down_reverses():
    up = notes.parse_interval("major_third", "up")
    down = notes.parse_interval("major_third", "down")
    assert down.semitones == -up.semitones


def test_parse_interval_unknown_name_raises():
    with pytest.raises(ToolError) as exc:
        notes.parse_interval("perfect_ninth", "up")
    assert exc.value.code == ErrorCode.INVALID_INTERVAL


def test_parse_interval_unknown_direction_raises():
    with pytest.raises(ToolError) as exc:
        notes.parse_interval("major_third", "sideways")
    assert exc.value.code == ErrorCode.INVALID_INTERVAL


# ---------------------------------------------------------------------------
# target_stream


def _voiced_measure():
    measure = m21.stream.Measure(number=1)
    measure.timeSignature = m21.meter.TimeSignature("4/4")
    voice1 = m21.stream.Voice()
    voice1.id = 1
    voice1.append([m21.note.Note(p, quarterLength=1) for p in ["C5", "D5", "E5", "F5"]])
    voice2 = m21.stream.Voice()
    voice2.id = 2
    voice2.append([m21.note.Note(p, quarterLength=2) for p in ["C4", "D4"]])
    measure.insert(0, voice1)
    measure.insert(0, voice2)
    return measure, voice1, voice2


def test_target_stream_no_voices_returns_measure():
    measure = m21.stream.Measure(number=1)
    measure.timeSignature = m21.meter.TimeSignature("4/4")
    measure.append(m21.note.Note("C4", quarterLength=4))
    assert notes.target_stream(measure, 1.0) is measure


def test_target_stream_with_voices_picks_voice_with_note_at_offset():
    measure, voice1, voice2 = _voiced_measure()
    # Both voices have something at offset 0; voice1 (checked first) wins.
    assert notes.target_stream(measure, 0.0) is voice1
    # Offset 1.0: voice1 has a note starting there.
    assert notes.target_stream(measure, 1.0) is voice1


def test_target_stream_falls_back_to_first_voice():
    measure = m21.stream.Measure(number=1)
    measure.timeSignature = m21.meter.TimeSignature("4/4")
    voice1 = m21.stream.Voice()
    voice1.id = 1
    voice1.append(m21.note.Note("C5", quarterLength=1))
    voice2 = m21.stream.Voice()
    voice2.id = 2
    voice2.append(m21.note.Note("C4", quarterLength=1))
    measure.insert(0, voice1)
    measure.insert(0, voice2)
    # Offset 3.0 has nothing in either voice; falls back to first voice.
    assert notes.target_stream(measure, 3.0) is voice1


# ---------------------------------------------------------------------------
# carve_span


def _measure(number=1, ts="4/4", padding=0.0, notes_list=None):
    measure = m21.stream.Measure(number=number)
    if ts is not None:
        measure.timeSignature = m21.meter.TimeSignature(ts)
    measure.paddingLeft = padding
    for element in notes_list or []:
        measure.append(element)
    return measure


def _positions(stream_obj):
    return [
        (float(e.offset), float(e.duration.quarterLength), type(e).__name__)
        for e in stream_obj.notesAndRests
    ]


def test_carve_span_exact_replacement_of_one_note():
    measure = _measure(notes_list=[m21.note.Note(p, quarterLength=1) for p in ["C4", "D4", "E4", "F4"]])
    result = notes.carve_span(measure, 1.0, 1.0)
    assert _positions(result) == [(0.0, 1.0, "Note"), (2.0, 1.0, "Note"), (3.0, 1.0, "Note")]


def test_carve_span_covers_several_notes():
    measure = _measure(notes_list=[m21.note.Note(p, quarterLength=1) for p in ["C4", "D4", "E4", "F4"]])
    result = notes.carve_span(measure, 1.0, 2.0)
    assert _positions(result) == [(0.0, 1.0, "Note"), (3.0, 1.0, "Note")]


def test_carve_span_partial_overlap_at_start_backfills_leading_rest():
    measure = _measure(notes_list=[m21.note.Note("C4", quarterLength=2), m21.note.Note("D4", quarterLength=2)])
    result = notes.carve_span(measure, 1.0, 1.0)
    assert _positions(result) == [(0.0, 1.0, "Rest"), (2.0, 2.0, "Note")]


def test_carve_span_partial_overlap_at_end_backfills_trailing_rest():
    measure = _measure(notes_list=[m21.note.Note("C4", quarterLength=2), m21.note.Note("D4", quarterLength=2)])
    result = notes.carve_span(measure, 0.0, 1.0)
    assert _positions(result) == [(1.0, 1.0, "Rest"), (2.0, 2.0, "Note")]


def test_carve_span_barline_overflow_raises_without_mutating():
    measure = _measure(notes_list=[m21.note.Note("C4", quarterLength=4)])
    before = _positions(measure)
    with pytest.raises(ToolError) as exc:
        notes.carve_span(measure, 2.0, 4.0)
    assert exc.value.code == ErrorCode.DURATION_CROSSES_BARLINE
    assert _positions(measure) == before


def test_carve_span_barline_overflow_message_mentions_remaining_room():
    measure = _measure(notes_list=[m21.note.Note("C4", quarterLength=4)])
    with pytest.raises(ToolError) as exc:
        notes.carve_span(measure, 3.0, 3.0)
    assert "1" in exc.value.message


def _tuplet_measure():
    measure = _measure(notes_list=[])
    for pitch in ["C4", "D4", "E4"]:
        tuplet_note = m21.note.Note(pitch, quarterLength=1 / 3)
        tuplet_note.duration.appendTuplet(m21.duration.Tuplet(3, 2))
        measure.append(tuplet_note)
    for pitch in ["F4", "G4", "A4"]:
        measure.append(m21.note.Note(pitch, quarterLength=1))
    return measure


def test_carve_span_tuplet_intersection_raises_without_mutating():
    measure = _tuplet_measure()
    before = _positions(measure)
    with pytest.raises(ToolError) as exc:
        notes.carve_span(measure, 0.0, 1.0)
    assert exc.value.code == ErrorCode.UNSUPPORTED_TUPLET
    assert _positions(measure) == before


def test_carve_span_leaves_non_tuplet_region_alone():
    measure = _tuplet_measure()
    # Offset 1.0-2.0 (the "F4" quarter note) doesn't touch the tuplet.
    result = notes.carve_span(measure, 1.0, 1.0)
    remaining_pitches = [e.pitch.nameWithOctave for e in result.notesAndRests if isinstance(e, m21.note.Note)]
    assert "F4" not in remaining_pitches
    assert "G4" in remaining_pitches


def test_carve_span_pickup_measure_writable_length():
    measure = _measure(number=0, notes_list=[m21.note.Note("G4", quarterLength=1)], padding=3.0)
    with pytest.raises(ToolError) as exc:
        notes.carve_span(measure, 0.0, 2.0)
    assert exc.value.code == ErrorCode.DURATION_CROSSES_BARLINE

    # A span that fits the pickup's actual writable length (1 quarter
    # length, not the full 4/4 bar) succeeds.
    result = notes.carve_span(measure, 0.0, 1.0)
    assert _positions(result) == []


def test_carve_span_removes_grace_note_in_span():
    measure = _measure(notes_list=[])
    grace = m21.note.Note("B4").getGrace()
    measure.append([grace, m21.note.Note("C5", quarterLength=1)])
    measure.append(m21.note.Note("D5", quarterLength=1))
    measure.append(m21.note.Note("E5", quarterLength=1))
    measure.append(m21.note.Note("F5", quarterLength=1))

    result = notes.carve_span(measure, 0.0, 1.0)
    remaining_types = [type(e).__name__ for e in result.notesAndRests]
    assert "Note" in remaining_types
    assert len([e for e in result.notesAndRests if e.duration.isGrace]) == 0
    assert _positions(result) == [(1.0, 1.0, "Note"), (2.0, 1.0, "Note"), (3.0, 1.0, "Note")]


def test_carve_span_tie_repair_stop_partner_within_same_measure():
    start_note = m21.note.Note("C4", quarterLength=1)
    start_note.tie = m21.tie.Tie("start")
    stop_note = m21.note.Note("C4", quarterLength=1)
    stop_note.tie = m21.tie.Tie("stop")
    measure = _measure(notes_list=[start_note, stop_note, m21.note.Note("D4", quarterLength=1), m21.note.Note("E4", quarterLength=1)])

    result = notes.carve_span(measure, 0.0, 1.0)
    remaining = list(result.notesAndRests)
    # stop_note survives (offset 1.0) and its now-dangling backward tie
    # must have been cleared.
    survivor = next(e for e in remaining if abs(e.offset - 1.0) < 1e-6)
    assert survivor.tie is None


def test_carve_span_tie_into_next_measure_repaired():
    part = m21.stream.Part()
    part.id = "P1"

    measure1 = m21.stream.Measure(number=1)
    measure1.timeSignature = m21.meter.TimeSignature("4/4")
    tied_note = m21.note.Note("F4", quarterLength=1)
    tied_note.tie = m21.tie.Tie("start")
    measure1.append(
        [m21.note.Note("C4", quarterLength=1), m21.note.Note("D4", quarterLength=1), m21.note.Note("E4", quarterLength=1), tied_note]
    )

    measure2 = m21.stream.Measure(number=2)
    tie_partner = m21.note.Note("F4", quarterLength=1)
    tie_partner.tie = m21.tie.Tie("stop")
    measure2.append([tie_partner, m21.note.Note("G4", quarterLength=1), m21.note.Note("A4", quarterLength=1), m21.note.Note("B4", quarterLength=1)])

    part.append(measure1)
    part.append(measure2)
    score = m21.stream.Score()
    score.append(part)

    notes.carve_span(measure1, 3.0, 1.0)
    assert tie_partner.tie is None

    xml = score.write("musicxml")
    with open(xml, "r", encoding="utf-8") as f:
        text = f.read()
    # No dangling <tie .../> (sound-only) or <tied .../> (notation)
    # elements should remain anywhere in the exported score.
    assert not re.search(r"<tie\b", text)
    assert not re.search(r"<tied\b", text)


def test_carve_span_no_tie_present_is_a_no_op_for_tie_repair():
    measure = _measure(notes_list=[m21.note.Note(p, quarterLength=1) for p in ["C4", "D4", "E4", "F4"]])
    result = notes.carve_span(measure, 1.0, 1.0)
    assert all(getattr(e, "tie", None) is None for e in result.notesAndRests)


# ---------------------------------------------------------------------------
# End-to-end sanity: parse -> carve -> insert -> export -> reparse


def test_carve_span_end_to_end_round_trip(tmp_path):
    score = m21.stream.Score()
    part = m21.stream.Part()
    part.id = "P1"
    measure = m21.stream.Measure(number=1)
    measure.timeSignature = m21.meter.TimeSignature("4/4")
    measure.append([m21.note.Note(p, quarterLength=1) for p in ["C4", "D4", "E4", "F4"]])
    part.append(measure)
    score.append(part)

    first_path = tmp_path / "first.musicxml"
    score.write("musicxml", fp=str(first_path))

    reparsed = m21.converter.parse(str(first_path))
    reparsed_part = reparsed.parts[0]
    reparsed_measure = list(reparsed_part.getElementsByClass(m21.stream.Measure))[0]

    carved = notes.carve_span(reparsed_measure, 1.0, 1.0)
    carved.insert(1.0, m21.note.Note("G4", quarterLength=1))

    second_path = tmp_path / "second.musicxml"
    reparsed.write("musicxml", fp=str(second_path))

    final = m21.converter.parse(str(second_path))
    final_part = final.parts[0]
    final_measure = list(final_part.getElementsByClass(m21.stream.Measure))[0]

    total = sum(n.duration.quarterLength for n in final_measure.notesAndRests)
    assert float(total) == 4.0
    pitches = [n.pitch.nameWithOctave for n in final_measure.notesAndRests]
    assert pitches == ["C4", "G4", "E4", "F4"]
