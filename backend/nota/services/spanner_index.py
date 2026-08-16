"""Scoped speedup for music21's spanner-to-element lookup during MusicXML
export.

`music21.spanner.SpannerBundle.getBySpannedElement` is a linear scan: for
every call it walks every spanner in the bundle and, for each one, walks
that spanner's entire spanned-element list checking object identity. A
MusicXML export calls it once per exported element, so total cost is
O(elements x spanners x elements-per-spanner) -- on a large, spanner-heavy
score this dominates export time by more than an order of magnitude over
everything else the writer does.

`accelerated_spanner_lookup()` is a context manager that, for its duration,
replaces `getBySpannedElement` with an indexed implementation: the first
lookup against a given `SpannerBundle` instance builds a plain dict mapping
`id(spannedElement) -> [spanners that contain it]` by walking each spanner's
spanned elements exactly once, and every lookup after that (including
identical queries) is a dict lookup. Only the patched instance's *class
methods* are swapped -- no `SpannerBundle` or `Spanner` object is mutated --
and the originals are always restored when the `with` block exits, including
on an exception.

Keeping the index correct: a `SpannerBundle`'s contents can change out from
under it while spanners are being resolved -- most notably
`replaceSpannedElement`, which the exporter's own pre-write notation pass
(tuplet-bracket splitting, tie consolidation) calls on individual spanners
to swap in copied/merged elements. Any of `SpannerBundle.append`,
`SpannerBundle.remove`, `SpannerBundle.replaceSpannedElement`, and
`Spanner.replaceSpannedElement` invalidates whatever index it could have
affected, so a lookup immediately after a mutation always rebuilds rather
than returning a stale result. `SpannerBundle`-level mutations only drop
that one bundle's index, since the bundle they were called on is known.
`Spanner.replaceSpannedElement` is called on an individual spanner with no
back-reference to whichever bundle(s) hold it, so it conservatively drops
every index currently built -- correct regardless of which bundle actually
owns that spanner, and cheap in practice since real exports were observed
to run every one of these mutations before the first lookup even happens
(see the accompanying tests), so no index actually gets rebuilt mid-export.

`SPANNER_INDEX_DISABLE=1` (read once per context-manager entry, mirroring
`nota.services.score_cache`'s `SCORE_CACHE_SIZE` pattern) skips the patch
entirely and leaves music21's own implementation in place, for comparison
or as a rollback switch.
"""

from __future__ import annotations

import os
import threading
import weakref
from collections import defaultdict
from contextlib import contextmanager
from typing import Any

from music21 import spanner as m21_spanner

# Guards the patch/unpatch bookkeeping below so nested `with` blocks (and,
# defensively, concurrent ones) can't corrupt which original gets restored.
# The MCP harness only ever has one write in flight per call, but this
# makes reentrancy and restore-on-exception correct regardless.
_lock = threading.RLock()
_depth = 0
_originals: dict[str, Any] = {}

# id(SpannerBundle instance) -> {id(spannedElement): [Spanner, ...]}.
# Weak-keyed so a bundle that goes out of scope mid-export (sub-bundles are
# created constantly, e.g. `getByClass` results) doesn't keep its index
# alive, and so nothing here needs explicit cleanup for bundles the rest of
# music21 has already discarded.
_indexes: "weakref.WeakKeyDictionary[m21_spanner.SpannerBundle, dict[int, list]]" = (
    weakref.WeakKeyDictionary()
)


def _build_index(bundle: m21_spanner.SpannerBundle) -> dict[int, list]:
    index: dict[int, list] = defaultdict(list)
    for sp in bundle._storage:  # noqa: SLF001 - mirrors music21's own internal access pattern
        seen_in_this_spanner: set[int] = set()
        for el in sp.getSpannedElements():
            eid = id(el)
            if eid in seen_in_this_spanner:
                # A spanner's own bookkeeping normally prevents duplicate
                # entries, but the fallback here matches the original
                # scan's semantics either way: a spanner counts once per
                # spanned element, no matter how many times it appears in
                # that spanner's storage.
                continue
            seen_in_this_spanner.add(eid)
            index[eid].append(sp)
    return index


