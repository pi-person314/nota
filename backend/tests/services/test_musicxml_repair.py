"""Unit tests for `nota.services.musicxml_repair.repair_spanner_order`.

Each MusicXML snippet here is hand-built to isolate one specific shape
(the real, corpus-derived cases are covered end to end in
`tests/tools/test_real_scores.py`), so these tests can pin down exactly
what does and does not get reordered.
"""

from __future__ import annotations

import music21 as m21

from nota.services.musicxml_repair import repair_spanner_order

_HEADER = (
    '<?xml version="1.0" encoding="utf-8"?>\n'
    '<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0 Partwise//EN" '
    '"http://www.musicxml.org/dtds/partwise.dtd">\n'
)


def _score(*parts_xml: str) -> str:
    parts = "\n".join(parts_xml)
    return (
        f"{_HEADER}"
        '<score-partwise version="4.0">\n'
        "  <part-list>\n"
        + "".join(
            f'    <score-part id="P{i + 1}"><part-name>Test</part-name></score-part>\n'
            for i in range(len(parts_xml))
        )
        + "  </part-list>\n"
        f"{parts}\n"
        "</score-partwise>\n"
    )


def _broken_wedge_part(part_id: str = "P1", number: str = "1") -> str:
    """A stop for `number` at the very end of measure 1, and its own start
    at the very beginning of measure 2 -- the exact shape observed on the
    real Haydn/Schoenberg/Schumann corpus scores this module was written
    for: same effective offset, wrong document order.
    """
    return (
        f'  <part id="{part_id}">\n'
        '    <measure number="1">\n'
        "      <attributes><divisions>1</divisions></attributes>\n"
        "      <note><pitch><step>C</step><octave>4</octave></pitch>"
        "<duration>4</duration><type>whole</type></note>\n"
        '      <direction placement="below"><direction-type>'
        f'<wedge number="{number}" type="stop" /></direction-type></direction>\n'
        "    </measure>\n"
        '    <measure number="2">\n'
        '      <direction placement="below"><direction-type>'
        f'<wedge number="{number}" type="crescendo" /></direction-type></direction>\n'
        "      <note><pitch><step>D</step><octave>4</octave></pitch>"
        "<duration>4</duration><type>whole</type></note>\n"
        "    </measure>\n"
        "  </part>"
    )


def _correct_wedge_part(part_id: str = "P1", number: str = "1") -> str:
    """A normally-ordered start-then-stop wedge within one measure."""
    return (
        f'  <part id="{part_id}">\n'
        '    <measure number="1">\n'
        "      <attributes><divisions>1</divisions></attributes>\n"
        '      <direction placement="below"><direction-type>'
        f'<wedge number="{number}" type="crescendo" /></direction-type></direction>\n'
        "      <note><pitch><step>C</step><octave>4</octave></pitch>"
        "<duration>4</duration><type>whole</type></note>\n"
        '      <direction placement="below"><direction-type>'
        f'<wedge number="{number}" type="stop" /></direction-type></direction>\n'
        "    </measure>\n"
        "  </part>"
    )


def _orphan_stop_part(part_id: str = "P1", number: str = "7") -> str:
    """A stop with no matching start anywhere in the document."""
    return (
        f'  <part id="{part_id}">\n'
        '    <measure number="1">\n'
        "      <attributes><divisions>1</divisions></attributes>\n"
        "      <note><pitch><step>C</step><octave>4</octave></pitch>"
        "<duration>4</duration><type>whole</type></note>\n"
        '      <direction placement="below"><direction-type>'
        f'<wedge number="{number}" type="stop" /></direction-type></direction>\n'
        "    </measure>\n"
        "  </part>"
    )


def test_broken_shape_gets_fixed():
    xml = _score(_broken_wedge_part())

    repaired = repair_spanner_order(xml)

    assert repaired != xml
    start_pos = repaired.index('type="crescendo"')
    stop_pos = repaired.index('type="stop"')
    assert start_pos < stop_pos

    reparsed = m21.converter.parse(repaired.encode("utf-8"), format="musicxml")
    wedges = list(
        reparsed.recurse().getElementsByClass((m21.dynamics.Crescendo, m21.dynamics.Diminuendo))
    )
    assert len(wedges) == 1


def test_broken_shape_music21_loses_it_without_the_repair():
    """Documents the defect this module exists to work around: reparsing
    the broken XML as-is silently drops the pair (bounded, no exception).
    """
    xml = _score(_broken_wedge_part())

    reparsed = m21.converter.parse(xml.encode("utf-8"), format="musicxml")
    wedges = list(
        reparsed.recurse().getElementsByClass((m21.dynamics.Crescendo, m21.dynamics.Diminuendo))
    )
    assert len(wedges) == 0


def test_already_correct_xml_passes_through_unchanged():
    xml = _score(_correct_wedge_part())

    repaired = repair_spanner_order(xml)

    assert repaired == xml
    assert repaired is xml  # short-circuited, not merely equal


