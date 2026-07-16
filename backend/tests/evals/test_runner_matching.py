"""Runs the full eval runner machinery (`evals.run_evals.run_case`) against
a scripted fake Anthropic client and a direct-dispatch tool backend -- no
subprocess, no API key, no real score storage beyond the temp dir the
`app` fixture already sets up.

Each test proves one piece of the matching logic in `evals/scoring.py` by
controlling exactly what the "LLM" does and checking the resulting
`CaseResult.passed`/`detail`: exact match, an args-subset mismatch,
the ranged-vs-per-note distinction, no_tools pass/fail, any_of, and
setup_transcripts context flow.
"""

from __future__ import annotations

import pytest

from evals import run_evals
from evals.dataset import case as make_case
from evals.dataset import expect_any_of, expect_no_tools, expect_tools, tc
from evals.dispatcher import DirectToolDispatcher, RecordingDispatcher
from nota.orchestrator import loop
from tests.orchestrator.fakes import FakeAnthropicClient, fake_response, text_block, tool_use_block


@pytest.fixture
def eval_cfg(app):
    """The `app` fixture (top-level tests/conftest.py) already configures
    storage/db against a temp DB and score directory via `create_app` ->
    `storage.configure`; hand back its Config so `evals.fixture` functions
    can register scores against that same isolated storage.
    """
    return app.config["NOTA_CONFIG"]


@pytest.fixture
def dispatcher(monkeypatch):
    """A RecordingDispatcher wrapping direct tool-function dispatch (no MCP
    subprocess), installed as the loop's dispatcher for the duration of
    one test.
    """
    recording = RecordingDispatcher(DirectToolDispatcher())
    monkeypatch.setattr(loop, "_get_dispatcher", lambda: recording)
    return recording


def _install_client(monkeypatch, responses):
    fake = FakeAnthropicClient(responses)
    monkeypatch.setattr(loop, "_get_client", lambda: fake)
    return fake


def test_exact_match_passes(app, eval_cfg, dispatcher, monkeypatch):
    _install_client(
        monkeypatch,
        [
            fake_response(tool_use_block("1", "add_dynamic", {"measure": 3, "beat": 1, "dynamic": "f"})),
            fake_response(text_block("Added forte at measure 3.")),
        ],
    )
    dataset_case = make_case(
        "t_exact",
        "simple",
        "forte at measure 3 beat 1",
        expect_tools(tc("add_dynamic", measure=3, beat=1, dynamic="f")),
    )

    result = run_evals.run_case(dataset_case, dispatcher, eval_cfg)

    assert result.passed, result.detail
    assert len(result.actual_calls) == 1
    assert result.actual_calls[0]["tool"] == "add_dynamic"
    # The recorded args also carry the score_id the loop injects -- args
    # are matched as a subset, so extra keys like this are expected here.
    assert result.actual_calls[0]["args"]["measure"] == 3
    assert result.actual_calls[0]["args"]["beat"] == 1
    assert result.actual_calls[0]["args"]["dynamic"] == "f"


def test_args_subset_mismatch_fails(app, eval_cfg, dispatcher, monkeypatch):
    _install_client(
        monkeypatch,
        [
            fake_response(tool_use_block("1", "add_dynamic", {"measure": 3, "beat": 1, "dynamic": "p"})),
            fake_response(text_block("Added piano at measure 3.")),
        ],
    )
    dataset_case = make_case(
        "t_mismatch",
        "simple",
        "forte at measure 3 beat 1",
        expect_tools(tc("add_dynamic", measure=3, beat=1, dynamic="f")),
    )

    result = run_evals.run_case(dataset_case, dispatcher, eval_cfg)

    assert not result.passed
    assert "no assignment" in result.detail


