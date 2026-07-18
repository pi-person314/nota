"""Ordinal disambiguation for parts that share a display name.

A real orchestral score can legitimately have more than one part with the
exact same name in its source MusicXML (e.g. a string quartet's two violin
parts both simply named "Violin", with no "I"/"II" suffix -- observed on a
real corpus score, Beethoven's op. 18 no. 1). music21's own MusicXML writer
compounds this: on export it also collapses each such part's `id` to match
its display name, so after a normal upload round-trip (parse -> write, what
every upload does) the parts are not just same-named but identical on every
field addressing normally matches against.

This module computes, in score order, an ordinal alias ("Violin 1",
"Violin 2", ...) for every part whose name is shared (case-insensitively)
by at least one other part in the same score. A part whose name is unique
gets no alias -- it is already unambiguous and keeps being addressable by
its bare name. Aliases are 1-based and assigned in score order, independent
of anything else about the parts (their ids, clefs, instruments, ...).
"""

from __future__ import annotations

from collections import Counter


def normalize_part_name(name: object) -> str:
    """Case-fold a part name (or alias) for comparison, collapsing any run
    of internal whitespace to a single space so "Violin  2" and "violin 2"
    both match "Violin 2".
    """
    return " ".join(str(name).strip().lower().split())


def assign_ordinal_aliases(names: list[str | None]) -> list[str | None]:
    """Given part display names in score order, return a same-length list
    of ordinal-suffixed aliases ("Violin 1", "Violin 2", ...) for every
    name shared (case-insensitively, whitespace-insensitively) by more than
    one part. A part whose name is unique (or missing/None) passes through
    with `None` in its slot, meaning "no alias needed".
    """
    normalized = [normalize_part_name(n) if n else None for n in names]
    counts = Counter(n for n in normalized if n is not None)

    ordinal_so_far: dict[str, int] = {}
    aliases: list[str | None] = []
    for name, norm in zip(names, normalized):
        if norm is not None and counts[norm] > 1:
            ordinal_so_far[norm] = ordinal_so_far.get(norm, 0) + 1
            aliases.append(f"{str(name).strip()} {ordinal_so_far[norm]}")
        else:
            aliases.append(None)
    return aliases


def display_names(names: list[str | None]) -> list[str]:
    """Given part display names in score order, return the name every part
    should be shown as to a model or user: the ordinal alias where one was
    assigned, the original name otherwise. Never empty for a part that had
    *some* name.
    """
    aliases = assign_ordinal_aliases(names)
    return [alias or (name or "") for name, alias in zip(names, aliases)]
