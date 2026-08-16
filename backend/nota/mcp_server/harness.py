"""The stateless per-call harness every notation tool runs through.

No two calls ever share the same in-memory document. Each call:

1. resolves the score's file path via `storage.path_for` (SCORE_NOT_FOUND
   if there is no such score),
2. obtains a parsed score -- checked out of `score_cache` if an entry
   matches the file's current mtime/size, otherwise parsed fresh with
   music21. Either way, this call is the object's exclusive owner: nothing
   else can be holding a reference to it at the same time (see
   `nota.services.score_cache` for how that invariant holds up under
   concurrent calls),
3. asks the tool-supplied `planner` to validate the request against the
   parsed score and describe what it would do — validation failures raise
   `ToolError` here, before anything is written to the undo stack,
4. if the planner reports a no-op (e.g. add_dynamic's de-duplication),
   returns success with no snapshot and no write,
5. otherwise snapshots the score's current on-disk XML (so undo restores
   the pre-mutation state), applies the mutation, writes the result back to
   the same path, and repairs it in place against a known music21 writer
   defect (see `nota.services.musicxml_repair`),
6. verifies every id the mutation reports actually survived serialization,
7. touches the score's last-modified timestamp and returns the result.

Steps 3 and 4 return the checked-out score to the cache before returning,
since neither validation nor no-op detection ever mutates it -- it is
still exactly what a fresh parse would produce. A score that reaches step
5 is never returned to the cache: it is about to be mutated and rewritten,
and the cache only ever holds objects it can guarantee are faithful to
what is currently on disk.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import music21 as m21

from .. import storage
from ..services import musicxml_repair, score_cache, spanner_index
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

    cache = score_cache.get_cache()
    score = cache.checkout(path) if cache is not None else None
    if score is None:
        score = m21.converter.parse(path)

    try:
        plan = planner(score)
    except ToolError as exc:
        # Validation never mutates (see location.py's module docstring and
        # every planner's own docstring), so this object is still exactly
        # what a fresh parse would produce -- safe to make available to
        # whatever the next call against this score turns out to be.
        if cache is not None:
            cache.release(path, score)
        return _error(exc.code, exc.message)

    if plan.no_op_summary is not None:
        if cache is not None:
            cache.release(path, score)
        return _ok([], plan.no_op_summary)

    # Snapshot the pre-mutation on-disk state before touching anything.
    # `score` is intentionally not released back into the cache anywhere
    # past this point: it is about to be mutated and rewritten, and
    # re-inserting a post-mutation object would risk diverging from what a
    # fresh parse of the file it's about to become would yield (see
    # score_cache.py's module docstring).
    storage.save_snapshot(score_id, label)

    changed_element_ids, summary = plan.apply()

    try:
        with spanner_index.accelerated_spanner_lookup():
            score.write("musicxml", fp=path)
    except Exception as exc:
        # Defense in depth: every score reaching this point round-tripped
        # cleanly through music21 at upload time (see musicxml_ingest.py),
        # so this should not be reachable in practice. But some music21
        # content is parseable and yet not re-exportable (observed on a
        # real score: a nested tuplet duration that resolves to a
        # MusicXML note type shorter than any the format defines), so a
        # mutation could in principle create — or merely reveal — such a
        # case. Surfacing it as a structured error keeps a bug here from
        # crashing the caller outright. The pre-mutation snapshot taken
        # above is left in place; it is harmless (undoing it just
        # restores the identical pre-mutation state) and simpler than
        # trying to retract it.
        return _error(
            ErrorCode.EXPORT_FAILED,
            f"Could not save this change: the score could not be re-serialized to MusicXML ({exc}).",
        )

    with open(path, "r", encoding="utf-8") as f:
        written_xml = f.read()

    # Repair a music21 writer defect (see musicxml_repair's module
    # docstring) in what was just written, before anything downstream
    # reads it back: a score that already had the affected shape would
    # otherwise start silently losing spanners the moment this call's
    # rewrite touches it, even though the mutation itself has nothing to
    # do with them.
    repaired_xml = musicxml_repair.repair_spanner_order(written_xml)
    if repaired_xml != written_xml:
        with open(path, "w", encoding="utf-8") as f:
            f.write(repaired_xml)
        written_xml = repaired_xml

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
