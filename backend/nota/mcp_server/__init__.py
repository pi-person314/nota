"""Stateless MCP notation-tool server.

`tools.py` holds the importable, framework-free tool implementations;
`server.py` exposes them over MCP stdio via the `mcp` package. See
`harness.py` for the per-call load/validate/snapshot/mutate/persist
lifecycle every tool goes through.
"""
