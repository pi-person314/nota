"""End-to-end test of the real MCP stdio client (`nota.orchestrator.mcp_client`
.MCPClientManager): a real `python -m nota.mcp_server` subprocess, a real
`ClientSession`, a real `list_tools`, and a real `add_dynamic`/`undo` call
against a fixture score on disk. Only the Anthropic side is mocked (via
`run_command`'s `_get_client` seam) -- the MCP transport is exercised for
real, which is the point of this test.

Uses its own `MCPClientManager()` instance (not the process-wide
`.instance()` singleton) so it can point the subprocess at this test's
temp DATABASE_URL/SCORE_STORAGE_DIR without disturbing any other test that
might share the singleton, and shuts it down explicitly afterward.
"""

from __future__ import annotations

import pytest

from nota.orchestrator import loop
from nota.orchestrator.mcp_client import MCPClientManager

from .fakes import fake_response, text_block, tool_use_block


@pytest.fixture
def real_dispatcher(app):
    cfg = app.config["NOTA_CONFIG"]
    manager = MCPClientManager()
    manager.configure(database_url=cfg.database_url, score_storage_dir=cfg.score_storage_dir)
    yield manager
    manager.shutdown()


def test_real_mcp_stdio_list_tools_and_call_tool(make_score, real_dispatcher):
    score_id = make_score()

    schemas = real_dispatcher.list_tool_schemas()
    names = {schema["name"] for schema in schemas}
    assert {"add_dynamic", "draw_slur", "add_articulation", "undo", "redo"} <= names
    add_dynamic_schema = next(s for s in schemas if s["name"] == "add_dynamic")
    assert add_dynamic_schema["input_schema"]["type"] == "object"
    assert "measure" in add_dynamic_schema["input_schema"]["properties"]

    result = real_dispatcher.call_tool(
        "add_dynamic", {"score_id": score_id, "measure": 1, "beat": 1, "dynamic": "f"}
    )
    assert result["success"] is True
    assert result["changed_element_ids"]

    undo_result = real_dispatcher.call_tool("undo", {"score_id": score_id})
    assert undo_result["success"] is True
    assert undo_result["summary"].startswith("Undid: add_dynamic")


def test_run_command_end_to_end_over_real_mcp_transport(
    make_score, real_dispatcher, install_fake_client, monkeypatch
):
    score_id = make_score()
    monkeypatch.setattr(loop, "_get_dispatcher", lambda: real_dispatcher)
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
    assert result["changed_element_ids"][0] in result["musicxml"]
