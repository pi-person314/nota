"""Repairs a music21-specific MusicXML round-trip defect: overlapping
spanner-line direction elements (crescendo/diminuendo hairpins, brackets,
dashes, and octave-shift/ottava lines) whose closing (`type="stop"`)
element is written *before* its own opening element in document order.

Root cause: when several of these spanners are concurrently open within one
part, MusicXML's `number` attribute exists specifically to disambiguate
which simultaneously-open spanner a later `stop` belongs to. On some real
scores, music21's writer reuses a `number` for a new spanner before the
previous spanner using that number has actually closed *in document
order*. The writer still emits a well-formed start/stop pair for every
spanner -- nothing is dropped at write time -- but for the reused number,
the *stop* direction ends up serialized earlier in the file than its own
matching *start* direction. music21's own MusicXML *reader* has no
tolerance for that: it processes directions strictly in document order, so
hitting a stop for a number that isn't currently open logs "Could not
import wedge: ..." (or the bracket/dashes/octave-shift equivalent) and
silently drops that spanner pair on re-parse -- lossy, but bounded to the
mis-ordered pair, and never raises.

This module repairs exactly that shape after music21 has already produced
the (buggy) MusicXML text, by relocating the misplaced opening direction to
just before its stop, and touches nothing else. It was derived from two
concrete cases in the music21-bundled corpus:

- haydn/opus74no1/movement3: 2 of 11 hairpins hit this pattern.
- beethoven/opus133: one bracket ("Line") spanner hits the identical
  pattern -- confirmed by generalizing the same detection/repair to
  `<bracket>` and observing it fires correctly against real data, which is
  why `<bracket>` is handled below alongside `<wedge>`.

In both confirmed cases, the orphaned stop sits at the very end of one
measure and its true start sits at the very beginning of the next measure
-- the two elements mark the exact same instant in the music (no note,
`<backup>`, or `<forward>` separates them), so the matching criterion here
is not "same measure, same offset" but same *effective offset*: a running
duration count kept per part, advanced by every non-chord `<note>` and by
`<forward>`/`<backup>`, that does not reset at measure boundaries. A stop
for a currently-unopened spanner number is only reordered when a start for
that exact number is found later in the same part at that same running
offset (and no `<divisions>` change lies between them, since raw duration
units aren't comparable across a divisions change). Anything else -- no
later start at all, a later start at a different offset, or another
stop/continue for the same number occurring first -- is left alone, since
it isn't provably the same defect.

`<dashes>` and `<octave-shift>` (MusicXML's ottava marking) share the exact
same `direction`/`number`/`type` shape as `<bracket>` and are handled by
the same code path on the chance they exhibit the same defect (not
independently confirmed against a corpus example, unlike wedge and
bracket, but structurally identical). `<pedal>` was deliberately left out:
its `type` vocabulary (start/stop/sostenuto/change/continue) doesn't
reduce to a clean start/stop binary the way the other four do, so folding
it into the same conservative matching logic would not be safe.

Only whole `<direction>` elements that contain *nothing but* the spanner
element itself (plus optionally `<staff>`/`<voice>`) are ever moved -- a
`<direction>` that also carries a `<sound>`, an `<offset>`, or another
direction-type is left untouched even when it is half of an otherwise
broken pair, since moving it could relocate unrelated content along with
it.
"""

from __future__ import annotations

from xml.parsers import expat

# Spanner-line elements that use MusicXML's `number`/`type` disambiguation
# convention (direction/direction-type/<tag number="N" type="...">), keyed
# by tag name -> the `type` values that open a new spanner of that kind.
# Every kind's stop is literally `type="stop"`.
_SPANNER_START_TYPES: dict[str, frozenset[str]] = {
    "wedge": frozenset({"crescendo", "diminuendo"}),
    "bracket": frozenset({"start"}),
    "dashes": frozenset({"start"}),
    "octave-shift": frozenset({"up", "down"}),
}
_STOP_TYPE = "stop"
_CONTINUE_TYPE = "continue"

# Direction children tolerated alongside the recognized spanner's own
# <direction-type> without disqualifying a <direction> from being moved.
_HARMLESS_DIRECTION_CHILDREN = frozenset({"direction-type", "staff", "voice"})


class _Slot:
    """One recognized spanner direction, in the document order it was
    found. `start`/`end` are byte offsets into the source bytes spanning
    the whole enclosing `<direction>...</direction>` element.
    """

    __slots__ = ("tag", "number", "kind", "offset", "divisions_epoch", "start", "end", "is_simple")

    def __init__(self, tag, number, kind, offset, divisions_epoch, start, end, is_simple):
        self.tag = tag
        self.number = number
        self.kind = kind  # "start" | "stop" | "continue"
        self.offset = offset
        self.divisions_epoch = divisions_epoch
        self.start = start
        self.end = end
        self.is_simple = is_simple


