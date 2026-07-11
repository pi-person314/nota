"""Command orchestration: turns one voice/text transcript into notation-tool
calls via Claude, and the supporting HTTP-facing machinery (per-score
locking, system prompt construction, MCP tool dispatch).

`loop.run_command` is the main entry point; `nota.routes.commands` is the
HTTP layer that calls it.
"""
