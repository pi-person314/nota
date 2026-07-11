"""Sync-facing client for the notation tools, backed by the stateless MCP
stdio server (`python -m nota.mcp_server`).

Flask is a synchronous, multi-threaded framework; the `mcp` package's
`ClientSession` is asyncio-based. `MCPClientManager` bridges the two: it
runs a single background thread with its own asyncio event loop, starts the
MCP server subprocess and opens one persistent `ClientSession` on that loop
the first time it's needed, and exposes plain blocking methods
(`list_tool_schemas`, `call_tool`) that any Flask request thread can call
via `asyncio.run_coroutine_threadsafe`.

This is deliberately behind a small interface (see `ToolDispatcher` below)
so a future caller could swap in a direct-function-call dispatcher (import
`nota.mcp_server.tools` directly, skipping the subprocess and the MCP wire
protocol entirely) without touching `nota.orchestrator.loop`. The stdio
approach is used here: a real end-to-end smoke test (list_tools + a live
tool call against a fixture score, subprocess and all) passes reliably on
Windows, so there was no need to fall back.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
from concurrent.futures import TimeoutError as FutureTimeoutError
from contextlib import AsyncExitStack
from datetime import timedelta
from typing import Any, Protocol

DEFAULT_CALL_TIMEOUT = 30.0
TOOL_TRANSPORT_ERROR = "TOOL_TRANSPORT_ERROR"


class ToolDispatcher(Protocol):
    """The interface `nota.orchestrator.loop` depends on. `MCPClientManager`
    is the production implementation; tests may substitute a fake or a
    direct-function-dispatch adapter that satisfies the same shape.
    """

    def list_tool_schemas(self) -> list[dict]: ...

    def call_tool(self, name: str, arguments: dict, timeout: float = DEFAULT_CALL_TIMEOUT) -> dict: ...


def _transport_error(message: str) -> dict:
    return {"success": False, "error_code": TOOL_TRANSPORT_ERROR, "message": message}


class MCPClientManager:
    """Thread-safe singleton wrapping one persistent MCP stdio session.

    `instance()` returns the process-wide singleton for production use.
    Tests that want an isolated subprocess/session (e.g. to point it at a
    temp DATABASE_URL/SCORE_STORAGE_DIR different from whatever the
    singleton was last configured with) should construct `MCPClientManager()`
    directly instead and call `shutdown()` on it when done.
    """

    _singleton: "MCPClientManager | None" = None
    _singleton_lock = threading.Lock()

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._start_lock = threading.Lock()

        self._session = None
        self._exit_stack: AsyncExitStack | None = None
        self._session_init_lock: asyncio.Lock | None = None

        self._tool_schemas: list[dict] | None = None

        self._database_url: str | None = None
        self._score_storage_dir: str | None = None

        self._restarted_once = False

    # -- singleton lifecycle -------------------------------------------------

    @classmethod
    def instance(cls) -> "MCPClientManager":
        with cls._singleton_lock:
            if cls._singleton is None:
                cls._singleton = cls()
            return cls._singleton

    @classmethod
    def reset_singleton_for_tests(cls) -> None:
        """Drop the process-wide singleton so the next `instance()` call
        builds a fresh manager. Does not shut down whatever manager was
        previously installed — callers should call `shutdown()` on it
        first if it ever started a subprocess.
        """
        with cls._singleton_lock:
            cls._singleton = None

    # -- configuration ---------------------------------------------------

    def configure(self, *, database_url: str, score_storage_dir: str) -> None:
        """Record the environment to pass to the MCP subprocess.

        Only affects subprocess starts that happen after this call — if a
        session is already running, it keeps running against whatever
        environment it was started with until it dies and is restarted.
        Safe to call multiple times before the first tool call.
        """
        self._database_url = database_url
        self._score_storage_dir = score_storage_dir

    # -- background loop / thread ----------------------------------------

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        with self._start_lock:
            if self._loop is None:
                self._loop = asyncio.new_event_loop()
                self._thread = threading.Thread(
                    target=self._loop.run_forever,
                    name="nota-mcp-client",
                    daemon=True,
                )
                self._thread.start()
            return self._loop

    def _run_coro(self, coro, timeout: float):
        loop = self._ensure_loop()
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result(timeout=timeout)

    # -- session management (runs on the background loop) ----------------

    def _subprocess_env(self) -> dict:
        env = dict(os.environ)
        if self._database_url:
            env["DATABASE_URL"] = self._database_url
        if self._score_storage_dir:
            env["SCORE_STORAGE_DIR"] = self._score_storage_dir
        return env

    async def _start_session(self):
        # Imported lazily so importing this module never requires the `mcp`
        # package to be importable in contexts that don't use it.
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "nota.mcp_server"],
            env=self._subprocess_env(),
        )

        stack = AsyncExitStack()
        try:
            read, write = await stack.enter_async_context(stdio_client(params))
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
        except BaseException:
            await stack.aclose()
            raise

        self._exit_stack = stack
        self._session = session
        return session

    async def _ensure_session(self):
        if self._session is not None:
            return self._session
        if self._session_init_lock is None:
            self._session_init_lock = asyncio.Lock()
        async with self._session_init_lock:
            if self._session is not None:
                return self._session
            return await self._start_session()

    async def _close_session(self) -> None:
        stack, self._exit_stack = self._exit_stack, None
        self._session = None
        if stack is not None:
            try:
                await stack.aclose()
            except Exception:
                pass

    # -- tool schemas ------------------------------------------------------

    async def _list_tools_async(self) -> list[dict]:
        session = await self._ensure_session()
        result = await session.list_tools()
        return [
            {
                "name": tool.name,
                "description": tool.description or "",
                "input_schema": tool.inputSchema,
            }
            for tool in result.tools
        ]

    def list_tool_schemas(self) -> list[dict]:
        """Return the notation tools in Anthropic `tools` param format,
        cached after the first successful call.
        """
        if self._tool_schemas is not None:
            return self._tool_schemas
        schemas = self._run_coro(self._list_tools_async(), timeout=DEFAULT_CALL_TIMEOUT)
        self._tool_schemas = schemas
        return schemas

    # -- tool calls ----------------------------------------------------------

    async def _call_tool_async(self, name: str, arguments: dict, timeout: float) -> dict:
        try:
            session = await self._ensure_session()
            result = await session.call_tool(
                name, arguments, read_timeout_seconds=timedelta(seconds=timeout)
            )
        except Exception:
            # The subprocess or session may have died; restart once and retry
            # before giving up, so a single crashed call doesn't wedge every
            # subsequent command for the process's lifetime.
            await self._close_session()
            try:
                session = await self._ensure_session()
                result = await session.call_tool(
                    name, arguments, read_timeout_seconds=timedelta(seconds=timeout)
                )
            except Exception as exc:
                return _transport_error(f"Tool call '{name}' failed: {exc}")

        return _parse_call_result(result, name)

    def call_tool(self, name: str, arguments: dict, timeout: float = DEFAULT_CALL_TIMEOUT) -> dict:
        """Call a notation tool by name and return its parsed JSON result.

        Never raises: transport-level failures (subprocess died twice,
        call timed out, malformed response) come back as a structured
        `{"success": false, "error_code": "TOOL_TRANSPORT_ERROR", ...}`
        dict, in the same shape a tool-level validation error would use, so
        the agentic loop can feed it back to Claude like any other error.
        """
        try:
            return self._run_coro(
                self._call_tool_async(name, arguments, timeout), timeout=timeout + 5
            )
        except FutureTimeoutError:
            return _transport_error(f"Tool call '{name}' timed out after {timeout}s.")
        except Exception as exc:
            return _transport_error(f"Tool call '{name}' failed: {exc}")

    # -- shutdown ----------------------------------------------------------

    def shutdown(self) -> None:
        """Close the MCP session/subprocess and stop the background loop.
        Safe to call even if nothing was ever started.
        """
        loop = self._loop
        if loop is None:
            return

        if self._session is not None or self._exit_stack is not None:
            try:
                future = asyncio.run_coroutine_threadsafe(self._close_session(), loop)
                future.result(timeout=10)
            except Exception:
                pass

        loop.call_soon_threadsafe(loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=5)

        self._loop = None
        self._thread = None
        self._tool_schemas = None
        self._session_init_lock = None


def _first_text_block(result) -> str:
    for block in getattr(result, "content", None) or []:
        if getattr(block, "type", None) == "text":
            return block.text
    return ""


def _parse_call_result(result: Any, name: str) -> dict:
    """Turn an `mcp.types.CallToolResult` into the plain dict every
    notation tool returns. FastMCP tools here are plain `-> dict` functions
    with no declared output schema, so the result always arrives as a JSON
    text block rather than `structuredContent` — but structuredContent is
    checked first in case that ever changes.
    """
    if getattr(result, "isError", False):
        text = _first_text_block(result)
        return _transport_error(text or f"Tool '{name}' reported an error with no message.")

    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        return structured

    text = _first_text_block(result)
    if text:
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            return parsed

    return _transport_error(f"Tool '{name}' returned an unparseable result.")
