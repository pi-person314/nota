"""Tests for the Claude agentic loop (`nota.orchestrator.loop.run_command`).

The Anthropic client is always a scripted fake (`fakes.FakeAnthropicClient`);
tool execution goes through `fakes.DirectDispatchDispatcher`, which calls
the real notation tool functions directly (bypassing the MCP subprocess),
so mutations, snapshots, and error codes are all real.
"""

from __future__ import annotations

import httpx
import pytest
from anthropic import APIStatusError, APITimeoutError

from nota.orchestrator import loop

from .fakes import fake_response, text_block, tool_use_block


def _dummy_request() -> httpx.Request:
    return httpx.Request("POST", "https://api.anthropic.com/v1/messages")


def test_single_tool_call_produces_confirmation(make_score, install_fake_client, install_direct_dispatcher):
    score_id = make_score()
    dispatcher = install_direct_dispatcher()
    install_fake_client(
        [
            fake_response(tool_use_block("toolu_1", "add_dynamic", {"measure": 1, "beat": 1, "dynamic": "f"})),
            fake_response(text_block("Added forte at measure 1.")),
        ]
    )

    result = loop.run_command(score_id, "add forte at measure one")

    assert result["tools_called"] == ["add_dynamic"]
    assert result["changed_element_ids"]
    assert result["confirmation"] == "Added forte at measure 1."
    assert result["needs_clarification"] is False
    assert "error" not in result
    assert dispatcher.calls[0][0] == "add_dynamic"
    # score_id is injected into every tool call's arguments.
    assert dispatcher.calls[0][1]["score_id"] == score_id


def test_compound_command_executes_both_tools_in_one_user_message(
    make_score, install_fake_client, install_direct_dispatcher
):
    score_id = make_score()
    dispatcher = install_direct_dispatcher()
    fake_client = install_fake_client(
        [
            fake_response(
                tool_use_block("toolu_1", "add_dynamic", {"measure": 1, "beat": 1, "dynamic": "f"}),
                tool_use_block(
                    "toolu_2",
                    "add_articulation",
                    {"measure": 2, "beat": 1, "articulation": "staccato"},
                ),
            ),
            fake_response(text_block("Added forte and staccato.")),
        ]
    )

    result = loop.run_command(score_id, "add forte at measure one and staccato at measure two")

    assert result["tools_called"] == ["add_dynamic", "add_articulation"]
    assert len(dispatcher.calls) == 2
    assert len(result["changed_element_ids"]) == 2

    # Both tool_use blocks from the first response must be answered in a
    # single subsequent user message (not split across two messages).
    second_call_messages = fake_client.messages.calls[1]["messages"]
    tool_result_messages = [
        m for m in second_call_messages if m["role"] == "user" and isinstance(m["content"], list)
    ]
    assert len(tool_result_messages) == 1
    assert len(tool_result_messages[0]["content"]) == 2
    ids_in_result = {block["tool_use_id"] for block in tool_result_messages[0]["content"]}
    assert ids_in_result == {"toolu_1", "toolu_2"}


def test_chained_self_correction_retries_after_tool_error(
    make_score, install_fake_client, install_direct_dispatcher
):
    score_id = make_score()
    dispatcher = install_direct_dispatcher()
    install_fake_client(
        [
            # Unknown dynamic -> INVALID_ENUM_VALUE tool error.
            fake_response(tool_use_block("toolu_1", "add_dynamic", {"measure": 1, "beat": 1, "dynamic": "xyz"})),
            # Model corrects itself after seeing the error.
            fake_response(tool_use_block("toolu_2", "add_dynamic", {"measure": 1, "beat": 1, "dynamic": "f"})),
            fake_response(text_block("Added forte at measure 1.")),
        ]
    )

    result = loop.run_command(score_id, "add a weird dynamic then fix it")

    assert result["tools_called"] == ["add_dynamic", "add_dynamic"]
    assert len(dispatcher.calls) == 2
    # Only the second (successful) call contributes a changed id.
    assert len(result["changed_element_ids"]) == 1
    assert result["confirmation"] == "Added forte at measure 1."
    assert "error" not in result


def test_iteration_cap_stops_at_eight(make_score, install_fake_client, install_direct_dispatcher):
    score_id = make_score()
    install_direct_dispatcher()
    # Script more than 8 tool-call responses; the loop must never consume
    # more than MAX_ITERATIONS (8) of them.
    scripted = [
        fake_response(tool_use_block(f"toolu_{i}", "add_dynamic", {"measure": 1, "beat": 1, "dynamic": "f"}))
        for i in range(10)
    ]
    fake_client = install_fake_client(scripted)

    result = loop.run_command(score_id, "keep adding dynamics forever")

    assert len(fake_client.messages.calls) == loop.MAX_ITERATIONS
    assert len(result["tools_called"]) == loop.MAX_ITERATIONS
    assert result["needs_clarification"] is False


def test_no_tool_call_is_a_clarification(make_score, install_fake_client, install_direct_dispatcher):
    score_id = make_score()
    install_direct_dispatcher()
    install_fake_client([fake_response(text_block("Which measure did you mean?"))])

    result = loop.run_command(score_id, "add a forte there")

    assert result["tools_called"] == []
    assert result["changed_element_ids"] == []
    assert result["confirmation"] == "Which measure did you mean?"
    assert result["needs_clarification"] is True
    assert "error" not in result


def test_llm_timeout_mid_loop_keeps_prior_tool_effects(
    make_score, install_fake_client, install_direct_dispatcher, read_score_xml
):
    score_id = make_score()
    dispatcher = install_direct_dispatcher()
    install_fake_client(
        [
            fake_response(tool_use_block("toolu_1", "add_dynamic", {"measure": 1, "beat": 1, "dynamic": "f"})),
            APITimeoutError(request=_dummy_request()),
        ]
    )

    result = loop.run_command(score_id, "add forte then something breaks")

    assert result["error"] == "LLM_TIMEOUT"
    assert result["tools_called"] == ["add_dynamic"]
    assert result["changed_element_ids"]
    # The mutation actually landed on disk -- it survives the LLM failure.
    assert 'id="' + result["changed_element_ids"][0] + '"' in read_score_xml(score_id)
    assert len(dispatcher.calls) == 1


def test_llm_api_status_error_mid_loop_is_llm_error(make_score, install_fake_client, install_direct_dispatcher):
    score_id = make_score()
    install_direct_dispatcher()
    response = httpx.Response(500, request=_dummy_request(), json={"error": {"message": "boom"}})
    install_fake_client([APIStatusError("boom", response=response, body={"error": {"message": "boom"}})])

    result = loop.run_command(score_id, "add forte")

    assert result["error"] == "LLM_ERROR"
    assert result["tools_called"] == []


@pytest.fixture
def read_score_xml(app):
    from nota import storage

    def _read(score_id: str) -> str:
        return storage.read_xml(score_id)

    return _read
