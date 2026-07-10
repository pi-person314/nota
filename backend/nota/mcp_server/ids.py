"""xml:id generation for elements a notation tool creates or touches.

music21's MusicXML writer exports an element's `.id` attribute as `xml:id`
only when it has been explicitly set to a string; a freshly-constructed
music21 object's default `.id` is an interpreter-internal integer and is
never written out. Because the MCP server is stateless and re-parses the
score from disk on every call, music21 also does not read `xml:id` values
back in on parse — so there is no way to recover a previously-assigned id
for an element across calls. Every call that wants to report an id must
mint a fresh one for whatever it created or touched in that call.
"""

from __future__ import annotations

import uuid

import music21 as m21


def new_id() -> str:
    """Return a fresh id in the `nota-xxxxxxxx` form used for every
    xml:id a tool assigns.
    """
    return f"nota-{uuid.uuid4().hex[:8]}"


def assign_id(element) -> str:
    """Assign a fresh id to a music21 note-like element and return it.

    Used both for elements a tool creates outright (a new Dynamic) and for
    existing elements a tool merely attaches something to (a note gaining
    an articulation) — in the latter case the note is being reported as
    "changed" for highlighting purposes, so it needs an id too.

    Chords need special handling: music21's MusicXML writer expands a
    Chord into one `<note>` element per pitch and reads each element's id
    from the corresponding entry in `chord.notes` (a stable, cached tuple
    of per-pitch Note objects) rather than from the Chord object itself —
    `chord.id` is silently dropped on export. Setting the id on the first
    of those per-pitch notes is what actually survives serialization, and
    a chord is treated as a single target anyway, so that one id is
    sufficient to identify it for highlighting.
    """
    if isinstance(element, m21.chord.Chord):
        target = element.notes[0]
    else:
        target = element
    target.id = new_id()
    return target.id