def _indexed_get_by_spanned_element(
    self: m21_spanner.SpannerBundle, spannedElement: Any
) -> m21_spanner.SpannerBundle:
    index = _indexes.get(self)
    if index is None:
        index = _build_index(self)
        _indexes[self] = index
    matches = index.get(id(spannedElement), [])
    return self.__class__(matches)


def _invalidate_this_bundle(original):
    """Wrap a `SpannerBundle` mutator: run it, then drop that bundle's
    index (if any) so the next lookup rebuilds from the mutated state.
    """

    def wrapper(self: m21_spanner.SpannerBundle, *args, **kwargs):
        try:
            return original(self, *args, **kwargs)
        finally:
            _indexes.pop(self, None)

    return wrapper


def _invalidate_all_bundles(original):
    """Wrap `Spanner.replaceSpannedElement`: it runs on a single spanner
    with no reference back to whatever bundle(s) contain it, so the only
    sound response is to drop every index currently built -- see the
    module docstring for why this is cheap in observed practice.
    """

    def wrapper(self, *args, **kwargs):
        try:
            return original(self, *args, **kwargs)
        finally:
            _indexes.clear()

    return wrapper


@contextmanager
def accelerated_spanner_lookup():
    """Patch `SpannerBundle.getBySpannedElement` (and the mutators that
    could invalidate its index) to an indexed implementation for the
    duration of the `with` block, restoring music21's originals on exit --
    normal or via exception.

    Reentrant: nested `with` blocks share the same patch (only the
    outermost entry installs it, only the outermost exit restores it), so
    a call site that's already inside an accelerated block can safely wrap
    its own writes without double-patching or restoring the wrong
    original.

    Set `SPANNER_INDEX_DISABLE=1` to make this a no-op and keep music21's
    stock (unindexed) implementation for the block -- read fresh from the
    environment on every entry, so it can be toggled between calls without
    restarting the process.
    """
    global _depth

    if os.environ.get("SPANNER_INDEX_DISABLE") == "1":
        yield
        return

    with _lock:
        outermost = _depth == 0
        _depth += 1
        if outermost:
            _indexes.clear()
            _originals["getBySpannedElement"] = m21_spanner.SpannerBundle.getBySpannedElement
            _originals["bundle_append"] = m21_spanner.SpannerBundle.append
            _originals["bundle_remove"] = m21_spanner.SpannerBundle.remove
            _originals["bundle_replace"] = m21_spanner.SpannerBundle.replaceSpannedElement
            _originals["spanner_replace"] = m21_spanner.Spanner.replaceSpannedElement

            m21_spanner.SpannerBundle.getBySpannedElement = _indexed_get_by_spanned_element
            m21_spanner.SpannerBundle.append = _invalidate_this_bundle(
                _originals["bundle_append"]
            )
            m21_spanner.SpannerBundle.remove = _invalidate_this_bundle(
                _originals["bundle_remove"]
            )
            m21_spanner.SpannerBundle.replaceSpannedElement = _invalidate_this_bundle(
                _originals["bundle_replace"]
            )
            m21_spanner.Spanner.replaceSpannedElement = _invalidate_all_bundles(
                _originals["spanner_replace"]
            )

    try:
        yield
    finally:
        with _lock:
            _depth -= 1
            if _depth == 0:
                m21_spanner.SpannerBundle.getBySpannedElement = _originals.pop(
                    "getBySpannedElement"
                )
                m21_spanner.SpannerBundle.append = _originals.pop("bundle_append")
                m21_spanner.SpannerBundle.remove = _originals.pop("bundle_remove")
                m21_spanner.SpannerBundle.replaceSpannedElement = _originals.pop(
                    "bundle_replace"
                )
                m21_spanner.Spanner.replaceSpannedElement = _originals.pop("spanner_replace")
                _indexes.clear()
