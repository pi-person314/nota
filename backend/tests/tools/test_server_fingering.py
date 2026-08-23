"""MCP-layer tests for add_fingering: registration, schema, and one
end-to-end call through an in-memory MCP client session, in the same
style as test_server_note_tools.py.
"""

from __future__ import annotations

import asyncio
import json

import mcp.types as mcp_types
from mcp.shared.memory import create_connected_server_and_client_session

from nota.mcp_server.server import mcp as mcp_server


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


def test_add_fingering_registered():
    tools_list = _run(_list_tools())
    names = {t.name for t in tools_list}
    assert "add_fingering" in names


def test_add_fingering_requires_score_id():
    tools_list = _run(_list_tools())
    by_name = {t.name: t for t in tools_list}
    schema = by_name["add_fingering"].inputSchema
    assert "score_id" in schema["properties"]
    assert "score_id" in schema.get("required", [])


def test_add_fingering_schema_is_llm_usable():
    tools_list = _run(_list_tools())
    by_name = {t.name: t for t in tools_list}

    tool = by_name["add_fingering"]
    assert tool.description
    assert "open string" in tool.description.lower()
    assert "no-op" in tool.description.lower()

    props = tool.inputSchema["properties"]
    assert "finger" in props
    assert "0" in props["finger"]["description"]

    remove_props = by_name["remove_notation"].inputSchema["properties"]
    assert "fingering" in remove_props["notation_type"]["description"]


def test_call_add_fingering_through_mcp(make_score, read_score_xml):
    sid = make_score("simple_4_4")
    result = _run(
        _call_tool(
            "add_fingering",
            {"score_id": sid, "measure": 1, "beat": 1, "finger": 3},
        )
    )
    payload = _payload(result)
    assert payload["success"] is True
    assert len(payload["changed_element_ids"]) == 1
    xml = read_score_xml(sid)
    for element_id in payload["changed_element_ids"]:
        assert f'id="{element_id}"' in xml
