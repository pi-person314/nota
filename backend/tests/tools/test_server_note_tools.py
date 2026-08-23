"""MCP-layer tests for the note-editing tools (change_pitch, transpose,
add_note, set_duration, delete_note): registration, schemas, and a couple
of end-to-end calls through an in-memory MCP client session, in the same
style as test_server_new_tools.py.
"""

from __future__ import annotations

import asyncio
import json

import mcp.types as mcp_types
from mcp.shared.memory import create_connected_server_and_client_session

from nota.mcp_server.server import mcp as mcp_server

NOTE_TOOLS = {
    "change_pitch",
    "transpose",
    "add_note",
    "set_duration",
    "delete_note",
}


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
    if call_result.structuredContent is not None:
        payload = call_result.structuredContent
        if set(payload) == {"result"}:
            payload = payload["result"]
        return payload
    text_blocks = [c for c in call_result.content if isinstance(c, mcp_types.TextContent)]
    assert text_blocks, "tool returned no content"
    return json.loads(text_blocks[0].text)


def test_all_note_tools_registered():
    tools_list = _run(_list_tools())
    names = {t.name for t in tools_list}
    assert NOTE_TOOLS <= names


def test_every_note_tool_requires_score_id():
    tools_list = _run(_list_tools())
    for tool in tools_list:
        if tool.name not in NOTE_TOOLS:
            continue
        schema = tool.inputSchema
        assert "score_id" in schema["properties"], tool.name
        assert "score_id" in schema.get("required", []), tool.name


def test_note_tool_schemas_are_llm_usable():
    tools_list = _run(_list_tools())
    by_name = {t.name: t for t in tools_list}

    for name in NOTE_TOOLS:
        assert by_name[name].description, name

    # The optional targeting/range arguments must not be schema-required.
    change_pitch_schema = by_name["change_pitch"].inputSchema
    required = change_pitch_schema.get("required", [])
    assert "beat" not in required
    assert "from_pitch" not in required

    delete_schema = by_name["delete_note"].inputSchema
    required = delete_schema.get("required", [])
    for optional in ("beat", "end_measure", "end_beat"):
        assert optional in delete_schema["properties"]
        assert optional not in required

    # Duration vocabulary is spelled out where the model has to pick one.
    for name in ("add_note", "set_duration"):
        duration_desc = by_name[name].inputSchema["properties"]["duration"]["description"]
        assert "dotted_quarter" in duration_desc

    interval_desc = by_name["transpose"].inputSchema["properties"]["interval"]["description"]
    assert "perfect_fifth" in interval_desc


def test_call_add_note_then_change_pitch_through_mcp(make_score, read_score_xml):
    sid = make_score("simple_4_4")

    add_result = _payload(
        _run(
            _call_tool(
                "add_note",
                {"score_id": sid, "measure": 1, "beat": 1, "pitch": "C5", "duration": "quarter"},
            )
        )
    )
    assert add_result["success"] is True
    assert len(add_result["changed_element_ids"]) == 1
    xml = read_score_xml(sid)
    assert f'id="{add_result["changed_element_ids"][0]}"' in xml

    change_result = _payload(
        _run(
            _call_tool(
                "change_pitch",
                {"score_id": sid, "measure": 1, "beat": 1, "pitch": "D5"},
            )
        )
    )
    assert change_result["success"] is True
    assert "D5" in change_result["summary"]


def test_call_delete_note_through_mcp(make_score, read_score_xml):
    sid = make_score("simple_4_4")
    result = _payload(
        _run(_call_tool("delete_note", {"score_id": sid, "measure": 1, "beat": 1}))
    )
    assert result["success"] is True
    assert result["changed_element_ids"] == []
    assert "rest" in result["summary"].lower()
