"""Bounded LRU cache of parsed `music21.stream.Score` objects, sitting in
front of the notation-tool harness's `music21.converter.parse` call so a
sequence of read-only or rejected tool calls against the same on-disk score
doesn't re-pay the parse cost every time.

`music21.stream.Score` objects are mutable, and every accepted tool call in
`nota.mcp_server.harness` mutates its score in place before writing it back
to disk. A cache that could ever hand the same object to two callers -- or
that kept holding a reference to an object some caller went on to mutate --
would silently corrupt itself: caller A mutates the object it was handed,
the file on disk changes under it, and the cache still thinks that object
represents the old file. Two designs were considered for avoiding that:

  (a) Keep cached scores untouched forever and hand out `copy.deepcopy` of
      one on every checkout. Measured against this project's own real
      corpus benchmark scores (`tests/tools/real_score_builders.py`;
      numbers reproduced in `tests/services/test_score_cache.py`), a
      `deepcopy` of a parsed score costs *more* than parsing the source
      file from disk again: roughly 1.6x for a 313-measure quartet
      movement, 2x for a 113-measure quartet movement, and 2.6x for a
      21-measure chorale. music21's deepcopy has to walk and rebuild the
      whole spanner/derivation/site-reference graph, and that turns out to
      be pricier than the (largely C-accelerated) XML parse itself. Paying
      that cost on every checkout would make the "cache" a net slowdown,
      so this design was rejected outright rather than shipped as a
      technically-correct-but-pointless option.

  (b) Pop-on-checkout (chosen). No two callers can ever observe the same
      object: `checkout()` removes the matching entry from the cache and
      hands it to the caller, so ownership transfers completely -- the
      cache holds nothing under that key again until something is
      explicitly put back with `release()`. The harness only calls
      `release()` when it can prove the object it's returning is exactly
      what a fresh parse would still produce: either the tool's planner
      raised `ToolError` before touching anything, or it reported a no-op.
      Both are guaranteed read-only (every planner validates by calling
      into `nota.mcp_server.location`, whose docstring states its
      functions "never mutate the score"; the only mutation happens inside
      the `apply()` closure of an *accepted* `ToolPlan`, which the harness
      never calls on those two paths).

      A score that reaches the mutating path is deliberately never
      released back into the cache, even after a successful write. Doing
      so would mean trusting that the in-memory mutated object is
      bit-for-bit equivalent to what a fresh parse of the file it was just
      written to would yield -- but music21's MusicXML writer is lossy on
      the way out (e.g. two overlapping hairpins on the same note are
      silently dropped by the writer, even though both parse back in fine
      individually), so an in-memory object can diverge from its own
      serialization. Caching it anyway would let that divergence sit in
      the cache indefinitely, waiting to feed some unrelated future call a
      subtly wrong score. The honest cost of playing it safe: this cache
      does not speed up the dominant call pattern (a run of successive
      *accepted* edits to the same score), because every write changes the
      file's mtime/size and invalidates whatever key the next call would
      want anyway. It only helps repeated reads and repeated
      rejected/no-op calls against an otherwise-unchanged file. See
      `harness.py`'s module docstring for how the two release points fit
      into the call lifecycle.

Cache entries are keyed by `(absolute_path, mtime_ns, size)`, read from a
single `os.stat()` call. Any rewrite of the file -- including
`nota.storage.undo`/`redo`, which write straight to disk without touching
this module at all -- changes at least the mtime and almost always the
size too, so a stale entry is simply never matched again; nothing needs an
explicit invalidation call.
"""

from __future__ import annotations

import os
import threading
from collections import OrderedDict

import music21 as m21

# Conservative default: these objects are large (a full orchestral score can
# be tens of MB in memory), so the cache stays small unless a deployment
# opts into more. SCORE_CACHE_SIZE=0 disables caching entirely -- every
# call falls back to parsing fresh, exactly as before this module existed.
DEFAULT_MAX_ENTRIES = 4

CacheKey = tuple[str, int, int]


def _stat_key(path: str) -> CacheKey | None:
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (os.path.abspath(path), st.st_mtime_ns, st.st_size)


class ScoreCache:
    """Bounded LRU pop-on-checkout cache for parsed scores.

    Every public method takes its own lock for the duration of the
    dictionary operation, so concurrent `checkout`/`release` calls from
    multiple threads (Flask's default development server runs threaded)
    can't interleave into a corrupt internal state. That does not by
    itself make the *cache contents* correct under concurrency -- it only
    guarantees the pop-then-store bookkeeping is atomic, which combined
    with pop-on-checkout is what actually prevents two callers from ever
    holding the same object at once.
    """

    def __init__(self, max_entries: int = DEFAULT_MAX_ENTRIES):
        if max_entries < 0:
            raise ValueError("max_entries must be >= 0")
        self.max_entries = max_entries
        self._lock = threading.Lock()
        self._entries: "OrderedDict[CacheKey, m21.stream.Score]" = OrderedDict()

    def checkout(self, path: str) -> m21.stream.Score | None:
        """Remove and return the cached score for `path`, if one matches
        the file's current mtime/size. Returns None on a miss (nothing
        cached under that key, or the file changed since it was cached).

        The returned object is no longer reachable from the cache -- the
        caller now owns it exclusively and may mutate it freely.
        """
        if self.max_entries == 0:
            return None
        key = _stat_key(path)
        if key is None:
            return None
        with self._lock:
            return self._entries.pop(key, None)

    def release(self, path: str, score: m21.stream.Score) -> None:
        """Make `score` available to the next `checkout()` for `path`.

        Callers must only pass an object they can prove has not been
        mutated since it was parsed or checked out (see the module
        docstring's discussion of why) -- this method trusts its caller
        entirely and does not itself check that. Evicts the
        least-recently-used entry first if this insertion would exceed
        `max_entries`.
        """
        if self.max_entries == 0:
            return
        key = _stat_key(path)
        if key is None:
            return
        with self._lock:
            self._entries[key] = score
            self._entries.move_to_end(key)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


def _max_entries_from_env() -> int:
    raw = os.environ.get("SCORE_CACHE_SIZE")
    if raw is None or raw.strip() == "":
        return DEFAULT_MAX_ENTRIES
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_MAX_ENTRIES
    return max(value, 0)


_cache: ScoreCache | None = None
_configured = False


def configure(max_entries: int | None = None) -> None:
    """(Re)configure the process-wide score cache.

    Mirrors `nota.storage.configure`'s lazy-init pattern: pass an explicit
    `max_entries` from anything that owns process/test startup, or omit it
    to resolve `SCORE_CACHE_SIZE` from the environment (default
    `DEFAULT_MAX_ENTRIES`; `0` disables caching). Safe to call more than
    once -- e.g. between tests -- each call discards anything already
    cached and starts fresh.
    """
    global _cache, _configured
    resolved = _max_entries_from_env() if max_entries is None else max_entries
    _cache = ScoreCache(resolved) if resolved > 0 else None
    _configured = True


def get_cache() -> ScoreCache | None:
    """Return the process-wide score cache, lazily configuring it from
    `SCORE_CACHE_SIZE` on first use if nothing has configured it yet.

    Returns None when caching is disabled (`SCORE_CACHE_SIZE=0`); callers
    should treat that the same as "always a cache miss" and parse
    unconditionally.
    """
    if not _configured:
        configure()
    return _cache
