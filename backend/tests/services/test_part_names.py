"""Unit tests for `nota.services.part_names`."""

from __future__ import annotations

from nota.services.part_names import assign_ordinal_aliases, display_names, normalize_part_name


def test_unique_names_get_no_alias():
    aliases = assign_ordinal_aliases(["Violin", "Viola", "Cello"])
    assert aliases == [None, None, None]


def test_duplicate_names_get_ordinal_aliases_in_score_order():
    aliases = assign_ordinal_aliases(["Violin", "Viola", "Violin", "Cello"])
    assert aliases == ["Violin 1", None, "Violin 2", None]


def test_three_way_duplicate():
    aliases = assign_ordinal_aliases(["Oboe", "Oboe", "Oboe"])
    assert aliases == ["Oboe 1", "Oboe 2", "Oboe 3"]


def test_duplicate_detection_is_case_insensitive():
    aliases = assign_ordinal_aliases(["violin", "VIOLIN"])
    assert aliases == ["violin 1", "VIOLIN 2"]


def test_duplicate_detection_collapses_internal_whitespace():
    """Outer whitespace on the source name is trimmed when building the
    alias, and inputs that only differ by whitespace still count as the
    same name for duplicate-detection purposes.
    """
    aliases = assign_ordinal_aliases(["Violin", "  Violin  "])
    assert aliases == ["Violin 1", "Violin 2"]


def test_none_names_pass_through_without_alias():
    aliases = assign_ordinal_aliases(["Violin", None, "Violin"])
    assert aliases == ["Violin 1", None, "Violin 2"]


def test_display_names_uses_alias_only_where_assigned():
    names = display_names(["Violin", "Viola", "Violin"])
    assert names == ["Violin 1", "Viola", "Violin 2"]


def test_normalize_part_name_collapses_case_and_whitespace():
    assert normalize_part_name("  Violin   2 ") == "violin 2"
    assert normalize_part_name("violin 2") == "violin 2"
    assert normalize_part_name("VIOLIN  2") == "violin 2"
