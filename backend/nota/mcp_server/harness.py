"""The stateless per-call harness every notation tool runs through.

The MCP server never holds a parsed document across calls. Each call:

1. resolves the score's file path via `storage.path_for` (SCORE_NOT_FOUND
   if there is no such score),
2. parses the file fresh with music21,
3. asks the tool-supplied `planner` to validate the request against the
   parsed score and describe what it would do — validation failures raise
   `ToolError` here, before anything is written to the undo stack,
4. if the planner reports a no-op (e.g. add_dynamic's de-duplication),
   returns success with no snapshot and no write,
5. otherwise snapshots the score's current on-disk XML (so undo restores
   the pre-mutation state), applies the mutation, and writes the result
   back to the same path,
6. verifies every id the mutation reports actually survived serialization,
7. touches the score's last-modified timestamp and returns the result.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import music21 as m21

from .. import storage
from .errors import ErrorCode, ToolError


@dataclass
class ToolPlan:
    """What a tool's planner decided to do, produced against a fully
    validated request. Exactly one of `apply`/`no_op_summary` is set.

    `apply` performs the actual mutation (already knows exactly which
    objects to touch, since the planner resolved them during validation)
    and returns `(changed_element_ids, summary)`.
    """

    apply: Callable[[], tuple[list[str], str]] | None = None
    no_op_summary: str | None = None

    def __post_init__(self) -> None:
        has_apply = self.apply is not None
        has_no_op = self.no_op_summary is not None
        if has_apply == has_no_op:
            raise ValueError("ToolPlan requires exactly one of apply/no_op_summary")


Planner = Callable[[m21.stream.Score], ToolPlan]


def _ok(changed_element_ids: list[str], summary: str) -> dict:
    return {"success": True, "changed_element_ids": changed_element_ids, "summary": summary}


def _error(code: str, message: str) -> dict:
    return {"success": False, "error_code": code, "message": message}


def run_tool(score_id: str, label: str, planner: Planner) -> dict:
    """Run one notation tool call through the full stateless lifecycle.

    `label` becomes the undo-stack entry's label (e.g.
    "add_dynamic f m12 b1") and is only ever recorded if a mutation
    actually happens.
    """
    path = storage.path_for(score_id)
    if path is None:
        return _error(ErrorCode.SCORE_NOT_FOUND, f"No score with id {score_id}.")

    score = m21.converter.parse(path)

    try:
        plan = planner(score)
    except ToolError as exc:
        return _error(exc.code, exc.message)

    if plan.no_op_summary is not None:
        return _ok([], plan.no_op_summary)

    # Snapshot the pre-mutation on-disk state before touching anything.
    storage.save_snapshot(score_id, label)

    changed_element_ids, summary = plan.apply()

    score.write("musicxml", fp=path)

    with open(path, "r", encoding="utf-8") as f:
        written_xml = f.read()

    missing = [i for i in changed_element_ids if f'id="{i}"' not in written_xml]
    if missing:
        # A tool reported an id that music21 did not actually serialize.
        # This is a programming error in the tool (it should have fallen
        # back to a note-level id for that element type), not a user-
        # facing failure, so it is treated as an invariant violation
        # rather than a structured tool error.
        raise RuntimeError(
            f"xml:id verification failed for tool call '{label}': ids {missing} were "
            "returned but do not appear in the serialized MusicXML."
        )

    storage.touch_modified(score_id)
    return _ok(changed_element_ids, summary)
