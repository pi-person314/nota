"""Tests for the MCP stdio server wrapper: tool registration, schemas, and
end-to-end calls through an in-memory MCP client session (no subprocess).
"""

from __future__ import annotations

import asyncio
import json

import mcp.types as mcp_types
from mcp.shared.memory import create_connected_server_and_client_session

from nota.mcp_server.server import mcp as mcp_server

EXPECTED_TOOLS = {"add_dynamic", "draw_slur", "add_articulation"}


def _run(coro):
    return asyncio.run(coro)


async def _list_tools():
    async with create_connected_server_and_client_session(
        mcp_server._mcp_server, raise_exceptions=True
    ) as client:
        result = await client.list_tools()
        return result.tools


async def _call_tool(name: str, arguments: dict):
    async with create_connected_server_and_client_session(
        mcp_server._mcp_server, raise_exceptions=True
    ) as client:
        return await client.call_tool(name, arguments)


def _payload(call_result) -> dict:
    """Extract the structured tool result dict from an MCP CallToolResult."""
    if call_result.structuredContent is not None:
        payload = call_result.structuredContent
        # FastMCP wraps plain dict returns under a 'result' key in some
        # versions; unwrap if so.
        if set(payload) == {"result"}:
            payload = payload["result"]
        return payload
    text_blocks = [c for c in call_result.content if isinstance(c, mcp_types.TextContent)]
    assert text_blocks, "tool returned no content"
    return json.loads(text_blocks[0].text)


def test_all_three_tools_registered():
    tools_list = _run(_list_tools())
    names = {t.name for t in tools_list}
    assert EXPECTED_TOOLS <= names


def test_every_tool_requires_score_id():
    tools_list = _run(_list_tools())
    for tool in tools_list:
        if tool.name not in EXPECTED_TOOLS:
            continue
        schema = tool.inputSchema
        assert "score_id" in schema["properties"], tool.name
        assert "score_id" in schema.get("required", []), tool.name


def test_tool_descriptions_are_llm_usable():
    """Each tool and its non-obvious parameters carry descriptions an LLM
    can act on (beat semantics, range mode, dedupe behavior).
    """
    tools_list = _run(_list_tools())
    by_name = {t.name: t for t in tools_list}

    for name in EXPECTED_TOOLS:
        assert by_name[name].description, name

    assert "no-op" in by_name["add_dynamic"].description
    assert "range" in by_name["add_articulation"].description.lower()

    articulation_props = by_name["add_articulation"].inputSchema["properties"]
    assert "end_measure" in articulation_props
    assert "end_beat" in articulation_props
    assert "required" not in by_name["add_articulation"].inputSchema or (
        "end_measure" not in by_name["add_articulation"].inputSchema["required"]
    )


def test_call_add_dynamic_through_mcp(make_score, read_score_xml):
    sid = make_score("simple_4_4")
    result = _run(
        _call_tool("add_dynamic", {"score_id": sid, "measure": 1, "beat": 1, "dynamic": "f"})
    )
    payload = _payload(result)
    assert payload["success"] is True
    assert len(payload["changed_element_ids"]) == 1
    assert f'id="{payload["changed_element_ids"][0]}"' in read_score_xml(sid)


def test_call_draw_slur_through_mcp(make_score, read_score_xml):
    sid = make_score("simple_4_4")
    result = _run(
        _call_tool(
            "draw_slur",
            {
                "score_id": sid,
                "start_measure": 1,
                "start_beat": 1,
                "end_measure": 1,
                "end_beat": 4,
            },
        )
    )
    payload = _payload(result)
    assert payload["success"] is True
    assert len(payload["changed_element_ids"]) == 2


def test_call_add_articulation_range_through_mcp(make_score):
    sid = make_score("simple_4_4")
    result = _run(
        _call_tool(
            "add_articulation",
            {
                "score_id": sid,
                "measure": 1,
                "beat": 1,
                "articulation": "staccato",
                "end_measure": 2,
                "end_beat": 4,
            },
        )
    )
    payload = _payload(result)
    assert payload["success"] is True
    assert len(payload["changed_element_ids"]) == 8


def test_error_results_pass_through_mcp_unchanged(storage_env):
    result = _run(
        _call_tool(
            "add_dynamic",
            {"score_id": "does-not-exist", "measure": 1, "beat": 1, "dynamic": "f"},
        )
    )
    payload = _payload(result)
    assert payload["success"] is False
    assert payload["error_code"] == "SCORE_NOT_FOUND"
