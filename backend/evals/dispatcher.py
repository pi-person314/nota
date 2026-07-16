"""Tool-dispatch backends for the eval runner.

`nota.orchestrator.loop.run_command` gets its tool dispatcher from the
module-level `_get_dispatcher()` seam (deliberately factored out in
loop.py so callers can swap the tool transport without editing the loop
itself). Both classes here satisfy the same `ToolDispatcher` protocol
loop.py depends on:

- `RecordingDispatcher` wraps any dispatcher and records every
  `(tool_name, arguments)` pair passed to `call_tool`, in call order, so a
  caller can inspect exactly what the orchestrator asked the tool layer to
  do -- this is how the runner recovers "tools_called" and the actual
  arguments without touching loop.py.
- `DirectToolDispatcher` calls the notation tool functions in
  `nota.mcp_server.tools` directly, bypassing the MCP stdio subprocess
  entirely. Used by the no-API-key harness-validation tests (and available
  to the live runner too); schema fidelity does not matter there because a
  scripted fake Anthropic client never inspects tool schemas the way the
  real API does.
"""

from __future__ import annotations

from nota.orchestrator.mcp_client import DEFAULT_CALL_TIMEOUT, ToolDispatcher

ALL_TOOL_NAMES = (
    "add_dynamic",
    "draw_slur",
    "add_articulation",
    "draw_hairpin",
    "add_text_expression",
    "add_tempo",
    "add_rehearsal_mark",
    "add_ornament",
    "remove_notation",
    "undo",
    "redo",
)


class RecordingDispatcher:
    """Decorator around a `ToolDispatcher` that records every call it
    forwards. `self.calls` is a flat, ever-growing list across however many
    `loop.run_command` invocations share this instance -- callers that want
    just one case's calls should slice by `len(dispatcher.calls)` before
    and after running that case (see `evals.run_evals.run_case`).
    """

    def __init__(self, inner: ToolDispatcher):
        self._inner = inner
        self.calls: list[tuple[str, dict]] = []

    def list_tool_schemas(self) -> list[dict]:
        return self._inner.list_tool_schemas()

    def call_tool(self, name: str, arguments: dict, timeout: float = DEFAULT_CALL_TIMEOUT) -> dict:
        self.calls.append((name, dict(arguments)))
        return self._inner.call_tool(name, arguments, timeout=timeout)

    def reset(self) -> None:
        self.calls.clear()


class DirectToolDispatcher:
    """A `ToolDispatcher` that calls `nota.mcp_server.tools` functions
    directly -- no subprocess, no MCP wire protocol. Tool schemas are a
    static stand-in (name + empty object schema) covering all eleven real
    tools; good enough for a scripted fake Anthropic client, not a
    substitute for the real MCP server's schemas in a live run.
    """

    def __init__(self):
        from nota.mcp_server import tools as mcp_tools

        self._tools = mcp_tools

    def list_tool_schemas(self) -> list[dict]:
        return [
            {
                "name": name,
                "description": f"Fake schema for {name}.",
                "input_schema": {"type": "object", "properties": {}},
            }
            for name in ALL_TOOL_NAMES
        ]

    def call_tool(self, name: str, arguments: dict, timeout: float = DEFAULT_CALL_TIMEOUT) -> dict:
        fn = getattr(self._tools, name, None)
        if fn is None:
            return {
                "success": False,
                "error_code": "UNKNOWN_TOOL",
                "message": f"No such tool '{name}'.",
            }
        return fn(**arguments)