def test_no_wedge_at_all_passes_through_unchanged():
    xml = _score(
        '  <part id="P1">\n'
        '    <measure number="1">\n'
        "      <note><pitch><step>C</step><octave>4</octave></pitch>"
        "<duration>4</duration><type>whole</type></note>\n"
        "    </measure>\n"
        "  </part>"
    )

    assert repair_spanner_order(xml) is xml


def test_stop_with_no_start_anywhere_is_left_alone():
    xml = _score(_orphan_stop_part())

    repaired = repair_spanner_order(xml)

    assert repaired == xml
    assert repaired is xml


def test_multiple_parts_each_repaired_independently():
    xml = _score(
        _broken_wedge_part(part_id="P1", number="1"),
        _broken_wedge_part(part_id="P2", number="1"),
    )

    repaired = repair_spanner_order(xml)

    reparsed = m21.converter.parse(repaired.encode("utf-8"), format="musicxml")
    for part in reparsed.parts:
        wedges = list(
            part.recurse().getElementsByClass((m21.dynamics.Crescendo, m21.dynamics.Diminuendo))
        )
        assert len(wedges) == 1


def test_one_broken_part_and_one_untouched_part():
    """A correct part sitting alongside a broken one must come out
    byte-identical to how it went in; only the broken part's content moves.
    """
    correct = _correct_wedge_part(part_id="P1", number="1")
    xml = _score(correct, _broken_wedge_part(part_id="P2", number="1"))

    repaired = repair_spanner_order(xml)

    assert repaired != xml
    assert correct in repaired  # the untouched part survives verbatim


def test_bracket_spanner_gets_the_same_generalized_repair():
    """The bracket ("Line") shape observed on beethoven/opus133 is
    structurally identical to the wedge case and must be handled by the
    same generalized logic.
    """
    part = (
        '  <part id="P1">\n'
        '    <measure number="1">\n'
        "      <attributes><divisions>1</divisions></attributes>\n"
        "      <note><pitch><step>C</step><octave>4</octave></pitch>"
        "<duration>4</duration><type>whole</type></note>\n"
        '      <direction placement="above"><direction-type>'
        '<bracket number="1" type="stop" /></direction-type></direction>\n'
        "    </measure>\n"
        '    <measure number="2">\n'
        '      <direction placement="above"><direction-type>'
        '<bracket number="1" type="start" /></direction-type></direction>\n'
        "      <note><pitch><step>D</step><octave>4</octave></pitch>"
        "<duration>4</duration><type>whole</type></note>\n"
        "    </measure>\n"
        "  </part>"
    )
    xml = _score(part)

    repaired = repair_spanner_order(xml)

    assert repaired != xml
    assert repaired.index('type="start"') < repaired.index('type="stop"')


def test_non_simple_direction_is_left_alone():
    """A candidate start direction that carries extra content (here, a
    <sound> sibling) alongside the wedge is not "provably" just a
    misplaced spanner, so it must not be moved.
    """
    part = (
        '  <part id="P1">\n'
        '    <measure number="1">\n'
        "      <attributes><divisions>1</divisions></attributes>\n"
        "      <note><pitch><step>C</step><octave>4</octave></pitch>"
        "<duration>4</duration><type>whole</type></note>\n"
        '      <direction placement="below"><direction-type>'
        '<wedge number="1" type="stop" /></direction-type></direction>\n'
        "    </measure>\n"
        '    <measure number="2">\n'
        '      <direction placement="below"><direction-type>'
        '<wedge number="1" type="crescendo" /></direction-type>'
        '<sound dynamics="80" /></direction>\n'
        "      <note><pitch><step>D</step><octave>4</octave></pitch>"
        "<duration>4</duration><type>whole</type></note>\n"
        "    </measure>\n"
        "  </part>"
    )
    xml = _score(part)

    assert repair_spanner_order(xml) is xml


def test_divisions_change_between_stop_and_candidate_blocks_the_fix():
    """Raw duration units aren't comparable across a <divisions> change,
    so a same-*looking* offset either side of one must not be trusted.
    """
    part = (
        '  <part id="P1">\n'
        '    <measure number="1">\n'
        "      <attributes><divisions>1</divisions></attributes>\n"
        "      <note><pitch><step>C</step><octave>4</octave></pitch>"
        "<duration>4</duration><type>whole</type></note>\n"
        '      <direction placement="below"><direction-type>'
        '<wedge number="1" type="stop" /></direction-type></direction>\n'
        "    </measure>\n"
        '    <measure number="2">\n'
        "      <attributes><divisions>2</divisions></attributes>\n"
        '      <direction placement="below"><direction-type>'
        '<wedge number="1" type="crescendo" /></direction-type></direction>\n'
        "      <note><pitch><step>D</step><octave>4</octave></pitch>"
        "<duration>8</duration><type>whole</type></note>\n"
        "    </measure>\n"
        "  </part>"
    )
    xml = _score(part)

    assert repair_spanner_order(xml) is xml