class _PartState:
    def __init__(self):
        self.offset = 0
        self.divisions: int | None = None
        self.divisions_epoch = 0
        self.slots: list[_Slot] = []


def repair_spanner_order(xml_text: str) -> str:
    """Return `xml_text` with any provable stop-before-start spanner
    inversion (see module docstring) reordered, or `xml_text` itself,
    completely unchanged, if nothing needs fixing -- including if the
    document can't be analyzed for any reason (malformed XML, an
    unexpected shape). Callers can always treat the result as safe to
    write in place of the input.
    """
    if not any(f"<{tag}" in xml_text for tag in _SPANNER_START_TYPES):
        return xml_text

    try:
        xml_bytes = xml_text.encode("utf-8")
        parts = _scan(xml_bytes)
    except Exception:
        return xml_text

    moves: list[tuple[int, int, int]] = []
    for state in parts.values():
        moves.extend(_find_moves(state.slots))

    if not moves:
        return xml_text

    try:
        repaired_bytes = _apply_moves(xml_bytes, moves)
        return repaired_bytes.decode("utf-8")
    except Exception:
        return xml_text


def _classify(tag: str, type_value: str | None) -> str | None:
    if type_value is None:
        return None
    if type_value == _STOP_TYPE:
        return "stop"
    if type_value == _CONTINUE_TYPE:
        return "continue"
    if type_value in _SPANNER_START_TYPES.get(tag, ()):
        return "start"
    return None


def _scan(xml_bytes: bytes) -> dict[str, _PartState]:
    """Walk `xml_bytes` with expat, returning {part_id: _PartState} with
    every recognized spanner direction recorded as a `_Slot`, in document
    order per part.
    """
    parser = expat.ParserCreate()
    parts: dict[str, _PartState] = {}

    tag_stack: list[str] = []
    current_part: list[_PartState | None] = [None]

    # Direction-scanning state, meaningful only while inside a <direction>
    # (direction elements never nest, so a single record suffices).
    direction = {
        "active": False,
        "start": None,
        "offset": 0,
        "divisions_epoch": 0,
        "base_depth": 0,
        "children": [],  # direct children of <direction>
        "type_children": [],  # direct children of its one <direction-type>
        "spanner": None,  # (tag, number, type) of a recognized spanner child
    }

    note_chord_stack: list[bool] = []
    capture: dict[str, object] = {"target": None, "chars": []}

    def start_element(name, attrs):
        tag_stack.append(name)

        if name == "part":
            pid = attrs.get("id") or f"part-{len(parts)}"
            state = parts.setdefault(pid, _PartState())
            current_part[0] = state
            return

        part = current_part[0]

        if name == "direction":
            direction["active"] = True
            direction["start"] = parser.CurrentByteIndex
            direction["offset"] = part.offset if part is not None else 0
            direction["divisions_epoch"] = part.divisions_epoch if part is not None else 0
            direction["base_depth"] = len(tag_stack)
            direction["children"] = []
            direction["type_children"] = []
            direction["spanner"] = None
            return

        if direction["active"]:
            depth = len(tag_stack) - direction["base_depth"]
            if depth == 1:
                direction["children"].append(name)
            elif depth == 2 and direction["children"] and direction["children"][-1] == "direction-type":
                direction["type_children"].append(name)
                if name in _SPANNER_START_TYPES and direction["spanner"] is None:
                    direction["spanner"] = (name, attrs.get("number", "1"), attrs.get("type"))
            return

        if name == "note":
            note_chord_stack.append(False)
            return
        if name == "chord" and note_chord_stack:
            note_chord_stack[-1] = True
            return
        if name in ("duration", "divisions"):
            capture["target"] = name
            capture["chars"] = []
            return

    def end_element(name):
        part = current_part[0]

        if direction["active"] and name == "direction":
            end_tag = b"</direction>"
            idx = xml_bytes.find(end_tag, direction["start"])
            end = idx + len(end_tag) if idx != -1 else parser.CurrentByteIndex
            if part is not None and direction["spanner"] is not None:
                tag, number, type_value = direction["spanner"]
                kind = _classify(tag, type_value)
                is_simple = (
                    bool(direction["children"])
                    and all(c in _HARMLESS_DIRECTION_CHILDREN for c in direction["children"])
                    and direction["children"].count("direction-type") == 1
                    and direction["type_children"] == [tag]
                )
                if kind is not None:
                    part.slots.append(
                        _Slot(
                            tag=tag,
                            number=number,
                            kind=kind,
                            offset=direction["offset"],
                            divisions_epoch=direction["divisions_epoch"],
                            start=direction["start"],
                            end=end,
                            is_simple=is_simple,
                        )
                    )
            direction["active"] = False
            direction["start"] = None
            tag_stack.pop()
            return

        if direction["active"]:
            tag_stack.pop()
            return

        if name == "part":
            current_part[0] = None
            tag_stack.pop()
            return

        if name == "note":
            if note_chord_stack:
                note_chord_stack.pop()
            tag_stack.pop()
            return

        if name in ("duration", "divisions") and capture["target"] == name:
            text = "".join(capture["chars"]).strip()
            capture["target"] = None
            capture["chars"] = []
            tag_stack.pop()
            if not text or part is None:
                return
            try:
                value = int(text)
            except ValueError:
                return
            if name == "divisions":
                if part.divisions is not None and value != part.divisions:
                    part.divisions_epoch += 1
                part.divisions = value
                return
            # name == "duration": only note/backup/forward advance the
            # running offset -- anything else (e.g. a rare standalone
            # <figured-bass> duration) is deliberately ignored, per the
            # module docstring's note on staying conservative.
            parent = tag_stack[-1] if tag_stack else None
            if parent == "note":
                if not (note_chord_stack and note_chord_stack[-1]):
                    part.offset += value
            elif parent == "forward":
                part.offset += value
            elif parent == "backup":
                part.offset -= value
            return

        tag_stack.pop()

    def char_data(data):
        if capture["target"] is not None:
            capture["chars"].append(data)

    parser.StartElementHandler = start_element
    parser.EndElementHandler = end_element
    parser.CharacterDataHandler = char_data
    parser.Parse(xml_bytes, True)

    return parts


