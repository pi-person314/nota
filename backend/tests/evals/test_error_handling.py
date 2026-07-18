"""Tests for how the eval runner (`evals.run_evals`) reports orchestrator/
LLM errors -- a timed-out or failed Claude API call must never be
indistinguishable from the model genuinely getting a case wrong.

Same no-subprocess, no-API-key harness as `test_runner_matching.py`: a
scripted `FakeAnthropicClient` stands in for the real Anthropic client, and
tool calls go through a `RecordingDispatcher` wrapping `DirectToolDispatcher`
(direct in-process calls to `nota.mcp_server.tools`, bypassing MCP).
"""

from __future__ import annotations

import json

import httpx
import pytest
from anthropic import APIStatusError, APITimeoutError

from evals import run_evals
from evals.dataset import case as make_case
from evals.dataset import expect_tools, tc
from evals.dispatcher import DirectToolDispatcher, RecordingDispatcher
from nota.orchestrator import loop
from tests.orchestrator.fakes import FakeAnthropicClient, fake_response, text_block, tool_use_block


def _dummy_request() -> httpx.Request:
    return httpx.Request("POST", "https://api.anthropic.com/v1/messages")


@pytest.fixture
def eval_cfg(app):
    """See `test_runner_matching.py`: the `app` fixture already configures
    storage/db against a temp DB and score directory; hand back its Config
    so `evals.fixture` functions can register scores against that same
    isolated storage.
    """
    return app.config["NOTA_CONFIG"]


@pytest.fixture
def dispatcher(monkeypatch):
    recording = RecordingDispatcher(DirectToolDispatcher())
    monkeypatch.setattr(loop, "_get_dispatcher", lambda: recording)
    return recording


def _install_client(monkeypatch, responses):
    fake = FakeAnthropicClient(responses)
    monkeypatch.setattr(loop, "_get_client", lambda: fake)
    return fake


def test_llm_timeout_is_carried_into_case_result(app, eval_cfg, dispatcher, monkeypatch):
    _install_client(monkeypatch, [APITimeoutError(request=_dummy_request())])
    dataset_case = make_case(
        "t_timeout",
        "simple",
        "forte at measure 3 beat 1",
        expect_tools(tc("add_dynamic", measure=3, beat=1, dynamic="f")),
    )

    result = run_evals.run_case(dataset_case, dispatcher, eval_cfg)

    assert result.error == "LLM_TIMEOUT"
    # An errored case must never read as a pass, even though it also isn't
    # the kind of failure the detail/expected/actual_calls fields describe.
    assert result.passed is False
    assert "LLM_TIMEOUT" in result.detail
    assert result.actual_calls == []


def test_llm_api_error_is_carried_into_case_result(app, eval_cfg, dispatcher, monkeypatch):
    response = httpx.Response(500, request=_dummy_request())
    _install_client(
        monkeypatch,
        [APIStatusError("boom", response=response, body={"error": {"message": "boom"}})],
    )
    dataset_case = make_case(
        "t_api_error",
        "simple",
        "forte at measure 3 beat 1",
        expect_tools(tc("add_dynamic", measure=3, beat=1, dynamic="f")),
    )

    result = run_evals.run_case(dataset_case, dispatcher, eval_cfg)

    assert result.error == "LLM_ERROR"
    assert result.passed is False


def test_errored_case_is_not_scored_against_an_expectation_it_would_otherwise_pass(
    app, eval_cfg, dispatcher, monkeypatch
):
    """Regression test for the exact blind spot this fix closes: a
    no-tool-calls expectation with no clarification requirement would
    "pass" on an empty response even when that emptiness came from an API
    outage, not the model correctly doing nothing. The error must win.
    """
    _install_client(monkeypatch, [APITimeoutError(request=_dummy_request())])
    dataset_case = make_case(
        "t_timeout_would_have_passed",
        "ambiguous",
        "make it louder",
        {"no_tools": True, "expect_clarification_or_correction": False},
    )

    result = run_evals.run_case(dataset_case, dispatcher, eval_cfg)

    assert result.error == "LLM_TIMEOUT"
    assert result.passed is False
    assert run_evals.case_outcome(result) == "errored"


