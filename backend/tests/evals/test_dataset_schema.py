"""Validates the eval dataset's shape and cross-checks every tool name it
references against the MCP server's actual tool registry -- catches a typo
in a case ("darw_slur") or a stale tool name before it silently no-ops in
a live run. Runs entirely in-process (no subprocess, no API key).
"""

from __future__ import annotations

import asyncio

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from evals.dataset import CASES, CATEGORIES
from nota.mcp_server.server import mcp as mcp_server

REQUIRED_CASE_KEYS = {"id", "category", "transcript", "expectation"}


def _registered_tool_names() -> set[str]:
    async def _list():
        async with create_connected_server_and_client_session(
            mcp_server._mcp_server, raise_exceptions=True
        ) as client:
            result = await client.list_tools()
            return {tool.name for tool in result.tools}

    return asyncio.run(_list())


def _iter_expectation_tool_calls(expectation: dict):
    """Yield every {tool, args} entry reachable from an expectation,
    recursing through any_of alternatives.
    """
    if expectation.get("any_of"):
        for alternative in expectation["any_of"]:
            yield from _iter_expectation_tool_calls(alternative)
        return
    for entry in expectation.get("tool_calls") or []:
        yield entry


def _validate_expectation_shape(expectation: dict) -> list[str]:
    errors: list[str] = []
    has_any_of = bool(expectation.get("any_of"))
    has_no_tools = bool(expectation.get("no_tools"))
    has_tool_calls = "tool_calls" in expectation

    modes = sum([has_any_of, has_no_tools, has_tool_calls])
    if modes == 0:
        errors.append("expectation must set one of any_of/no_tools/tool_calls")
    if has_no_tools and has_tool_calls:
        errors.append("expectation cannot set both no_tools and tool_calls")

    if has_any_of:
        for i, alternative in enumerate(expectation["any_of"]):
            errors += [f"any_of[{i}]: {e}" for e in _validate_expectation_shape(alternative)]

    if has_tool_calls:
        for i, entry in enumerate(expectation["tool_calls"]):
            if "tool" not in entry:
                errors.append(f"tool_calls[{i}] missing required 'tool' key")
            elif not isinstance(entry["tool"], str):
                errors.append(f"tool_calls[{i}]['tool'] must be a string")
            if "args" in entry and not isinstance(entry["args"], dict):
                errors.append(f"tool_calls[{i}]['args'] must be a dict")

    return errors


def test_dataset_size_is_in_expected_range():
    assert 55 <= len(CASES) <= 70, f"expected 55-70 cases, found {len(CASES)}"


def test_dataset_ids_are_unique():
    ids = [c["id"] for c in CASES]
    duplicates = {i for i in ids if ids.count(i) > 1}
    assert not duplicates, f"duplicate case ids: {duplicates}"


def test_every_category_from_the_spec_is_covered():
    """Every category the task calls out by name has at least one case."""
    required = {
        "simple",
        "synonyms",
        "ranges",
        "compound",
        "transcription_artifacts",
        "context_carryover",
        "undo_redo",
        "out_of_range",
        "ambiguous",
    }
    present = {c["category"] for c in CASES}
    missing = required - present
    assert not missing, f"dataset has no cases in category/categories: {missing}"


@pytest.mark.parametrize("dataset_case", CASES, ids=[c["id"] for c in CASES])
def test_case_schema_is_valid(dataset_case):
    missing_keys = REQUIRED_CASE_KEYS - set(dataset_case)
    assert not missing_keys, f"case {dataset_case.get('id')} missing keys: {missing_keys}"

    assert dataset_case["category"] in CATEGORIES, (
        f"case {dataset_case['id']} has unknown category {dataset_case['category']!r}"
    )
    assert isinstance(dataset_case["transcript"], str) and dataset_case["transcript"].strip(), (
        f"case {dataset_case['id']} has an empty transcript"
    )

    for setup in dataset_case.get("setup_transcripts", []):
        assert isinstance(setup, str) and setup.strip(), (
            f"case {dataset_case['id']} has an empty setup_transcripts entry"
        )

    errors = _validate_expectation_shape(dataset_case["expectation"])
    assert not errors, f"case {dataset_case['id']}: {errors}"


def test_every_referenced_tool_exists_in_the_mcp_registry():
    registered = _registered_tool_names()
    referenced: set[str] = set()
    for dataset_case in CASES:
        for entry in _iter_expectation_tool_calls(dataset_case["expectation"]):
            referenced.add(entry["tool"])

    unknown = referenced - registered
    assert not unknown, f"dataset references tool name(s) not registered on the MCP server: {unknown}"


def test_every_registered_tool_is_exercised_at_least_once():
    """The suite is meant to cover all eleven notation tools, not a subset."""
    registered = _registered_tool_names()
    referenced: set[str] = set()
    for dataset_case in CASES:
        for entry in _iter_expectation_tool_calls(dataset_case["expectation"]):
            referenced.add(entry["tool"])

    unexercised = registered - referenced
    assert not unexercised, f"no case in the dataset ever expects tool(s): {unexercised}"
