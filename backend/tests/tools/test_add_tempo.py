"""Tests for nota.mcp_server.tools.add_tempo."""

from __future__ import annotations

import music21 as m21

from nota import storage
from nota.mcp_server import tools
from nota.mcp_server.errors import ErrorCode

from .assertions import (
    assert_error,
    assert_ids_present,
    assert_renders_with_verovio,
    assert_round_trips,
    assert_success,
)


def test_add_tempo_bpm_only(make_score):
    sid = make_score("simple_4_4")
    result = assert_success(tools.add_tempo(sid, measure=1, bpm=120))
    assert len(result["changed_element_ids"]) == 1
    xml = assert_round_trips(sid)
    assert_ids_present(sid, result["changed_element_ids"])
    assert_renders_with_verovio(sid)

    reparsed = m21.converter.parse(xml.encode("utf-8"), format="musicxml")
    marks = list(reparsed.recurse().getElementsByClass(m21.tempo.MetronomeMark))
    assert any(m.number == 120 for m in marks)


def test_add_tempo_text_only(make_score):
    sid = make_score("simple_4_4")
    result = assert_success(tools.add_tempo(sid, measure=1, text="Andante"))
    assert_round_trips(sid)
    assert_ids_present(sid, result["changed_element_ids"])


def test_add_tempo_bpm_and_text(make_score):
    sid = make_score("simple_4_4")
    result = assert_success(tools.add_tempo(sid, measure=1, bpm=90, text="Andante"))
    assert_round_trips(sid)
    assert_ids_present(sid, result["changed_element_ids"])
    assert "90" in result["summary"]
    assert "Andante" in result["summary"]


def test_add_tempo_custom_unit(make_score):
    sid = make_score("compound_6_8")
    result = assert_success(tools.add_tempo(sid, measure=1, bpm=60, unit="dotted_quarter"))
    xml = assert_round_trips(sid)
    assert_ids_present(sid, result["changed_element_ids"])
    reparsed = m21.converter.parse(xml.encode("utf-8"), format="musicxml")
    marks = list(reparsed.recurse().getElementsByClass(m21.tempo.MetronomeMark))
    assert any(m.referent.dots == 1 and m.referent.type == "quarter" for m in marks)


def test_add_tempo_defaults_to_quarter_unit(make_score):
    sid = make_score("simple_4_4")
    result = assert_success(tools.add_tempo(sid, measure=1, bpm=100))
    xml = storage.read_xml(sid)
    reparsed = m21.converter.parse(xml.encode("utf-8"), format="musicxml")
    marks = list(reparsed.recurse().getElementsByClass(m21.tempo.MetronomeMark))
    assert any(m.referent.type == "quarter" and m.referent.dots == 0 for m in marks)
    assert result


def test_add_tempo_pickup_measure(make_score):
    sid = make_score("pickup")
    result = assert_success(tools.add_tempo(sid, measure=0, bpm=80))
    assert_round_trips(sid)
    assert_ids_present(sid, result["changed_element_ids"])
    assert_renders_with_verovio(sid)


def test_add_tempo_after_meter_change(make_score):
    sid = make_score("meter_change")
    result = assert_success(tools.add_tempo(sid, measure=5, bpm=140))
    assert_round_trips(sid)
    assert_ids_present(sid, result["changed_element_ids"])


def test_add_tempo_bounds_edge_values_accepted(make_score):
    sid = make_score("simple_4_4")
    assert_success(tools.add_tempo(sid, measure=1, bpm=10))
    assert_success(tools.add_tempo(sid, measure=2, bpm=400))


# ----------------------------------------------------------------- error paths


def test_add_tempo_score_not_found():
    result = tools.add_tempo("nope", measure=1, bpm=120)
    assert_error(result, ErrorCode.SCORE_NOT_FOUND)


def test_add_tempo_neither_bpm_nor_text_rejected(make_score):
    sid = make_score("simple_4_4")
    result = tools.add_tempo(sid, measure=1)
    assert_error(result, ErrorCode.TEXT_REQUIRED)


def test_add_tempo_blank_text_with_no_bpm_rejected(make_score):
    sid = make_score("simple_4_4")
    result = tools.add_tempo(sid, measure=1, text="   ")
    assert_error(result, ErrorCode.TEXT_REQUIRED)


def test_add_tempo_bpm_too_low(make_score):
    sid = make_score("simple_4_4")
    result = tools.add_tempo(sid, measure=1, bpm=5)
    err = assert_error(result, ErrorCode.INVALID_ENUM_VALUE)
    assert "10" in err["message"]


def test_add_tempo_bpm_too_high(make_score):
    sid = make_score("simple_4_4")
    result = tools.add_tempo(sid, measure=1, bpm=1000)
    err = assert_error(result, ErrorCode.INVALID_ENUM_VALUE)
    assert "400" in err["message"]


def test_add_tempo_invalid_unit(make_score):
    sid = make_score("simple_4_4")
    result = tools.add_tempo(sid, measure=1, bpm=120, unit="thirty-second")
    err = assert_error(result, ErrorCode.INVALID_ENUM_VALUE)
    assert "thirty-second" in err["message"]
    assert "quarter" in err["message"]


def test_add_tempo_measure_out_of_range(make_score):
    sid = make_score("simple_4_4")
    result = tools.add_tempo(sid, measure=99, bpm=120)
    err = assert_error(result, ErrorCode.MEASURE_OUT_OF_RANGE)
    assert "4 measures" in err["message"]


def test_add_tempo_part_not_found(make_score):
    sid = make_score("simple_4_4")
    result = tools.add_tempo(sid, measure=1, bpm=120, part="Tuba")
    err = assert_error(result, ErrorCode.PART_NOT_FOUND)
    assert "Violin" in err["message"]


# ------------------------------------------------------------------ snapshots


def test_add_tempo_validation_failure_leaves_no_snapshot(make_score, snapshot_count):
    sid = make_score("simple_4_4")
    tools.add_tempo(sid, measure=1)
    tools.add_tempo(sid, measure=1, bpm=9999)
    tools.add_tempo(sid, measure=99, bpm=120)
    assert snapshot_count(sid) == 0


def test_add_tempo_success_creates_snapshot_and_undo_restores(make_score, snapshot_count):
    sid = make_score("simple_4_4")
    before = storage.read_xml(sid)

    tools.add_tempo(sid, measure=1, bpm=120)
    assert snapshot_count(sid) == 1
    assert storage.read_xml(sid) != before

    storage.undo(sid)
    assert storage.read_xml(sid) == before
