"""Test doubles for the orchestrator test suite: a scripted fake Anthropic
client (so tests never make a real API call) and a fake tool dispatcher
that calls the notation tool functions directly, bypassing the MCP
subprocess for tests that only care about orchestration behavior.
"""

from __future__ import annotations

from types import SimpleNamespace


def text_block(text: str) -> SimpleNamespace:
    """A fake Anthropic text content block."""
    return SimpleNamespace(type="text", text=text)


def tool_use_block(id: str, name: str, input: dict) -> SimpleNamespace:
    """A fake Anthropic tool_use content block."""
    return SimpleNamespace(type="tool_use", id=id, name=name, input=input)


def fake_response(*blocks) -> SimpleNamespace:
    """A fake `anthropic.types.Message`-shaped object carrying only the
    `.content` field the orchestrator loop actually reads.
    """
    return SimpleNamespace(content=list(blocks))


class FakeMessages:
    """Fake `client.messages`. `.create()` replays a scripted list of
    responses (or raises a scripted exception instance) in order, and
    records every call's kwargs for assertions.
    """

    def __init__(self, items):
        self._items = list(items)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self._items:
            raise AssertionError("FakeMessages: ran out of scripted responses")
        item = self._items.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


class FakeAnthropicClient:
    """Fake `anthropic.Anthropic()` client good enough to stand in for
    `client.with_options(timeout=...).messages.create(...)`.
    """

    def __init__(self, items):
        self.messages = FakeMessages(items)
        self.with_options_calls: list[dict] = []

    def with_options(self, **kwargs):
        self.with_options_calls.append(kwargs)
        return self


class DirectDispatchDispatcher:
    """Fake `ToolDispatcher` that calls the notation tool functions in
    `nota.mcp_server.tools` directly, bypassing the MCP subprocess/wire
    protocol entirely. Real tool side effects (mutation, snapshots) still
    happen -- only the transport is faked.
    """

    def __init__(self):
        from nota.mcp_server import tools as mcp_tools

        self._tools = mcp_tools
        self.calls: list[tuple[str, dict]] = []

    def list_tool_schemas(self) -> list[dict]:
        return [
            {
                "name": name,
                "description": f"Fake schema for {name}.",
                "input_schema": {"type": "object", "properties": {}},
            }
            for name in ("add_dynamic", "draw_slur", "add_articulation", "undo", "redo")
        ]

    def call_tool(self, name: str, arguments: dict, timeout: float = 30) -> dict:
        self.calls.append((name, dict(arguments)))
        fn = getattr(self._tools, name, None)
        if fn is None:
            return {
                "success": False,
                "error_code": "UNKNOWN_TOOL",
                "message": f"No such tool '{name}'.",
            }
        return fn(**arguments)
