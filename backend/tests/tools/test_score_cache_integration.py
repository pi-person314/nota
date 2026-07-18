"""Integration tests proving `score_cache` is wired into the harness
correctly: repeated non-mutating calls (rejected validation, no-ops) are
served from the cache instead of re-parsing, and -- the property that
actually matters -- a real tool-call sequence produces identical results
whether the cache is on or off.

Uses the same `make_score`/`storage_env` fixtures as the rest of this
directory (see `conftest.py`), so each test gets its own isolated temp
DB/storage dir and score file.
"""

from __future__ import annotations

import re

import music21 as m21
import pytest

from nota import storage
from nota.mcp_server import tools
from nota.mcp_server.errors import ErrorCode
from nota.services import score_cache

from .assertions import assert_error, assert_success

_ID_PATTERN = re.compile(r'id="nota-[0-9a-f]+"')


def _normalize(xml: str) -> str:
    """Strip the randomly-generated xml:id values `ids.assign_id` mints so
    two independently-run tool-call sequences can be compared for
    "same musical content", ignoring the ids that are expected to differ
    between separate runs (see `nota/mcp_server/ids.py`).
    """
    return _ID_PATTERN.sub('id="ID"', xml)


@pytest.fixture(autouse=True)
def _reset_process_wide_cache():
    """`score_cache` is a process-wide singleton (see its own module
    docstring for why); every test here sets it explicitly, and this
    fixture resets it afterward so later tests in the same pytest session
    aren't affected by whatever configuration ran here.
    """
    yield
    score_cache._cache = None
    score_cache._configured = False


@pytest.fixture
def counting_parse(monkeypatch):
    """Patch `music21.converter.parse` to keep counting/still delegate to
    the real implementation, so tests can assert on how many times the
    harness actually re-parsed from disk without relying on wall-clock
    timing (which would be flaky in CI).
    """
    real_parse = m21.converter.parse
    calls: list[str] = []

    def wrapper(*args, **kwargs):
        calls.append(args[0] if args else kwargs.get("value"))
        return real_parse(*args, **kwargs)

    monkeypatch.setattr(m21.converter, "parse", wrapper)
    return calls


def test_repeated_rejected_calls_are_served_from_cache_when_enabled(
    make_score, counting_parse
):
    score_cache.configure(max_entries=4)
    sid = make_score("simple_4_4")

    first = tools.add_dynamic(sid, measure=999, beat=1, dynamic="f")
    assert_error(first, ErrorCode.MEASURE_OUT_OF_RANGE)
    assert len(counting_parse) == 1

    counting_parse.clear()
    second = tools.add_dynamic(sid, measure=999, beat=1, dynamic="f")
    assert_error(second, ErrorCode.MEASURE_OUT_OF_RANGE)
    # Second call hits the object the first call's failed validation
    # released back into the cache -- no reparse needed.
    assert len(counting_parse) == 0


def test_repeated_rejected_calls_always_reparse_when_disabled(make_score, counting_parse):
    score_cache.configure(max_entries=0)
    sid = make_score("simple_4_4")

    tools.add_dynamic(sid, measure=999, beat=1, dynamic="f")
    assert len(counting_parse) == 1

    counting_parse.clear()
    tools.add_dynamic(sid, measure=999, beat=1, dynamic="f")
    assert len(counting_parse) == 1


def test_repeated_no_ops_are_served_from_cache_when_enabled(make_score, counting_parse):
    score_cache.configure(max_entries=4)
    sid = make_score("simple_4_4")

    # Establishes the dynamic; this call mutates and writes, so it is
    # never released into the cache (see score_cache.py's module
    # docstring on why the mutating path is excluded).
    established = tools.add_dynamic(sid, measure=1, beat=1, dynamic="f")
    assert_success(established)

    counting_parse.clear()
    second = tools.add_dynamic(sid, measure=1, beat=1, dynamic="f")
    assert_success(second)
    assert "already present" in second["summary"]
    assert len(counting_parse) == 1  # cache was empty; this call parses and releases

    counting_parse.clear()
    third = tools.add_dynamic(sid, measure=1, beat=1, dynamic="f")
    assert_success(third)
    assert len(counting_parse) == 0  # served from what the second call released


def test_mutating_call_sequence_is_never_reparsed_from_cache(make_score, counting_parse):
    """The dominant real-world pattern -- a run of successive accepted
    edits -- gets no benefit from this cache: every write changes the
    file's mtime/size, invalidating the key the next call would want. This
    pins that (documented, accepted) limitation down so a future change
    doesn't accidentally start trusting a post-mutation object instead.
    """
    score_cache.configure(max_entries=4)
    sid = make_score("simple_4_4")

    tools.add_dynamic(sid, measure=1, beat=1, dynamic="f")
    tools.add_dynamic(sid, measure=2, beat=1, dynamic="p")
    tools.add_dynamic(sid, measure=1, beat=2, dynamic="mf")

    # Every one of the three calls above had to parse fresh: none of them
    # could have been served from a cache entry a prior *mutating* call
    # left behind, because mutating calls never release into the cache.
    assert len(counting_parse) == 3


def _run_mixed_call_sequence(make_score, cache_size: int) -> str:
    """Run a fixed sequence of accepted, no-op, and rejected tool calls
    (the same mix any of these tests wants) against a fresh copy of
    `simple_4_4` with the cache configured to `cache_size`, and return the
    resulting on-disk XML with randomly-minted ids normalized out.
    """
    score_cache.configure(max_entries=cache_size)
    sid = make_score("simple_4_4")

    tools.add_dynamic(sid, measure=1, beat=1, dynamic="f")
    tools.add_articulation(sid, measure=1, beat=1, articulation="staccato")
    tools.add_dynamic(sid, measure=1, beat=1, dynamic="f")  # no-op
    tools.add_dynamic(sid, measure=2, beat=1, dynamic="p")
    bad = tools.add_dynamic(sid, measure=999, beat=1, dynamic="f")  # rejected
    assert_error(bad, ErrorCode.MEASURE_OUT_OF_RANGE)
    tools.remove_notation(sid, measure=1, beat=1, notation_type="dynamic")

    return _normalize(storage.read_xml(sid))


@pytest.mark.parametrize("cache_size", [0, 4])
def test_mixed_call_sequence_succeeds_regardless_of_cache_size(make_score, cache_size):
    """Smoke test that the mixed accepted/no-op/rejected sequence used by
    `test_cache_on_and_cache_off_agree` below runs cleanly and round-trips
    under both a disabled and an enabled cache.
    """
    xml = _run_mixed_call_sequence(make_score, cache_size)
    reparsed = m21.converter.parse(xml.encode("utf-8"), format="musicxml")
    assert reparsed is not None


def test_cache_on_and_cache_off_agree(make_score):
    """The correctness bar for this whole feature: running the exact same
    sequence of accepted, no-op, and rejected tool calls against two fresh
    copies of the same starting score produces the same musical content
    (ids normalized out, since `ids.assign_id` mints a fresh random id on
    every call by design -- see ids.py) regardless of whether the cache is
    enabled.
    """
    off_result = _run_mixed_call_sequence(make_score, cache_size=0)
    on_result = _run_mixed_call_sequence(make_score, cache_size=4)

    assert off_result == on_result
