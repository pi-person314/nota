"""MCP-layer tests for the six new notation tools (draw_hairpin,
add_text_expression, add_tempo, add_rehearsal_mark, add_ornament,
remove_notation): registration, schemas, and end-to-end calls through an
in-memory MCP client session, in the same style as test_server.py.

Kept as a separate module rather than extending test_server.py so the
original file (and its EXPECTED_TOOLS assertions covering the first three
tools) is left untouched.
"""

from __future__ import annotations

import asyncio
import json

import mcp.types as mcp_types
from mcp.shared.memory import create_connected_server_and_client_session

from nota.mcp_server.server import mcp as mcp_server

ALL_ELEVEN_TOOLS = {
    "add_dynamic",
    "draw_slur",
    "add_articulation",
    "undo",
    "redo",
    "draw_hairpin",
    "add_text_expression",
    "add_tempo",
    "add_rehearsal_mark",
    "add_ornament",
    "remove_notation",
}

NEW_TOOLS = {
    "draw_hairpin",
    "add_text_expression",
    "add_tempo",
    "add_rehearsal_mark",
    "add_ornament",
    "remove_notation",
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


def test_all_eleven_tools_registered():
    tools_list = _run(_list_tools())
    names = {t.name for t in tools_list}
    assert ALL_ELEVEN_TOOLS <= names


def test_every_new_tool_requires_score_id():
    tools_list = _run(_list_tools())
    for tool in tools_list:
        if tool.name not in NEW_TOOLS:
            continue
        schema = tool.inputSchema
        assert "score_id" in schema["properties"], tool.name
        assert "score_id" in schema.get("required", []), tool.name


def test_new_tool_descriptions_are_llm_usable():
    tools_list = _run(_list_tools())
    by_name = {t.name: t for t in tools_list}

    for name in NEW_TOOLS:
        assert by_name[name].description, name

    hairpin_props = by_name["draw_hairpin"].inputSchema["properties"]
    assert "diminuendo" in hairpin_props["direction"]["description"].lower()
    assert "no-op" in by_name["add_rehearsal_mark"].description.lower()
    assert "ambiguous_target".upper() in by_name["remove_notation"].description.upper()

    tempo_props = by_name["add_tempo"].inputSchema["properties"]
    assert "bpm" in tempo_props
    assert "text" in tempo_props
    assert "unit" in tempo_props

    remove_props = by_name["remove_notation"].inputSchema["properties"]
    assert "beat" in remove_props
    assert "notation_type" in remove_props
    required = by_name["remove_notation"].inputSchema.get("required", [])
    assert "beat" not in required
    assert "notation_type" not in required


def test_call_draw_hairpin_through_mcp(make_score, read_score_xml):
    sid = make_score("simple_4_4")
    result = _run(
        _call_tool(
            "draw_hairpin",
            {
                "score_id": sid,
                "start_measure": 1,
                "start_beat": 1,
                "end_measure": 1,
                "end_beat": 4,
                "direction": "crescendo",
            },
        )
    )
    payload = _payload(result)
    assert payload["success"] is True
    assert len(payload["changed_element_ids"]) == 2
    xml = read_score_xml(sid)
    for element_id in payload["changed_element_ids"]:
        assert f'id="{element_id}"' in xml


def test_call_remove_notation_through_mcp(make_score, read_score_xml):
    sid = make_score("simple_4_4")
    add_result = _run(
        _call_tool("add_dynamic", {"score_id": sid, "measure": 1, "beat": 1, "dynamic": "f"})
    )
    assert _payload(add_result)["success"] is True

    remove_result = _run(
        _call_tool("remove_notation", {"score_id": sid, "measure": 1, "beat": 1})
    )
    payload = _payload(remove_result)
    assert payload["success"] is True
    assert payload["changed_element_ids"] == []
    assert "measure 1" in payload["summary"]


def test_call_remove_notation_ambiguous_through_mcp(make_score):
    sid = make_score("simple_4_4")
    _run(_call_tool("add_dynamic", {"score_id": sid, "measure": 1, "beat": 1, "dynamic": "f"}))
    _run(
        _call_tool(
            "add_articulation",
            {"score_id": sid, "measure": 1, "beat": 1, "articulation": "staccato"},
        )
    )

    result = _run(_call_tool("remove_notation", {"score_id": sid, "measure": 1, "beat": 1}))
    payload = _payload(result)
    assert payload["success"] is False
    assert payload["error_code"] == "AMBIGUOUS_TARGET"


def test_error_results_pass_through_mcp_unchanged_for_new_tools(storage_env):
    result = _run(
        _call_tool(
            "add_tempo",
            {"score_id": "does-not-exist", "measure": 1, "bpm": 120},
        )
    )
    payload = _payload(result)
    assert payload["success"] is False
    assert payload["error_code"] == "SCORE_NOT_FOUND"
