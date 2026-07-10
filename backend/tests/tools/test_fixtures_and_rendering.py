"""Sanity checks on the generated fixture matrix itself, plus Verovio
render checks (skipped, visibly, when verovio isn't installed) for the
output of each tool on each relevant fixture.
"""

from __future__ import annotations

import music21 as m21
import pytest

from nota import storage
from nota.mcp_server import tools

from .conftest import VEROVIO_AVAILABLE, requires_verovio
from .musicxml_builders import FIXTURE_BUILDERS

ALL_FIXTURES = sorted(FIXTURE_BUILDERS)


@pytest.mark.parametrize("fixture_name", ALL_FIXTURES)
def test_fixture_round_trips_with_music21(fixture_xml_cache, fixture_name):
    info = fixture_xml_cache[fixture_name]
    reparsed = m21.converter.parse(info.xml.encode("utf-8"), format="musicxml")
    assert list(reparsed.recurse().notes), fixture_name


def test_fixture_matrix_shapes(fixture_xml_cache):
    assert fixture_xml_cache["simple_4_4"].measure_count == 4
    assert not fixture_xml_cache["simple_4_4"].has_pickup

    assert fixture_xml_cache["compound_6_8"].measure_count == 2

    assert fixture_xml_cache["pickup"].has_pickup
    assert fixture_xml_cache["pickup"].measure_count == 3

    assert fixture_xml_cache["meter_change"].measure_count == 7


def test_pickup_fixture_preserves_anacrusis_on_round_trip(fixture_xml_cache):
    info = fixture_xml_cache["pickup"]
    reparsed = m21.converter.parse(info.xml.encode("utf-8"), format="musicxml")
    part = reparsed.parts[0]
    first_measure = part.getElementsByClass(m21.stream.Measure)[0]
    assert first_measure.number == 0
    assert first_measure.paddingLeft == 3.0
    assert first_measure.notes[0].beat == 4.0


def test_meter_change_fixture_reports_correct_meters(fixture_xml_cache):
    info = fixture_xml_cache["meter_change"]
    reparsed = m21.converter.parse(info.xml.encode("utf-8"), format="musicxml")
    part = reparsed.parts[0]
    measures = {m.number: m for m in part.getElementsByClass(m21.stream.Measure)}
    assert measures[3].getContextByClass(m21.meter.TimeSignature).ratioString == "4/4"
    assert measures[6].getContextByClass(m21.meter.TimeSignature).ratioString == "3/4"


@requires_verovio
@pytest.mark.parametrize("fixture_name", ALL_FIXTURES)
def test_fixture_renders_with_verovio(fixture_xml_cache, fixture_name):
    import verovio

    toolkit = verovio.toolkit()
    assert toolkit.loadData(fixture_xml_cache[fixture_name].xml)
    svg = toolkit.renderToSVG(1)
    assert svg and "<svg" in svg


@requires_verovio
@pytest.mark.parametrize("fixture_name", ALL_FIXTURES)
def test_tool_output_renders_with_verovio_per_fixture(make_score, fixture_name):
    """Run one representative mutation per tool against every fixture and
    assert Verovio renders the resulting file. Positions are chosen to be
    valid in every fixture (measure 1 always has a note on beat 1; the
    pickup fixture's measure 1 is a full bar).
    """
    import verovio

    sid = make_score(fixture_name)
    assert tools.add_dynamic(sid, measure=1, beat=1, dynamic="mf")["success"]
    assert tools.add_articulation(sid, measure=1, beat=1, articulation="accent")["success"]
    assert tools.draw_slur(sid, start_measure=1, start_beat=1, end_measure=1, end_beat=2)[
        "success"
    ]

    toolkit = verovio.toolkit()
    assert toolkit.loadData(storage.read_xml(sid))
    svg = toolkit.renderToSVG(1)
    assert svg and "<svg" in svg


def test_verovio_installed_note():
    """Not an assertion about the code under test: makes the availability
    of the optional Verovio render checks visible in the test report.
    """
    if not VEROVIO_AVAILABLE:
        pytest.skip("verovio is not installed; render assertions were skipped")