def test_extra_unexpected_tool_call_fails(app, eval_cfg, dispatcher, monkeypatch):
    """A correct call plus a spurious extra call must fail, not partially
    pass -- exact count match is part of the contract.
    """
    _install_client(
        monkeypatch,
        [
            fake_response(
                tool_use_block("1", "add_dynamic", {"measure": 3, "beat": 1, "dynamic": "f"}),
                tool_use_block("2", "add_dynamic", {"measure": 4, "beat": 1, "dynamic": "p"}),
            ),
            fake_response(text_block("Done.")),
        ],
    )
    dataset_case = make_case(
        "t_extra_call",
        "simple",
        "forte at measure 3 beat 1",
        expect_tools(tc("add_dynamic", measure=3, beat=1, dynamic="f")),
    )

    result = run_evals.run_case(dataset_case, dispatcher, eval_cfg)

    assert not result.passed
    assert "expected 1 tool call" in result.detail


def test_ranged_call_beats_per_note_calls(app, eval_cfg, dispatcher, monkeypatch):
    """A range command ('every note in measure 8') must be scored as a
    single ranged add_articulation call, not one call per note -- three
    separate per-note calls should fail the range expectation even though
    each individual call is a legitimate staccato within range.
    """
    _install_client(
        monkeypatch,
        [
            fake_response(
                tool_use_block("1", "add_articulation", {"measure": 8, "beat": 1, "articulation": "staccato"}),
                tool_use_block("2", "add_articulation", {"measure": 8, "beat": 2, "articulation": "staccato"}),
                tool_use_block("3", "add_articulation", {"measure": 8, "beat": 3, "articulation": "staccato"}),
            ),
            fake_response(text_block("Added staccato to three notes.")),
        ],
    )
    dataset_case = make_case(
        "t_range_per_note",
        "ranges",
        "staccato on every note in measure 8",
        expect_tools(
            tc("add_articulation", measure=8, beat=1, end_measure=8, end_beat=4, articulation="staccato")
        ),
    )

    result = run_evals.run_case(dataset_case, dispatcher, eval_cfg)

    assert not result.passed
    assert "expected 1 tool call" in result.detail


def test_ranged_call_matches_when_a_single_ranged_call_is_made(app, eval_cfg, dispatcher, monkeypatch):
    _install_client(
        monkeypatch,
        [
            fake_response(
                tool_use_block(
                    "1",
                    "add_articulation",
                    {"measure": 8, "beat": 1, "end_measure": 8, "end_beat": 4, "articulation": "staccato"},
                )
            ),
            fake_response(text_block("Added staccato across measure 8.")),
        ],
    )
    dataset_case = make_case(
        "t_range_ok",
        "ranges",
        "staccato on every note in measure 8",
        expect_tools(tc("add_articulation", measure=8, beat=1, end_measure=8, articulation="staccato")),
    )

    result = run_evals.run_case(dataset_case, dispatcher, eval_cfg)

    assert result.passed, result.detail


def test_no_tools_passes_on_clarifying_response(app, eval_cfg, dispatcher, monkeypatch):
    _install_client(monkeypatch, [fake_response(text_block("Which measure did you mean?"))])
    dataset_case = make_case("t_no_tools_ok", "ambiguous", "make it louder", expect_no_tools())

    result = run_evals.run_case(dataset_case, dispatcher, eval_cfg)

    assert result.passed, result.detail


def test_no_tools_fails_when_a_tool_was_called(app, eval_cfg, dispatcher, monkeypatch):
    _install_client(
        monkeypatch,
        [
            fake_response(tool_use_block("1", "add_dynamic", {"measure": 1, "beat": 1, "dynamic": "f"})),
            fake_response(text_block("Added forte.")),
        ],
    )
    dataset_case = make_case("t_no_tools_fail", "ambiguous", "make it louder", expect_no_tools())

    result = run_evals.run_case(dataset_case, dispatcher, eval_cfg)

    assert not result.passed
    assert "expected no tool calls" in result.detail


