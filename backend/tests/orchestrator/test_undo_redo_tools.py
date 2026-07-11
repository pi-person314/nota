"""Tests for the additive `undo`/`redo` MCP tool functions in
`nota.mcp_server.tools`. These wrap `nota.storage.undo`/`redo` in the same
structured success/error contract every other notation tool uses, so they
can be driven by the agentic loop the same way as any other tool.
"""

from __future__ import annotations

from nota import storage
from nota.mcp_server import tools


def test_undo_on_empty_stack_returns_nothing_to_undo(make_score):
    score_id = make_score()

    result = tools.undo(score_id)

    assert result == {
        "success": False,
        "error_code": "NOTHING_TO_UNDO",
        "message": "There is nothing to undo.",
    }


def test_redo_on_empty_stack_returns_nothing_to_redo(make_score):
    score_id = make_score()

    result = tools.redo(score_id)

    assert result == {
        "success": False,
        "error_code": "NOTHING_TO_REDO",
        "message": "There is nothing to redo.",
    }


def test_undo_on_unknown_score_returns_score_not_found():
    result = tools.undo("does-not-exist")

    assert result["success"] is False
    assert result["error_code"] == "SCORE_NOT_FOUND"


def test_redo_on_unknown_score_returns_score_not_found():
    result = tools.redo("does-not-exist")

    assert result["success"] is False
    assert result["error_code"] == "SCORE_NOT_FOUND"


def test_undo_reverts_the_most_recent_mutation(make_score):
    score_id = make_score()

    add_result = tools.add_dynamic(score_id, measure=1, beat=1, dynamic="f")
    assert add_result["success"] is True
    dynamic_id = add_result["changed_element_ids"][0]
    xml_after_add = storage.read_xml(score_id)
    assert f'id="{dynamic_id}"' in xml_after_add

    undo_result = tools.undo(score_id)

    assert undo_result["success"] is True
    assert undo_result["changed_element_ids"] == []
    assert undo_result["summary"].startswith("Undid: add_dynamic")
    xml_after_undo = storage.read_xml(score_id)
    assert f'id="{dynamic_id}"' not in xml_after_undo


def test_redo_reapplies_an_undone_mutation(make_score):
    score_id = make_score()

    add_result = tools.add_dynamic(score_id, measure=1, beat=1, dynamic="f")
    dynamic_id = add_result["changed_element_ids"][0]
    tools.undo(score_id)
    assert f'id="{dynamic_id}"' not in storage.read_xml(score_id)

    redo_result = tools.redo(score_id)

    assert redo_result["success"] is True
    assert redo_result["changed_element_ids"] == []
    assert redo_result["summary"].startswith("Redid: add_dynamic")
    assert f'id="{dynamic_id}"' in storage.read_xml(score_id)


def test_undo_tool_is_registered_on_the_mcp_server():
    from nota.mcp_server.server import mcp

    # FastMCP registers tools by decoration at import time; assert both
    # new tools made it onto the server, not just onto tools.py.
    tool_names = {t.name for t in _list_registered_tools(mcp)}
    assert {"undo", "redo"} <= tool_names


def _list_registered_tools(mcp) -> list:
    """FastMCP exposes an async list_tools(); the tool manager's sync
    registry is what we actually want to check without spinning up an
    event loop for a pure registration check.
    """
    return list(mcp._tool_manager._tools.values())
