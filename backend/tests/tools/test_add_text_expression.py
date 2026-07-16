"""Tests for nota.mcp_server.tools.add_text_expression."""

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


def test_add_text_expression_simple_4_4(make_score):
    sid = make_score("simple_4_4")
    result = assert_success(tools.add_text_expression(sid, measure=1, beat=1, text="dolce"))
    xml = assert_round_trips(sid)
    assert_ids_present(sid, result["changed_element_ids"])
    assert_renders_with_verovio(sid)
    assert "dolce" in result["summary"]

    reparsed = m21.converter.parse(xml.encode("utf-8"), format="musicxml")
    expressions = list(reparsed.recurse().getElementsByClass(m21.expressions.TextExpression))
    assert any(e.content == "dolce" for e in expressions)


def test_add_text_expression_compound_6_8_offbeat(make_score):
    sid = make_score("compound_6_8")
    result = assert_success(tools.add_text_expression(sid, measure=1, beat=1.5, text="espressivo"))
    assert_round_trips(sid)
    assert_ids_present(sid, result["changed_element_ids"])


def test_add_text_expression_pickup_measure(make_score):
    sid = make_score("pickup")
    result = assert_success(tools.add_text_expression(sid, measure=0, beat=4, text="sotto voce"))
    assert_round_trips(sid)
    assert_ids_present(sid, result["changed_element_ids"])
    assert_renders_with_verovio(sid)


def test_add_text_expression_after_meter_change(make_score):
    sid = make_score("meter_change")
    result = assert_success(tools.add_text_expression(sid, measure=6, beat=2, text="cantabile"))
    assert_round_trips(sid)
    assert_ids_present(sid, result["changed_element_ids"])


def test_add_text_expression_chords_fixture(make_score):
    sid = make_score("chords")
    result = assert_success(tools.add_text_expression(sid, measure=1, beat=2, text="dolce"))
    assert_round_trips(sid)
    assert_ids_present(sid, result["changed_element_ids"])


def test_add_text_expression_two_voices(make_score):
    sid = make_score("two_voices")
    result = assert_success(tools.add_text_expression(sid, measure=1, beat=1, text="dolce"))
    assert_round_trips(sid)
    assert_ids_present(sid, result["changed_element_ids"])


def test_add_text_expression_no_note_at_position_still_succeeds_with_no_anchor(make_score):
    """No note is required for a free-text expression; when nothing starts
    exactly at that offset, there's simply nothing to highlight.
    """
    sid = make_score("simple_4_4")
    result = assert_success(tools.add_text_expression(sid, measure=1, beat=1.5, text="rit."))
    assert result["changed_element_ids"] == []
    assert_round_trips(sid)


def test_add_text_expression_strips_whitespace(make_score):
    sid = make_score("simple_4_4")
    result = assert_success(tools.add_text_expression(sid, measure=1, beat=1, text="  dolce  "))
    xml = storage.read_xml(sid)
    reparsed = m21.converter.parse(xml.encode("utf-8"), format="musicxml")
    expressions = list(reparsed.recurse().getElementsByClass(m21.expressions.TextExpression))
    assert any(e.content == "dolce" for e in expressions)
    assert result


# ----------------------------------------------------------------- error paths


def test_add_text_expression_score_not_found():
    result = tools.add_text_expression("nope", measure=1, beat=1, text="dolce")
    assert_error(result, ErrorCode.SCORE_NOT_FOUND)


def test_add_text_expression_empty_text_rejected(make_score):
    sid = make_score("simple_4_4")
    result = tools.add_text_expression(sid, measure=1, beat=1, text="")
    assert_error(result, ErrorCode.TEXT_REQUIRED)


def test_add_text_expression_whitespace_only_text_rejected(make_score):
    sid = make_score("simple_4_4")
    result = tools.add_text_expression(sid, measure=1, beat=1, text="   ")
    assert_error(result, ErrorCode.TEXT_REQUIRED)


def test_add_text_expression_measure_out_of_range(make_score):
    sid = make_score("simple_4_4")
    result = tools.add_text_expression(sid, measure=99, beat=1, text="dolce")
    err = assert_error(result, ErrorCode.MEASURE_OUT_OF_RANGE)
    assert "4 measures" in err["message"]


def test_add_text_expression_beat_out_of_range(make_score):
    sid = make_score("simple_4_4")
    result = tools.add_text_expression(sid, measure=1, beat=7, text="dolce")
    err = assert_error(result, ErrorCode.BEAT_OUT_OF_RANGE)
    assert "4 beats" in err["message"]


def test_add_text_expression_part_not_found(make_score):
    sid = make_score("simple_4_4")
    result = tools.add_text_expression(sid, measure=1, beat=1, text="dolce", part="Tuba")
    err = assert_error(result, ErrorCode.PART_NOT_FOUND)
    assert "Violin" in err["message"]


# ------------------------------------------------------------------ snapshots


def test_add_text_expression_validation_failure_leaves_no_snapshot(make_score, snapshot_count):
    sid = make_score("simple_4_4")
    tools.add_text_expression(sid, measure=99, beat=1, text="dolce")
    tools.add_text_expression(sid, measure=1, beat=1, text="")
    assert snapshot_count(sid) == 0


def test_add_text_expression_success_creates_snapshot_and_undo_restores(make_score, snapshot_count):
    sid = make_score("simple_4_4")
    before = storage.read_xml(sid)

    tools.add_text_expression(sid, measure=1, beat=1, text="dolce")
    assert snapshot_count(sid) == 1
    assert storage.read_xml(sid) != before

    storage.undo(sid)
    assert storage.read_xml(sid) == before