def test_no_tools_fails_without_a_text_response(app, eval_cfg, dispatcher, monkeypatch):
    """no_tools additionally requires a non-empty confirmation/clarifying
    text -- silently doing nothing is not the same as asking a question.
    """
    _install_client(monkeypatch, [fake_response()])
    dataset_case = make_case("t_no_tools_silent", "ambiguous", "make it louder", expect_no_tools())

    result = run_evals.run_case(dataset_case, dispatcher, eval_cfg)

    assert not result.passed
    assert "clarifying question" in result.detail


def test_any_of_passes_on_the_second_alternative(app, eval_cfg, dispatcher, monkeypatch):
    _install_client(
        monkeypatch,
        [
            fake_response(
                tool_use_block(
                    "1",
                    "draw_hairpin",
                    {
                        "start_measure": 5,
                        "start_beat": 1,
                        "end_measure": 6,
                        "end_beat": 1,
                        "direction": "diminuendo",
                    },
                )
            ),
            fake_response(text_block("Added a diminuendo.")),
        ],
    )
    dataset_case = make_case(
        "t_any_of",
        "synonyms",
        "dim from measure 5 beat 1 to measure 6 beat 1",
        expect_any_of(
            expect_tools(
                tc("draw_hairpin", start_measure=5, start_beat=1, end_measure=6, end_beat=1, direction="decrescendo")
            ),
            expect_tools(
                tc("draw_hairpin", start_measure=5, start_beat=1, end_measure=6, end_beat=1, direction="diminuendo")
            ),
        ),
    )

    result = run_evals.run_case(dataset_case, dispatcher, eval_cfg)

    assert result.passed, result.detail


def test_any_of_fails_when_no_alternative_matches(app, eval_cfg, dispatcher, monkeypatch):
    _install_client(
        monkeypatch,
        [
            fake_response(tool_use_block("1", "add_dynamic", {"measure": 1, "beat": 1, "dynamic": "f"})),
            fake_response(text_block("Added forte.")),
        ],
    )
    dataset_case = make_case(
        "t_any_of_fail",
        "synonyms",
        "dim from measure 5 beat 1 to measure 6 beat 1",
        expect_any_of(
            expect_tools(
                tc("draw_hairpin", start_measure=5, start_beat=1, end_measure=6, end_beat=1, direction="decrescendo")
            ),
            expect_tools(
                tc("draw_hairpin", start_measure=5, start_beat=1, end_measure=6, end_beat=1, direction="diminuendo")
            ),
        ),
    )

    result = run_evals.run_case(dataset_case, dispatcher, eval_cfg)

    assert not result.passed
    assert "no alternative matched" in result.detail


def test_setup_transcripts_build_context_and_are_excluded_from_scoring(app, eval_cfg, dispatcher, monkeypatch):
    """setup_transcripts run through the same score/CommandLog first; only
    the scored transcript's own tool calls should be recorded against the
    case, even though the dispatcher's call log is shared across both.
    """
    _install_client(
        monkeypatch,
        [
            # setup_transcripts[0]: "forte at measure 2 beat 1"
            fake_response(tool_use_block("s1", "add_dynamic", {"measure": 2, "beat": 1, "dynamic": "f"})),
            fake_response(text_block("Added forte at measure 2.")),
            # scored transcript: "same thing at measure 15"
            fake_response(tool_use_block("m1", "add_dynamic", {"measure": 15, "beat": 1, "dynamic": "f"})),
            fake_response(text_block("Added forte at measure 15.")),
        ],
    )
    dataset_case = make_case(
        "t_context",
        "context_carryover",
        "same thing at measure 15",
        expect_tools(tc("add_dynamic", measure=15, beat=1, dynamic="f")),
        setup_transcripts=["forte at measure 2 beat 1"],
    )

    result = run_evals.run_case(dataset_case, dispatcher, eval_cfg)

    assert result.passed, result.detail
    assert len(result.actual_calls) == 1
    assert result.actual_calls[0]["args"]["measure"] == 15
    # The dispatcher itself did see both calls -- proves setup actually ran
    # through the real orchestrator/tool layer, not just the scored one.
    assert [name for name, _ in dispatcher.calls] == ["add_dynamic", "add_dynamic"]
