"""Unit tests for `nota.services.omr_quality.assess_omr_output`.

Each case here is a hand-built MusicXML string calling `assess_omr_output`
directly, isolating exactly one rule at a time (measure-count/note-count
edges, part mismatches, malformed input). The same rules exercised
end to end through a mocked OMR upload live in
`tests/routes/test_upload_pdf.py`.
"""

from __future__ import annotations

from nota.services.omr_quality import assess_omr_output

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


def _note(step: str = "C", octave: int = 4, duration: int = 4) -> str:
    return (
        f"<note><pitch><step>{step}</step><octave>{octave}</octave></pitch>"
        f"<duration>{duration}</duration><type>whole</type></note>"
    )


def _rest(duration: int = 4) -> str:
    return f"<note><rest/><duration>{duration}</duration><type>whole</type></note>"


def _measure(number: int, *note_xml: str, divisions: bool = False) -> str:
    attrs = "<attributes><divisions>1</divisions></attributes>" if divisions else ""
    return f'<measure number="{number}">{attrs}{"".join(note_xml)}</measure>'


def _sounded_measures_part(part_id: str, count: int) -> str:
    measures = [
        _measure(i + 1, _note(), divisions=(i == 0)) for i in range(count)
    ]
    return f'<part id="{part_id}">{"".join(measures)}</part>'


def test_clean_score_is_acceptable_with_no_warnings():
    # Four measures, one sounded note each -- well under any warn/reject
    # threshold, and enough measures for the empty-fraction rule to apply
    # (it just never crosses it, since nothing here is empty).
    part = "".join(
        _measure(i + 1, _note(), _note(), _note(), divisions=(i == 0))
        for i in range(4)
    )
    xml = _score(f'<part id="P1">{part}</part>')

    report = assess_omr_output(xml)

    assert report.acceptable is True
    assert report.warnings == []


def test_zero_sounded_notes_is_not_acceptable():
    part = "".join(_measure(i + 1, _rest(), divisions=(i == 0)) for i in range(4))
    xml = _score(f'<part id="P1">{part}</part>')

    report = assess_omr_output(xml)

    assert report.acceptable is False


def test_over_ninety_percent_empty_with_enough_measures_is_not_acceptable():
    # 12 measures, 11 empty -- empty fraction ~0.92, over the 0.9 reject
    # threshold, with total_measures (12) at least MIN_MEASURES_FOR_EMPTY_REJECT.
    measures = [_measure(1, _note(), divisions=True)]
    measures += [_measure(i + 2, _rest()) for i in range(11)]
    xml = _score(f'<part id="P1">{"".join(measures)}</part>')

    report = assess_omr_output(xml)

    assert report.acceptable is False


def test_about_half_empty_is_acceptable_with_empty_measure_warning():
    # 6 measures, 3 empty -- empty fraction 0.5, over the 0.4 warn
    # threshold but well under the 0.9 reject threshold.
    measures = []
    for i in range(6):
        if i % 2 == 0:
            measures.append(_measure(i + 1, _note(), _note(), _note(), divisions=(i == 0)))
        else:
            measures.append(_measure(i + 1, _rest()))
    xml = _score(f'<part id="P1">{"".join(measures)}</part>')

    report = assess_omr_output(xml)

    assert report.acceptable is True
    assert (
        "Many measures came out empty — some notation was probably not recognized."
        in report.warnings
    )


def test_mismatched_part_measure_counts_gets_that_warning():
    xml = _score(
        _sounded_measures_part("P1", 4),
        _sounded_measures_part("P2", 5),
    )

    report = assess_omr_output(xml)

    assert report.acceptable is True
    assert (
        "Parts came out with different measure counts — some music may be missing."
        in report.warnings
    )


def test_fewer_than_eight_sounded_notes_gets_that_warning():
    # Four measures, one sounded note each -- 4 sounded notes total, under
    # the 8-note warn threshold, with no empty measures to trigger the
    # other warnings.
    part = "".join(_measure(i + 1, _note(), divisions=(i == 0)) for i in range(4))
    xml = _score(f'<part id="P1">{part}</part>')

    report = assess_omr_output(xml)

    assert report.acceptable is True
    assert report.warnings == [
        "Very little notation was recognized — check the result carefully."
    ]


def test_unparseable_xml_is_acceptable_with_no_warnings():
    report = assess_omr_output("<not xml")

    assert report.acceptable is True
    assert report.warnings == []
