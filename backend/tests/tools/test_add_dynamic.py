"""Tests for nota.mcp_server.tools.add_dynamic."""

from __future__ import annotations

from nota.mcp_server import tools
from nota.mcp_server.errors import ErrorCode

from .assertions import (
    assert_error,
    assert_ids_present,
    assert_renders_with_verovio,
    assert_round_trips,
    assert_success,
)


def test_add_dynamic_simple_4_4(make_score):
    sid = make_score("simple_4_4")
    result = assert_success(tools.add_dynamic(sid, measure=2, beat=1, dynamic="f"))

    assert len(result["changed_element_ids"]) == 1
    assert_round_trips(sid)
    assert_ids_present(sid, result["changed_element_ids"])
    assert_renders_with_verovio(sid)
    assert "measure 2" in result["summary"]
    assert "f" in result["summary"]


def test_add_dynamic_compound_6_8_offbeat(make_score):
    sid = make_score("compound_6_8")
    # 6/8 has beatCount == 2 (dotted-quarter beats); beat 1.5 is a valid
    # off-beat position within beat 1's dotted-quarter span.
    result = assert_success(tools.add_dynamic(sid, measure=1, beat=1.5, dynamic="mp"))
    assert_round_trips(sid)
    assert_ids_present(sid, result["changed_element_ids"])
    assert_renders_with_verovio(sid)


def test_add_dynamic_pickup_measure_zero(make_score):
    sid = make_score("pickup")
    result = assert_success(tools.add_dynamic(sid, measure=0, beat=4, dynamic="p"))
    assert_round_trips(sid)
    assert_ids_present(sid, result["changed_element_ids"])
    assert_renders_with_verovio(sid)


def test_add_dynamic_after_meter_change(make_score):
    sid = make_score("meter_change")
    # Measure 6 is in the 3/4 region; beat 3 is valid there (would be
    # out of range if the 4/4 meter were incorrectly still in effect).
    result = assert_success(tools.add_dynamic(sid, measure=6, beat=3, dynamic="ff"))
    assert_round_trips(sid)
    assert_ids_present(sid, result["changed_element_ids"])


def test_add_dynamic_dedup_returns_success_no_change(make_score, snapshot_count):
    sid = make_score("simple_4_4")
    first = assert_success(tools.add_dynamic(sid, measure=2, beat=1, dynamic="f"))
    assert snapshot_count(sid) == 1

    second = assert_success(tools.add_dynamic(sid, measure=2, beat=1, dynamic="f"))
    assert second["changed_element_ids"] == []
    assert "f" in second["summary"]
    assert "measure 2" in second["summary"]
    assert "already present" in second["summary"]

    # No-op must not create a second undo entry.
    assert snapshot_count(sid) == 1
    assert first["changed_element_ids"] != []


def test_add_dynamic_different_dynamic_same_spot_is_not_a_dup(make_score):
    sid = make_score("simple_4_4")
    tools.add_dynamic(sid, measure=2, beat=1, dynamic="f")
    second = assert_success(tools.add_dynamic(sid, measure=2, beat=1, dynamic="p"))
    assert second["changed_element_ids"] != []


def test_add_dynamic_score_not_found():
    result = tools.add_dynamic("does-not-exist", measure=1, beat=1, dynamic="f")
    assert_error(result, ErrorCode.SCORE_NOT_FOUND)


def test_add_dynamic_measure_out_of_range(make_score):
    sid = make_score("simple_4_4")
    result = tools.add_dynamic(sid, measure=99, beat=1, dynamic="f")
    err = assert_error(result, ErrorCode.MEASURE_OUT_OF_RANGE)
    assert "4 measures" in err["message"]


def test_add_dynamic_measure_zero_without_pickup_is_out_of_range(make_score):
    sid = make_score("simple_4_4")
    result = tools.add_dynamic(sid, measure=0, beat=1, dynamic="f")
    assert_error(result, ErrorCode.MEASURE_OUT_OF_RANGE)


def test_add_dynamic_beat_out_of_range(make_score):
    sid = make_score("simple_4_4")
    result = tools.add_dynamic(sid, measure=1, beat=7, dynamic="f")
    err = assert_error(result, ErrorCode.BEAT_OUT_OF_RANGE)
    assert "4 beats" in err["message"]


def test_add_dynamic_beat_out_of_range_compound_meter(make_score):
    sid = make_score("compound_6_8")
    # 6/8 only has 2 beats (each a dotted quarter); beat 3 doesn't exist.
    result = tools.add_dynamic(sid, measure=1, beat=3, dynamic="f")
    err = assert_error(result, ErrorCode.BEAT_OUT_OF_RANGE)
    assert "2 beats" in err["message"]


def test_add_dynamic_invalid_enum_value(make_score):
    sid = make_score("simple_4_4")
    result = tools.add_dynamic(sid, measure=1, beat=1, dynamic="super-loud")
    err = assert_error(result, ErrorCode.INVALID_ENUM_VALUE)
    assert "super-loud" in err["message"]


def test_add_dynamic_part_not_found(make_score):
    sid = make_score("simple_4_4")
    result = tools.add_dynamic(sid, measure=1, beat=1, dynamic="f", part="Tuba")
    err = assert_error(result, ErrorCode.PART_NOT_FOUND)
    assert "Violin" in err["message"]


def test_add_dynamic_valid_part_by_name(make_score):
    sid = make_score("simple_4_4")
    result = assert_success(tools.add_dynamic(sid, measure=1, beat=1, dynamic="f", part="Violin"))
    assert result["changed_element_ids"]


def test_add_dynamic_validation_failure_leaves_no_snapshot(make_score, snapshot_count):
    sid = make_score("simple_4_4")
    assert snapshot_count(sid) == 0
    tools.add_dynamic(sid, measure=99, beat=1, dynamic="f")
    assert snapshot_count(sid) == 0


def test_add_dynamic_success_creates_snapshot_and_undo_restores(make_score, snapshot_count):
    from nota import storage

    sid = make_score("simple_4_4")
    before = storage.read_xml(sid)

    tools.add_dynamic(sid, measure=2, beat=1, dynamic="f")
    assert snapshot_count(sid) == 1
    after = storage.read_xml(sid)
    assert after != before

    storage.undo(sid)
    assert storage.read_xml(sid) == before


def test_add_dynamic_chords_fixture(make_score):
    sid = make_score("chords")
    result = assert_success(tools.add_dynamic(sid, measure=1, beat=2, dynamic="mf"))
    assert_round_trips(sid)
    assert_ids_present(sid, result["changed_element_ids"])


def test_add_dynamic_two_voices_fixture(make_score):
    sid = make_score("two_voices")
    # Dynamics attach to the measure at an offset, independent of voice,
    # so this should succeed even though two notes occupy that beat.
    result = assert_success(tools.add_dynamic(sid, measure=1, beat=1, dynamic="f"))
    assert_round_trips(sid)
    assert_ids_present(sid, result["changed_element_ids"])
