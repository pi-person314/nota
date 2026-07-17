"""Tests for the per-call harness lifecycle and xml:id machinery that are
independent of any single tool: no-op handling, id-verification failure,
the chord id fallback, and pickup beat arithmetic edge cases.
"""

from __future__ import annotations

from unittest.mock import patch

import music21 as m21
import pytest

from nota import storage
from nota.mcp_server import ids, tools
from nota.mcp_server.errors import ErrorCode
from nota.mcp_server.harness import ToolPlan, run_tool

from .assertions import assert_error


def test_run_tool_score_not_found_before_parse():
    result = run_tool("missing-id", "label", lambda score: ToolPlan(no_op_summary="x"))
    err = assert_error(result, ErrorCode.SCORE_NOT_FOUND)
    assert "missing-id" in err["message"]


def test_no_op_plan_writes_nothing_and_snapshots_nothing(make_score, snapshot_count):
    sid = make_score("simple_4_4")
    before = storage.read_xml(sid)

    result = run_tool(sid, "noop", lambda score: ToolPlan(no_op_summary="nothing to do"))

    assert result == {"success": True, "changed_element_ids": [], "summary": "nothing to do"}
    assert storage.read_xml(sid) == before
    assert snapshot_count(sid) == 0


def test_tool_plan_requires_exactly_one_mode():
    with pytest.raises(ValueError):
        ToolPlan()
    with pytest.raises(ValueError):
        ToolPlan(apply=lambda: ([], "x"), no_op_summary="y")


def test_id_verification_raises_when_id_not_serialized(make_score):
    """If a mutation claims an id that never lands in the written XML, the
    harness must fail loudly rather than hand the frontend a dangling id.
    """
    sid = make_score("simple_4_4")

    def planner(score):
        def apply():
            return ["nota-never-written"], "bogus"

        return ToolPlan(apply=apply)

    with pytest.raises(RuntimeError, match="nota-never-written"):
        run_tool(sid, "bogus", planner)


def test_export_failure_during_apply_returns_structured_error_not_a_crash(
    make_score, snapshot_count
):
    """Regression test for a real breakage found by round-tripping every
    bundled music21 corpus score through this pipeline: some real scores
    parse cleanly but cannot be re-exported by music21 (a note with a
    duration so short — a "2048th" from a nested tuplet — that music21's
    own MusicXML writer refuses to emit it). Upload-time ingestion now
    rejects such scores outright (see test_upload_real_scores.py), so this
    should not be reachable via a normal edit — but the harness must still
    fail safely, as a structured EXPORT_FAILED error, rather than letting
    an unexpected write-time exception crash the caller. Simulated here
    with a mocked `Score.write` rather than a real unexportable score so
    the test stays fast and independent of any specific corpus content.
    """
    sid = make_score("simple_4_4")
    before = storage.read_xml(sid)

    with patch.object(m21.stream.Score, "write", side_effect=RuntimeError("boom")):
        result = tools.add_dynamic(sid, measure=1, beat=1, dynamic="f")

    err = assert_error(result, ErrorCode.EXPORT_FAILED)
    assert "boom" in err["message"]
    # Nothing was actually written to disk.
    assert storage.read_xml(sid) == before


def test_music21_drops_chord_level_ids_so_assign_id_falls_back():
    """Regression documentation for the chord fallback: music21's MusicXML
    writer ignores an id set on the Chord object itself (each exported
    <note> takes its id from the per-pitch Note in `chord.notes`), so
    assign_id must target the chord's first inner note instead.
    """
    def render(chord_obj) -> str:
        score = m21.stream.Score()
        part = m21.stream.Part()
        part.id = "P1"
        measure = m21.stream.Measure(number=1)
        measure.timeSignature = m21.meter.TimeSignature("4/4")
        measure.append(chord_obj)
        part.append(measure)
        score.append(part)
        return m21.musicxml.m21ToXml.GeneralObjectExporter(score).parse().decode("utf-8")

    # Setting the id directly on the Chord: dropped by the exporter.
    dropped = m21.chord.Chord(["C4", "E4", "G4"], quarterLength=1)
    dropped.id = "nota-on-chord"
    assert 'id="nota-on-chord"' not in render(dropped)

    # assign_id routes the id to the first inner note, which survives.
    kept = m21.chord.Chord(["C4", "E4", "G4"], quarterLength=1)
    new_id = ids.assign_id(kept)
    assert new_id.startswith("nota-")
    assert f'id="{new_id}"' in render(kept)


