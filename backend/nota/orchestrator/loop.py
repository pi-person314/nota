"""The Claude agentic loop: turns one transcript into notation-tool calls.

`run_command` is the only entry point other modules should use. It
reconstructs conversation history from `CommandLog`, calls Claude with the
notation tools until it stops requesting tools or the iteration cap is
reached, executes every requested tool through the MCP dispatcher, and logs
the result. Tool effects that already landed before an LLM error or the
iteration cap survive (each mutation has its own undo snapshot), so a
partial run never leaves the user stuck.
"""

from __future__ import annotations

import json
import os
import threading

import anthropic

from .. import db as db_module
from .. import models
from .. import storage
from .mcp_client import MCPClientManager, ToolDispatcher
from .prompt import build_system_prompt

MAX_ITERATIONS = 8
HISTORY_TURNS = 12
PER_ITERATION_TIMEOUT = 30.0
MAX_TOKENS = 1000
DEFAULT_MODEL = "claude-sonnet-4-6"

_client_lock = threading.Lock()
_client: anthropic.Anthropic | None = None


class LLMNotConfiguredError(Exception):
    """Raised when ANTHROPIC_API_KEY is not set in the environment. Callers
    (the /command route) should turn this into a clean 503, never a crash.
    """


def _model_name() -> str:
    return os.environ.get("CLAUDE_MODEL") or DEFAULT_MODEL


def _get_client() -> anthropic.Anthropic:
    """Lazily construct the module-level Anthropic client on first use.

    Kept as a separate function (rather than inlined in `run_command`) so
    tests can monkeypatch it to return a fake client without touching
    `ANTHROPIC_API_KEY` or the process-wide singleton.
    """
    global _client
    with _client_lock:
        if _client is None:
            if not os.environ.get("ANTHROPIC_API_KEY"):
                raise LLMNotConfiguredError("ANTHROPIC_API_KEY is not set.")
            _client = anthropic.Anthropic()
        return _client


def _get_dispatcher() -> ToolDispatcher:
    """Return the tool dispatcher to use for this process. Separated out
    (like `_get_client`) so tests can monkeypatch it — e.g. to a fake that
    does direct function dispatch instead of talking to the real MCP
    subprocess.
    """
    return MCPClientManager.instance()


def _load_history(score_id: str) -> list[dict]:
    """Reconstruct the last `HISTORY_TURNS` commands as alternating
    user/assistant text turns, oldest first. Tool calls and their results
    are deliberately not replayed — only the transcript and the final
    spoken confirmation — keeping this a plain text history rather than a
    replay of the full tool-use conversation.
    """
    with db_module.session_scope() as session:
        rows = (
            session.query(models.CommandLog)
            .filter_by(score_id=score_id)
            .order_by(models.CommandLog.id.desc())
            .limit(HISTORY_TURNS)
            .all()
        )
        rows = list(reversed(rows))

    history: list[dict] = []
    for row in rows:
        history.append({"role": "user", "content": row.transcript})
        if row.confirmation:
            history.append({"role": "assistant", "content": row.confirmation})
    return history


def _log_command(score_id: str, transcript: str, tools_called: list[str], confirmation: str) -> None:
    with db_module.session_scope() as session:
        session.add(
            models.CommandLog(
                score_id=score_id,
                transcript=transcript,
                tools_called_json=json.dumps(tools_called),
                confirmation=confirmation,
            )
        )


def _extract_text(content_blocks) -> str:
    texts = [
        block.text
        for block in content_blocks
        if getattr(block, "type", None) == "text" and getattr(block, "text", "").strip()
    ]
    return " ".join(t.strip() for t in texts).strip()


def run_command(score_id: str, transcript: str) -> dict:
    """Run one voice/text command through the Claude agentic loop.

    Returns:
        {
          "musicxml": <current score XML after any applied changes>,
          "changed_element_ids": [...],
          "confirmation": "<final spoken text, if any>",
          "tools_called": ["add_dynamic", ...],
          "needs_clarification": bool,
          "error": "LLM_TIMEOUT" | "LLM_ERROR",   # only present on failure
        }

    Raises `nota.storage.ScoreNotFoundError` if score_id doesn't exist, and
    `LLMNotConfiguredError` if no ANTHROPIC_API_KEY is configured — both are
    expected to be handled by the HTTP layer, not swallowed here.
    """
    with db_module.session_scope() as session:
        score = session.get(models.Score, score_id)
        if score is None:
            raise storage.ScoreNotFoundError(score_id)
        system_prompt = build_system_prompt(score)

    client = _get_client()
    dispatcher = _get_dispatcher()
    tool_schemas = dispatcher.list_tool_schemas()

    messages: list[dict] = _load_history(score_id)
    messages.append({"role": "user", "content": transcript})

    changed_ids: list[str] = []
    tools_called: list[str] = []
    confirmation = ""
    error: str | None = None

    for _ in range(MAX_ITERATIONS):
        try:
            response = client.with_options(timeout=PER_ITERATION_TIMEOUT).messages.create(
                model=_model_name(),
                system=system_prompt,
                messages=messages,
                tools=tool_schemas,
                max_tokens=MAX_TOKENS,
            )
        except anthropic.APITimeoutError:
            error = "LLM_TIMEOUT"
            break
        except anthropic.APIConnectionError:
            error = "LLM_TIMEOUT"
            break
        except anthropic.APIStatusError:
            error = "LLM_ERROR"
            break

        messages.append({"role": "assistant", "content": response.content})

        text = _extract_text(response.content)
        if text:
            confirmation = text

        tool_uses = [block for block in response.content if getattr(block, "type", None) == "tool_use"]
        if not tool_uses:
            break

        results = []
        for tool_use in tool_uses:
            arguments = dict(tool_use.input or {})
            arguments["score_id"] = score_id
            outcome = dispatcher.call_tool(tool_use.name, arguments)
            tools_called.append(tool_use.name)
            if isinstance(outcome, dict) and outcome.get("success"):
                changed_ids.extend(outcome.get("changed_element_ids", []) or [])
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": json.dumps(outcome),
                }
            )
        messages.append({"role": "user", "content": results})

    _log_command(score_id, transcript, tools_called, confirmation)

    result = {
        "musicxml": storage.read_xml(score_id),
        "changed_element_ids": changed_ids,
        "confirmation": confirmation,
        "tools_called": tools_called,
        "needs_clarification": len(tools_called) == 0 and bool(confirmation),
    }
    if error:
        result["error"] = error
    return result