def _find_moves(slots: list[_Slot]) -> list[tuple[int, int, int]]:
    """Given one part's spanner slots in document order, return
    `(cut_start, cut_end, insert_before)` byte-offset triples: the
    `[cut_start:cut_end)` span (a misplaced start direction) should be
    removed from its current location and reinserted immediately before
    offset `insert_before` (its true stop's start offset).
    """
    moves: list[tuple[int, int, int]] = []
    open_keys: set[tuple[str, str]] = set()
    consumed: set[int] = set()

    for i, slot in enumerate(slots):
        if i in consumed:
            continue
        key = (slot.tag, slot.number)

        if slot.kind == "start":
            open_keys.add(key)
        elif slot.kind == "continue":
            continue
        elif slot.kind == "stop":
            if key in open_keys:
                open_keys.discard(key)
                continue

            # Orphan stop: search forward for the next slot sharing this
            # (tag, number). Only a same-offset `start` found there,
            # before any other stop/continue for the same key intervenes,
            # counts as a provable inversion.
            for j in range(i + 1, len(slots)):
                other = slots[j]
                if (other.tag, other.number) != key:
                    continue
                if (
                    other.kind == "start"
                    and other.is_simple
                    and slot.is_simple
                    and other.divisions_epoch == slot.divisions_epoch
                    and other.offset == slot.offset
                ):
                    moves.append((other.start, other.end, slot.start))
                    consumed.add(j)
                break

    return moves


def _apply_moves(xml_bytes: bytes, moves: list[tuple[int, int, int]]) -> bytes:
    """Apply a batch of non-overlapping `(cut_start, cut_end,
    insert_before)` relocations to `xml_bytes` in a single left-to-right
    pass, returning the resulting bytes.
    """
    inserts: dict[int, list[bytes]] = {}
    cut_starts: dict[int, int] = {}
    boundary_set = {0, len(xml_bytes)}
    for cut_start, cut_end, insert_before in moves:
        inserts.setdefault(insert_before, []).append(xml_bytes[cut_start:cut_end])
        cut_starts[cut_start] = cut_end
        boundary_set.update((cut_start, cut_end, insert_before))
    boundaries = sorted(boundary_set)

    out: list[bytes] = []
    pos = 0
    bi = 0
    length = len(xml_bytes)
    while pos < length:
        if pos in inserts:
            out.extend(inserts[pos])
        cut_end = cut_starts.get(pos)
        if cut_end is not None:
            pos = cut_end
            continue
        while boundaries[bi] <= pos:
            bi += 1
        nxt = boundaries[bi]
        out.append(xml_bytes[pos:nxt])
        pos = nxt
    if length in inserts:
        out.extend(inserts[length])
    return b"".join(out)
