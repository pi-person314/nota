"""Unit tests for `nota.services.score_cache`: the pop-on-checkout LRU
cache that sits in front of the notation-tool harness's music21 parse
call. Harness-level integration tests (proving a real tool-call sequence
behaves identically with the cache on vs off) live in
`tests/tools/test_score_cache_integration.py`, since they need the
`make_score`/`tools` fixtures that module already has set up.
"""

from __future__ import annotations

import os
import threading
import time

import music21 as m21
import pytest

from nota.services import score_cache

SAMPLE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="4.0">
  <part-list>
    <score-part id="P1"><part-name>Violin</part-name></score-part>
  </part-list>
  <part id="P1">
    <measure number="1">
      <attributes>
        <divisions>1</divisions>
        <time><beats>4</beats><beat-type>4</beat-type></time>
      </attributes>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>4</duration><type>whole</type></note>
    </measure>
  </part>
</score-partwise>
"""


@pytest.fixture(autouse=True)
def _reset_process_wide_cache():
    """`score_cache.configure`/`get_cache` manage a process-wide singleton
    (mirroring `nota.storage`'s own lazy-init pattern, since the standalone
    MCP server process needs this to work without going through
    `nota.config`). Reset it around every test so tests that touch
    `configure`/`get_cache` don't leak state into whatever runs next in
    the same pytest session.
    """
    yield
    score_cache._cache = None
    score_cache._configured = False


def _write_score(path, xml: str = SAMPLE_XML) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(xml)


# --- ScoreCache: checkout/release basics ------------------------------


def test_checkout_miss_when_nothing_cached(tmp_path):
    path = tmp_path / "a.musicxml"
    _write_score(path)
    cache = score_cache.ScoreCache(max_entries=4)
    assert cache.checkout(str(path)) is None


def test_checkout_miss_when_file_does_not_exist(tmp_path):
    cache = score_cache.ScoreCache(max_entries=4)
    assert cache.checkout(str(tmp_path / "missing.musicxml")) is None


def test_release_then_checkout_hits_the_same_object(tmp_path):
    path = tmp_path / "a.musicxml"
    _write_score(path)
    cache = score_cache.ScoreCache(max_entries=4)
    score = m21.converter.parse(str(path))

    cache.release(str(path), score)

    assert cache.checkout(str(path)) is score


def test_checkout_pops_the_entry_so_a_second_checkout_misses(tmp_path):
    """Pop-on-checkout: once an entry is handed out, the cache holds
    nothing under that key until something is explicitly released back.
    """
    path = tmp_path / "a.musicxml"
    _write_score(path)
    cache = score_cache.ScoreCache(max_entries=4)
    score = m21.converter.parse(str(path))
    cache.release(str(path), score)

    assert cache.checkout(str(path)) is score
    assert cache.checkout(str(path)) is None


def test_mutating_a_checked_out_score_cannot_corrupt_a_later_checkout(tmp_path):
    """The whole reason this cache exists: mutating an object handed out
    by checkout() must never be visible through a later checkout() under
    the same key. Pop-on-checkout makes this true structurally -- the key
    is simply empty the instant checkout() returns -- rather than by
    hoping callers behave.
    """
    path = tmp_path / "a.musicxml"
    _write_score(path)
    cache = score_cache.ScoreCache(max_entries=4)
    score = m21.converter.parse(str(path))
    cache.release(str(path), score)

    checked_out = cache.checkout(str(path))
    assert checked_out is score
    measure = checked_out.parts[0].getElementsByClass(m21.stream.Measure)[0]
    measure.insert(0, m21.dynamics.Dynamic("f"))  # mutate as a tool would

    # No live entry to corrupt: the key was emptied by the checkout above,
    # and nothing re-inserted the (now mutated) object.
    assert cache.checkout(str(path)) is None


def test_invalidated_when_file_is_rewritten(tmp_path):
    path = tmp_path / "a.musicxml"
    _write_score(path)
    cache = score_cache.ScoreCache(max_entries=4)
    score = m21.converter.parse(str(path))
    cache.release(str(path), score)
    assert cache.checkout(str(path)) is score  # sanity: it was cached
    cache.release(str(path), score)

    # Rewrite with different content, forcing the mtime forward even on
    # filesystems with coarse timestamp resolution (this is what a real
    # mutating tool call, or storage.undo/redo, does to the file next).
    new_xml = SAMPLE_XML.replace("<part-name>Violin</part-name>", "<part-name>Viola</part-name>")
    _write_score(path, new_xml)
    st = os.stat(path)
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))

    assert cache.checkout(str(path)) is None


def test_invalidated_when_size_changes_but_mtime_could_collide(tmp_path):
    """Size is part of the key specifically so a same-tick rewrite (mtime
    resolution can be coarse on some filesystems) still invalidates, as
    long as the content length changed -- which every real tool call's
    rewrite does (it inserts at least one new XML element).
    """
    path = tmp_path / "a.musicxml"
    _write_score(path)
    cache = score_cache.ScoreCache(max_entries=4)
    score = m21.converter.parse(str(path))
    cache.release(str(path), score)

    original_stat = os.stat(path)
    longer_xml = SAMPLE_XML.replace("</score-partwise>", "<!-- padding -->\n</score-partwise>")
    assert len(longer_xml) != len(SAMPLE_XML)
    _write_score(path, longer_xml)
    # Force the same mtime as before, to isolate size as the invalidating factor.
    os.utime(path, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))

    assert cache.checkout(str(path)) is None


# --- LRU eviction -------------------------------------------------------


def test_lru_evicts_least_recently_used_at_capacity(tmp_path):
    cache = score_cache.ScoreCache(max_entries=2)
    paths, scores = [], []
    for i in range(3):
        path = tmp_path / f"s{i}.musicxml"
        _write_score(path)
        paths.append(str(path))
        scores.append(m21.converter.parse(str(path)))

    cache.release(paths[0], scores[0])
    cache.release(paths[1], scores[1])
    assert len(cache) == 2

    cache.release(paths[2], scores[2])  # evicts s0 (oldest, untouched since)
    assert len(cache) == 2
    assert cache.checkout(paths[0]) is None
    assert cache.checkout(paths[1]) is scores[1]
    assert cache.checkout(paths[2]) is scores[2]


def test_lru_eviction_tracks_recency_not_just_insertion_order(tmp_path):
    cache = score_cache.ScoreCache(max_entries=2)
    paths, scores = [], []
    for i in range(3):
        path = tmp_path / f"s{i}.musicxml"
        _write_score(path)
        paths.append(str(path))
        scores.append(m21.converter.parse(str(path)))

    cache.release(paths[0], scores[0])
    cache.release(paths[1], scores[1])

    # Touch s0 again (checkout + release), making it most-recently-used.
    reclaimed = cache.checkout(paths[0])
    cache.release(paths[0], reclaimed)

    cache.release(paths[2], scores[2])  # should evict s1, not s0

    assert cache.checkout(paths[0]) is scores[0]
    assert cache.checkout(paths[1]) is None
    assert cache.checkout(paths[2]) is scores[2]


# --- Disabled cache (max_entries=0) -------------------------------------


def test_zero_max_entries_disables_caching(tmp_path):
    path = tmp_path / "a.musicxml"
    _write_score(path)
    cache = score_cache.ScoreCache(max_entries=0)
    score = m21.converter.parse(str(path))

    cache.release(str(path), score)

    assert cache.checkout(str(path)) is None
    assert len(cache) == 0


def test_negative_max_entries_rejected():
    with pytest.raises(ValueError):
        score_cache.ScoreCache(max_entries=-1)


# --- configure()/get_cache(): the SCORE_CACHE_SIZE env toggle ------------


def test_default_env_gives_default_size(monkeypatch):
    monkeypatch.delenv("SCORE_CACHE_SIZE", raising=False)
    score_cache.configure()
    cache = score_cache.get_cache()
    assert cache is not None
    assert cache.max_entries == score_cache.DEFAULT_MAX_ENTRIES


def test_env_var_overrides_default_size(monkeypatch):
    monkeypatch.setenv("SCORE_CACHE_SIZE", "9")
    score_cache.configure()
    cache = score_cache.get_cache()
    assert cache is not None
    assert cache.max_entries == 9


def test_env_var_zero_disables_cache(monkeypatch):
    monkeypatch.setenv("SCORE_CACHE_SIZE", "0")
    score_cache.configure()
    assert score_cache.get_cache() is None


def test_invalid_env_var_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("SCORE_CACHE_SIZE", "not-a-number")
    score_cache.configure()
    cache = score_cache.get_cache()
    assert cache is not None
    assert cache.max_entries == score_cache.DEFAULT_MAX_ENTRIES


def test_explicit_max_entries_overrides_env(monkeypatch):
    monkeypatch.setenv("SCORE_CACHE_SIZE", "9")
    score_cache.configure(max_entries=2)
    cache = score_cache.get_cache()
    assert cache is not None
    assert cache.max_entries == 2


def test_get_cache_lazily_configures_itself_once(monkeypatch):
    monkeypatch.setenv("SCORE_CACHE_SIZE", "3")
    assert not score_cache._configured
    cache = score_cache.get_cache()
    assert cache is not None
    assert cache.max_entries == 3


# --- Thread safety --------------------------------------------------------


def test_thread_safety_no_object_is_ever_checked_out_twice(tmp_path):
    """Flask's default dev server runs threaded, so many tool calls for
    the same score could arrive concurrently. Hammer checkout/release from
    several threads and verify the pop-on-checkout contract actually holds
    under contention: no object is ever held "checked out" by two threads
    at once, and the cache never grows past its configured capacity.
    """
    cache = score_cache.ScoreCache(max_entries=4)
    path = tmp_path / "shared.musicxml"
    _write_score(path)
    cache.release(str(path), m21.converter.parse(str(path)))

    checked_out_ids: set[int] = set()
    bookkeeping_lock = threading.Lock()
    violations: list[int] = []
    stop_at = time.monotonic() + 1.0

    def worker() -> None:
        while time.monotonic() < stop_at:
            got = cache.checkout(str(path))
            if got is None:
                continue
            obj_id = id(got)
            with bookkeeping_lock:
                if obj_id in checked_out_ids:
                    violations.append(obj_id)
                checked_out_ids.add(obj_id)
            with bookkeeping_lock:
                checked_out_ids.discard(obj_id)
            cache.release(str(path), got)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)
    for t in threads:
        assert not t.is_alive()

    assert violations == []
    assert len(cache) <= cache.max_entries


def test_thread_safety_many_keys_no_crash_and_bounded_size(tmp_path):
    """Broader smoke test across several distinct keys at once: concurrent
    checkout/release traffic on a handful of different scores must not
    raise and must never leave the cache holding more than max_entries.
    """
    cache = score_cache.ScoreCache(max_entries=3)
    paths = []
    for i in range(6):
        path = tmp_path / f"s{i}.musicxml"
        _write_score(path)
        paths.append(str(path))
        cache.release(paths[i], m21.converter.parse(paths[i]))

    errors: list[Exception] = []
    stop_at = time.monotonic() + 1.0

    def worker() -> None:
        try:
            while time.monotonic() < stop_at:
                for p in paths:
                    got = cache.checkout(p)
                    if got is not None:
                        cache.release(p, got)
        except Exception as exc:  # pragma: no cover - failure path only
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert errors == []
    assert len(cache) <= cache.max_entries
