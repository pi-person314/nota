"""Programmatic construction of the MusicXML fixture matrix used by the
notation-tool test suite. Each builder returns a fully-formed music21
Score object; `conftest.py` serializes each one to
`tests/tools/fixtures/<name>.musicxml` once per test session.

Every fixture uses deliberately simple, fully-known content (specific
pitches/durations aren't musically meaningful) so tests can assert exact
measure/beat positions.
"""

from __future__ import annotations

import music21 as m21


def _measure(number: int, notes: list, time_signature: str | None = None) -> m21.stream.Measure:
    measure = m21.stream.Measure(number=number)
    if time_signature is not None:
        measure.timeSignature = m21.meter.TimeSignature(time_signature)
    measure.append(notes)
    return measure


def _part(part_id: str, name: str, measures: list[m21.stream.Measure]) -> m21.stream.Part:
    part = m21.stream.Part()
    part.id = part_id
    part.partName = name
    for measure in measures:
        part.append(measure)
    return part


def _score(*parts: m21.stream.Part) -> m21.stream.Score:
    score = m21.stream.Score()
    for part in parts:
        score.append(part)
    return score


def build_simple_4_4() -> m21.stream.Score:
    """Single part, plain 4/4, 4 measures of quarter notes. The baseline
    fixture for straightforward measure/beat addressing.
    """
    pitches = ["C4", "D4", "E4", "F4", "G4", "A4", "B4", "C5", "D5", "E5", "F5", "G5", "A5", "B5", "C6", "D6"]
    measures = []
    for m_num in range(1, 5):
        four = pitches[(m_num - 1) * 4 : m_num * 4]
        notes = [m21.note.Note(p, quarterLength=1) for p in four]
        measures.append(_measure(m_num, notes, "4/4" if m_num == 1 else None))
    part = _part("P1", "Violin", measures)
    return _score(part)


def build_compound_6_8() -> m21.stream.Score:
    """Single part, 6/8 compound meter, 2 measures of eighth notes (6 per
    measure => beatCount == 2, each beat a dotted quarter).
    """
    pitches = ["C4", "D4", "E4", "F4", "G4", "A4", "B4", "C5", "D5", "E5", "F5", "G5"]
    measures = []
    for m_num in range(1, 3):
        six = pitches[(m_num - 1) * 6 : m_num * 6]
        notes = [m21.note.Note(p, quarterLength=0.5) for p in six]
        measures.append(_measure(m_num, notes, "6/8" if m_num == 1 else None))
    part = _part("P1", "Flute", measures)
    return _score(part)


def build_pickup() -> m21.stream.Score:
    """Single part, 4/4, with a one-beat pickup measure (number 0) followed
    by 3 full measures.
    """
    pickup = m21.stream.Measure(number=0)
    pickup.timeSignature = m21.meter.TimeSignature("4/4")
    pickup.paddingLeft = 3.0
    pickup_note = m21.note.Note("G4", quarterLength=1)
    pickup.append(pickup_note)

    measures = [pickup]
    pitches = ["C4", "D4", "E4", "F4", "G4", "A4", "B4", "C5", "D5", "E5", "F5", "G5"]
    for m_num in range(1, 4):
        four = pitches[(m_num - 1) * 4 : m_num * 4]
        notes = [m21.note.Note(p, quarterLength=1) for p in four]
        measures.append(_measure(m_num, notes))

    part = _part("P1", "Oboe", measures)
    return _score(part)


def build_meter_change() -> m21.stream.Score:
    """Single part, 4 measures of 4/4 followed by 3 measures of 3/4
    (meter change declared on measure 5, inherited via context by 6-7).
    """
    measures = []
    pitches_4_4 = ["C4", "D4", "E4", "F4"] * 4
    for m_num in range(1, 5):
        four = pitches_4_4[(m_num - 1) * 4 : m_num * 4]
        notes = [m21.note.Note(p, quarterLength=1) for p in four]
        measures.append(_measure(m_num, notes, "4/4" if m_num == 1 else None))

    pitches_3_4 = ["G4", "A4", "B4"] * 3
    for i, m_num in enumerate(range(5, 8)):
        three = pitches_3_4[i * 3 : i * 3 + 3]
        notes = [m21.note.Note(p, quarterLength=1) for p in three]
        measures.append(_measure(m_num, notes, "3/4" if m_num == 5 else None))

    part = _part("P1", "Clarinet", measures)
    return _score(part)


