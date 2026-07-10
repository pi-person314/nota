"""Sanity check that music21 is correctly installed and functional on this
Python version: build a small score, round-trip it through MusicXML on
disk, and verify the structure survives parsing.
"""

from __future__ import annotations

import music21 as m21


def test_music21_round_trip_measure_count(tmp_path):
    score = m21.stream.Score()
    part = m21.stream.Part()
    part.partName = "Violin"

    for pitch in ["C4", "D4", "E4", "F4"]:
        measure = m21.stream.Measure()
        measure.append(m21.note.Note(pitch, type="whole"))
        part.append(measure)

    score.insert(0, part)

    out_path = tmp_path / "sample.musicxml"
    score.write("musicxml", fp=str(out_path))

    reparsed = m21.converter.parse(str(out_path))
    reparsed_part = reparsed.parts[0]
    measures = reparsed_part.getElementsByClass(m21.stream.Measure)

    assert len(measures) == 4

    notes = list(reparsed_part.recurse().notes)
    assert len(notes) == 4
    assert [n.nameWithOctave for n in notes] == ["C4", "D4", "E4", "F4"]
