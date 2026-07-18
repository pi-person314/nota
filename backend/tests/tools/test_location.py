"""Unit tests for nota.mcp_server.location, exercised directly against
in-memory music21 Score objects rather than through a tool call, so they
can pin down `resolve_part`'s matching/error-hint behavior precisely.
"""

from __future__ import annotations

import pytest

from nota.mcp_server import location
from nota.mcp_server.errors import ErrorCode, ToolError

from .musicxml_builders import build_duplicate_violin_names, build_simple_4_4


def test_resolve_part_none_returns_first_part():
    score = build_simple_4_4()
    assert location.resolve_part(score, None) is score.parts[0]


def test_resolve_part_unique_name_still_works():
    score = build_simple_4_4()
    assert location.resolve_part(score, "Violin") is score.parts[0]


def test_resolve_part_unknown_name_raises_with_hint():
    score = build_simple_4_4()
    with pytest.raises(ToolError) as excinfo:
        location.resolve_part(score, "Tuba")
    assert excinfo.value.code == ErrorCode.PART_NOT_FOUND
    assert "Violin" in excinfo.value.message


def test_resolve_part_bare_ambiguous_name_resolves_to_first_match():
    """Pinned behavior: plain "Violin" against a score with two same-named
    parts keeps resolving to the first one, not erroring.
    """
    score = build_duplicate_violin_names()
    resolved = location.resolve_part(score, "Violin")
    assert resolved is score.parts[0]


def test_resolve_part_ordinal_alias_reaches_second_duplicate():
    score = build_duplicate_violin_names()
    resolved = location.resolve_part(score, "Violin 2")
    assert resolved is score.parts[1]


def test_resolve_part_ordinal_alias_first_still_matches_first():
    score = build_duplicate_violin_names()
    resolved = location.resolve_part(score, "Violin 1")
    assert resolved is score.parts[0]


def test_resolve_part_ordinal_alias_is_case_and_whitespace_insensitive():
    score = build_duplicate_violin_names()
    assert location.resolve_part(score, "violin 2") is score.parts[1]
    assert location.resolve_part(score, "  VIOLIN   2  ") is score.parts[1]


def test_resolve_part_unrelated_duplicate_name_unaffected():
    """Parts with unique names (Viola, Violoncello) are unaffected by the
    Violin/Violin duplication elsewhere in the same score.
    """
    score = build_duplicate_violin_names()
    assert location.resolve_part(score, "Viola") is score.parts[2]
    assert location.resolve_part(score, "Violoncello") is score.parts[3]


def test_resolve_part_not_found_hint_lists_ordinal_aliases_not_dedup():
    score = build_duplicate_violin_names()
    with pytest.raises(ToolError) as excinfo:
        location.resolve_part(score, "Tuba")
    message = excinfo.value.message
    assert "Violin 1" in message
    assert "Violin 2" in message
    assert "Viola" in message
    assert "Violoncello" in message


def test_display_part_names_aliases_only_duplicates():
    score = build_duplicate_violin_names()
    names = location.display_part_names(list(score.parts))
    assert names == ["Violin 1", "Violin 2", "Viola", "Violoncello"]


def test_display_part_names_no_duplicates_returns_plain_names():
    score = build_simple_4_4()
    names = location.display_part_names(list(score.parts))
    assert names == ["Violin"]
