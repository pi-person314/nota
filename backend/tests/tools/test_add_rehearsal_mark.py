"""Tests for nota.mcp_server.tools.add_rehearsal_mark."""

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


def test_add_rehearsal_mark_simple_4_4(make_score):
    sid = make_score("simple_4_4")
    result = assert_success(tools.add_rehearsal_mark(sid, measure=2, label="A"))
    xml = assert_round_trips(sid)
    assert_ids_present(sid, result["changed_element_ids"])
    assert_renders_with_verovio(sid)
    assert "A" in result["summary"]

    reparsed = m21.converter.parse(xml.encode("utf-8"), format="musicxml")
    marks = list(reparsed.recurse().getElementsByClass(m21.expressions.RehearsalMark))
    assert any(m.content == "A" for m in marks)


def test_add_rehearsal_mark_pickup_measure(make_score):
    sid = make_score("pickup")
    result = assert_success(tools.add_rehearsal_mark(sid, measure=0, label="Intro"))
    assert_round_trips(sid)
    assert_ids_present(sid, result["changed_element_ids"])
    assert_renders_with_verovio(sid)


def test_add_rehearsal_mark_after_meter_change(make_score):
    sid = make_score("meter_change")
    result = assert_success(tools.add_rehearsal_mark(sid, measure=6, label="B"))
    assert_round_trips(sid)
    assert_ids_present(sid, result["changed_element_ids"])


def test_add_rehearsal_mark_chords_fixture(make_score):
    sid = make_score("chords")
    result = assert_success(tools.add_rehearsal_mark(sid, measure=1, label="C"))
    assert_round_trips(sid)
    assert_ids_present(sid, result["changed_element_ids"])


def test_add_rehearsal_mark_dedup_returns_success_no_change(make_score, snapshot_count):
    sid = make_score("simple_4_4")
    first = assert_success(tools.add_rehearsal_mark(sid, measure=2, label="A"))
    assert snapshot_count(sid) == 1
    assert first["changed_element_ids"] != []

    second = assert_success(tools.add_rehearsal_mark(sid, measure=2, label="A"))
    assert second["changed_element_ids"] == []
    assert "already present" in second["summary"]

    # No-op must not create a second undo entry.
    assert snapshot_count(sid) == 1


def test_add_rehearsal_mark_different_label_same_measure_is_not_a_dup(make_score):
    sid = make_score("simple_4_4")
    tools.add_rehearsal_mark(sid, measure=2, label="A")
    second = assert_success(tools.add_rehearsal_mark(sid, measure=2, label="B"))
    assert second["changed_element_ids"] != []


def test_add_rehearsal_mark_strips_whitespace_for_dedup(make_score):
    sid = make_score("simple_4_4")
    tools.add_rehearsal_mark(sid, measure=2, label="A")
    second = tools.add_rehearsal_mark(sid, measure=2, label="  A  ")
    assert second["changed_element_ids"] == []
    assert "already present" in second["summary"]


# ----------------------------------------------------------------- error paths


def test_add_rehearsal_mark_score_not_found():
    result = tools.add_rehearsal_mark("nope", measure=1, label="A")
    assert_error(result, ErrorCode.SCORE_NOT_FOUND)


def test_add_rehearsal_mark_empty_label_rejected(make_score):
    sid = make_score("simple_4_4")
    result = tools.add_rehearsal_mark(sid, measure=1, label="")
    assert_error(result, ErrorCode.TEXT_REQUIRED)


def test_add_rehearsal_mark_whitespace_only_label_rejected(make_score):
    sid = make_score("simple_4_4")
    result = tools.add_rehearsal_mark(sid, measure=1, label="   ")
    assert_error(result, ErrorCode.TEXT_REQUIRED)


def test_add_rehearsal_mark_measure_out_of_range(make_score):
    sid = make_score("simple_4_4")
    result = tools.add_rehearsal_mark(sid, measure=99, label="A")
    err = assert_error(result, ErrorCode.MEASURE_OUT_OF_RANGE)
    assert "4 measures" in err["message"]


def test_add_rehearsal_mark_part_not_found(make_score):
    sid = make_score("simple_4_4")
    result = tools.add_rehearsal_mark(sid, measure=1, label="A", part="Tuba")
    err = assert_error(result, ErrorCode.PART_NOT_FOUND)
    assert "Violin" in err["message"]


# ------------------------------------------------------------------ snapshots


def test_add_rehearsal_mark_validation_failure_leaves_no_snapshot(make_score, snapshot_count):
    sid = make_score("simple_4_4")
    tools.add_rehearsal_mark(sid, measure=99, label="A")
    tools.add_rehearsal_mark(sid, measure=1, label="")
    assert snapshot_count(sid) == 0


def test_add_rehearsal_mark_success_creates_snapshot_and_undo_restores(make_score, snapshot_count):
    sid = make_score("simple_4_4")
    before = storage.read_xml(sid)

    tools.add_rehearsal_mark(sid, measure=2, label="A")
    assert snapshot_count(sid) == 1
    assert storage.read_xml(sid) != before

    storage.undo(sid)
    assert storage.read_xml(sid) == before