def build_two_voices() -> m21.stream.Score:
    """Single part, single staff, 2 measures of 4/4 with two independent
    voices (soprano-ish quarter notes over alto-ish half notes).
    """
    measures = []
    for m_num in range(1, 3):
        measure = m21.stream.Measure(number=m_num)
        if m_num == 1:
            measure.timeSignature = m21.meter.TimeSignature("4/4")

        voice1 = m21.stream.Voice()
        voice1.id = 1
        voice1.append([m21.note.Note(p, quarterLength=1) for p in ["C5", "D5", "E5", "F5"]])

        voice2 = m21.stream.Voice()
        voice2.id = 2
        voice2.append([m21.note.Note(p, quarterLength=2) for p in ["C4", "D4"]])

        measure.insert(0, voice1)
        measure.insert(0, voice2)
        measures.append(measure)

    part = _part("P1", "Piano", measures)
    return _score(part)


def build_chords() -> m21.stream.Score:
    """Single part, 2 measures of 4/4 mixing chords and single notes."""
    measures = []

    m1 = m21.stream.Measure(number=1)
    m1.timeSignature = m21.meter.TimeSignature("4/4")
    m1.append(
        [
            m21.chord.Chord(["C4", "E4", "G4"], quarterLength=1),
            m21.note.Note("D4", quarterLength=1),
            m21.chord.Chord(["F4", "A4", "C5"], quarterLength=2),
        ]
    )
    measures.append(m1)

    m2 = m21.stream.Measure(number=2)
    m2.append(
        [
            m21.note.Note("G4", quarterLength=2),
            m21.chord.Chord(["C4", "F4", "A4"], quarterLength=2),
        ]
    )
    measures.append(m2)

    part = _part("P1", "Guitar", measures)
    return _score(part)


def build_grace_notes() -> m21.stream.Score:
    """Single part, 2 measures of 4/4 where a grace note precedes the note
    on beat 1 and another precedes the note on beat 3.
    """
    m1 = m21.stream.Measure(number=1)
    m1.timeSignature = m21.meter.TimeSignature("4/4")

    grace1 = m21.note.Note("B4").getGrace()
    main1 = m21.note.Note("C5", quarterLength=1)
    main2 = m21.note.Note("D5", quarterLength=1)
    grace2 = m21.note.Note("E5").getGrace()
    main3 = m21.note.Note("F5", quarterLength=1)
    main4 = m21.note.Note("G5", quarterLength=1)
    m1.append([grace1, main1, main2, grace2, main3, main4])

    m2 = m21.stream.Measure(number=2)
    m2.append([m21.note.Note(p, quarterLength=1) for p in ["A5", "B5", "C6", "D6"]])

    part = _part("P1", "Violin II", [m1, m2])
    return _score(part)


def build_duplicate_violin_names() -> m21.stream.Score:
    """4 parts, 2 measures of 4/4, where the first two parts are both
    named/id'd "Violin" (mirroring what a real upload of a score like
    Beethoven's op. 18 no. 1 produces after music21's writer collapses
    each duplicate-named part's id to match its name). Used to test
    ordinal-alias part resolution against a small, fully-known score
    rather than only against real corpus data.
    """
    pitches = ["C4", "D4", "E4", "F4", "G4", "A4", "B4", "C5"]

    def _fresh_measures():
        measures = []
        for m_num in range(1, 3):
            four = pitches[(m_num - 1) * 4 : m_num * 4]
            notes = [m21.note.Note(p, quarterLength=1) for p in four]
            measures.append(_measure(m_num, notes, "4/4" if m_num == 1 else None))
        return measures

    violin1 = _part("Violin", "Violin", _fresh_measures())
    violin2 = _part("Violin", "Violin", _fresh_measures())
    viola = _part("Viola", "Viola", _fresh_measures())
    cello = _part("Violoncello", "Violoncello", _fresh_measures())
    return _score(violin1, violin2, viola, cello)


FIXTURE_BUILDERS = {
    "simple_4_4": build_simple_4_4,
    "compound_6_8": build_compound_6_8,
    "pickup": build_pickup,
    "meter_change": build_meter_change,
    "two_voices": build_two_voices,
    "chords": build_chords,
    "grace_notes": build_grace_notes,
}