def test_grace_note_ids_survive_serialization(make_score):
    """Grace notes are regular Note objects with a grace duration; their
    ids must survive export like any other note's (range mode reports them).
    """
    sid = make_score("grace_notes")
    result = tools.add_articulation(
        sid, measure=1, beat=1, articulation="staccato", end_measure=1, end_beat=4
    )
    assert result["success"] is True
    xml = storage.read_xml(sid)
    for element_id in result["changed_element_ids"]:
        assert f'id="{element_id}"' in xml


def test_pickup_beat_in_missing_span_is_out_of_range(make_score):
    sid = make_score("pickup")
    # The pickup holds only the final quarter of a 4/4 bar; beats 1-3
    # fall in the missing opening span and must be rejected.
    result = tools.add_articulation(sid, measure=0, beat=1, articulation="staccato")
    err = assert_error(result, ErrorCode.BEAT_OUT_OF_RANGE)
    assert "pickup" in err["message"]
    assert "beat 4" in err["message"]  # states where the pickup actually begins


def test_pickup_beat_resolution_targets_real_note(make_score):
    sid = make_score("pickup")
    result = tools.add_articulation(sid, measure=0, beat=4, articulation="staccato")
    assert result["success"] is True

    reparsed = m21.converter.parse(storage.read_xml(sid).encode("utf-8"), format="musicxml")
    marked = [
        n
        for n in reparsed.recurse().notes
        if any(isinstance(a, m21.articulations.Staccato) for a in n.articulations)
    ]
    assert len(marked) == 1
    assert marked[0].measureNumber == 0


def test_touch_modified_updated_after_mutation(make_score):
    from nota import db as db_module
    from nota import models

    sid = make_score("simple_4_4")
    with db_module.session_scope() as session:
        before = session.get(models.Score, sid).last_modified_at

    tools.add_dynamic(sid, measure=1, beat=1, dynamic="f")

    with db_module.session_scope() as session:
        after = session.get(models.Score, sid).last_modified_at
    assert after > before


def test_stateless_across_calls_no_shared_document(make_score):
    """Two consecutive calls must both land in the file: the second call
    re-parses from disk and sees the first call's musical content.
    """
    sid = make_score("simple_4_4")
    first = tools.add_dynamic(sid, measure=1, beat=1, dynamic="f")
    assert first["success"]
    assert f'id="{first["changed_element_ids"][0]}"' in storage.read_xml(sid)

    second = tools.add_dynamic(sid, measure=2, beat=1, dynamic="p")
    assert second["success"]

    xml = storage.read_xml(sid)
    assert f'id="{second["changed_element_ids"][0]}"' in xml
    reparsed = m21.converter.parse(xml.encode("utf-8"), format="musicxml")
    dynamics = list(reparsed.recurse().getElementsByClass(m21.dynamics.Dynamic))
    assert sorted(d.value for d in dynamics) == ["f", "p"]


def test_ids_are_valid_until_the_next_mutation(make_score):
    """music21 does not read xml:id back into an element's `.id` on parse,
    so a *subsequent* tool call's re-serialization drops ids minted by
    earlier calls. The highlighting contract is therefore: the ids a call
    returns are guaranteed present in the XML written by that call, and
    remain valid only until the next mutation. This test pins that
    behavior down so a change in music21 (starting to preserve xml:id
    across round trips) is noticed.
    """
    sid = make_score("simple_4_4")
    first = tools.add_dynamic(sid, measure=1, beat=1, dynamic="f")
    tools.add_dynamic(sid, measure=2, beat=1, dynamic="p")

    xml = storage.read_xml(sid)
    assert f'id="{first["changed_element_ids"][0]}"' not in xml