def test_case_outcome_classifies_all_three_buckets():
    passed = run_evals.CaseResult(
        id="p", category="c", transcript="t", passed=True, detail="",
        expected={}, actual_calls=[], confirmation="ok", needs_clarification=False,
    )
    failed = run_evals.CaseResult(
        id="f", category="c", transcript="t", passed=False, detail="wrong args",
        expected={}, actual_calls=[], confirmation="", needs_clarification=False,
    )
    errored = run_evals.CaseResult(
        id="e", category="c", transcript="t", passed=False, detail="orchestrator/LLM error before scoring: LLM_TIMEOUT",
        expected={}, actual_calls=[], confirmation="", needs_clarification=False, error="LLM_TIMEOUT",
    )

    assert run_evals.case_outcome(passed) == "passed"
    assert run_evals.case_outcome(failed) == "failed"
    assert run_evals.case_outcome(errored) == "errored"


def test_run_suite_reports_mixed_pass_fail_error_counts(app, eval_cfg, dispatcher, monkeypatch):
    _install_client(
        monkeypatch,
        [
            # case 1: passes.
            fake_response(tool_use_block("1", "add_dynamic", {"measure": 3, "beat": 1, "dynamic": "f"})),
            fake_response(text_block("Added forte at measure 3.")),
            # case 2: fails (wrong dynamic).
            fake_response(tool_use_block("2", "add_dynamic", {"measure": 3, "beat": 1, "dynamic": "p"})),
            fake_response(text_block("Added piano at measure 3.")),
            # case 3: errors out.
            APITimeoutError(request=_dummy_request()),
            # case 4: errors out with a different code.
            APIStatusError(
                "boom",
                response=httpx.Response(500, request=_dummy_request()),
                body={"error": {"message": "boom"}},
            ),
        ],
    )
    cases = [
        make_case(
            "s_pass", "simple", "forte at measure 3 beat 1",
            expect_tools(tc("add_dynamic", measure=3, beat=1, dynamic="f")),
        ),
        make_case(
            "s_fail", "simple", "forte at measure 3 beat 1",
            expect_tools(tc("add_dynamic", measure=3, beat=1, dynamic="f")),
        ),
        make_case(
            "s_timeout", "simple", "forte at measure 3 beat 1",
            expect_tools(tc("add_dynamic", measure=3, beat=1, dynamic="f")),
        ),
        make_case(
            "s_api_error", "simple", "forte at measure 3 beat 1",
            expect_tools(tc("add_dynamic", measure=3, beat=1, dynamic="f")),
        ),
    ]

    report = run_evals.run_suite(cases, dispatcher, eval_cfg)

    assert report.total == 4
    assert report.passed == 1
    assert report.failed == 1
    assert report.errored == 2
    assert report.error_counts == {"LLM_TIMEOUT": 1, "LLM_ERROR": 1}
    assert report.by_category["simple"] == {"total": 4, "passed": 1, "failed": 1, "errored": 2}

    # The exit/status convention: any errored case forces exit code 3,
    # regardless of how many other cases passed or failed.
    assert run_evals.exit_code_for(report) == 3

    # The JSON report round-trips the same additive fields the console
    # summary reads, including per-case error strings.
    from dataclasses import asdict

    payload = json.loads(json.dumps(asdict(report)))
    assert payload["errored"] == 2
    assert payload["error_counts"] == {"LLM_TIMEOUT": 1, "LLM_ERROR": 1}
    result_errors = {r["id"]: r["error"] for r in payload["results"]}
    assert result_errors["s_timeout"] == "LLM_TIMEOUT"
    assert result_errors["s_api_error"] == "LLM_ERROR"
    assert result_errors["s_pass"] is None
    assert result_errors["s_fail"] is None


def test_exit_code_for_clean_pass_is_zero():
    report = run_evals.SuiteReport(
        generated_at="now", total=2, passed=2, failed=0, errored=0,
        error_counts={}, by_category={}, results=[],
    )
    assert run_evals.exit_code_for(report) == 0


def test_exit_code_for_failures_without_errors_is_one():
    report = run_evals.SuiteReport(
        generated_at="now", total=2, passed=1, failed=1, errored=0,
        error_counts={}, by_category={}, results=[],
    )
    assert run_evals.exit_code_for(report) == 1


def test_exit_code_for_any_errored_case_is_three_even_with_only_passes_otherwise():
    report = run_evals.SuiteReport(
        generated_at="now", total=2, passed=1, failed=0, errored=1,
        error_counts={"LLM_TIMEOUT": 1}, by_category={}, results=[],
    )
    assert run_evals.exit_code_for(report) == 3
