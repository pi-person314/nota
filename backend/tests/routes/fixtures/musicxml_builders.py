"""Builders for small in-memory music21 scores used by the route tests.

These build real, valid MusicXML via music21 (rather than hand-writing XML
strings) so upload/metadata-extraction tests exercise the same code paths
real uploads do. Kept under tests/routes/fixtures/ rather than
tests/routes/conftest.py since they're plain builder functions, not
pytest fixtures.
"""

from __future__ import annotations

import io
import zipfile

from music21 import metadata, meter, note, stream


def simple_score_bytes(title: str = "Test Piece") -> bytes:
    """A single 4/4 part, one measure, no pickup."""
    s = stream.Score()
    part = stream.Part()
    part.id = "P1"
    part.partName = "Violin"
    m1 = stream.Measure(number=1)
    m1.append(meter.TimeSignature("4/4"))
    m1.append(note.Note("C4", type="whole"))
    part.append(m1)
    s.insert(0, part)
    s.metadata = metadata.Metadata()
    s.metadata.title = title
    return _write_musicxml_bytes(s)


def meter_change_score_bytes(title: str = "Meter Change Piece") -> bytes:
    """Three measures: 4/4, 4/4, then a mid-piece change to 3/4 — for
    time-signature-map extraction tests.
    """
    s = stream.Score()
    part = stream.Part()
    part.id = "P1"
    part.partName = "Flute"

    m1 = stream.Measure(number=1)
    m1.append(meter.TimeSignature("4/4"))
    m1.append(note.Note("C5", type="whole"))
    part.append(m1)

    m2 = stream.Measure(number=2)
    m2.append(note.Note("D5", type="whole"))
    part.append(m2)

    m3 = stream.Measure(number=3)
    m3.append(meter.TimeSignature("3/4"))
    m3.append(note.Note("E5", type="half"))
    m3.append(note.Note("F5", type="quarter"))
    part.append(m3)

    s.insert(0, part)
    s.metadata = metadata.Metadata()
    s.metadata.title = title
    return _write_musicxml_bytes(s)


def pickup_score_bytes(title: str = "Pickup Piece") -> bytes:
    """A pickup (anacrusis) measure numbered 0, followed by one full measure."""
    s = stream.Score()
    part = stream.Part()
    part.id = "P1"
    part.partName = "Oboe"

    pickup = stream.Measure(number=0)
    pickup.paddingLeft = 3.0
    pickup.append(meter.TimeSignature("4/4"))
    pickup.append(note.Note("C5", type="quarter"))
    part.append(pickup)

    m1 = stream.Measure(number=1)
    m1.append(note.Note("D5", type="whole"))
    part.append(m1)

    s.insert(0, part)
    s.metadata = metadata.Metadata()
    s.metadata.title = title
    return _write_musicxml_bytes(s)


def two_part_score_bytes(title: str = "Two Part Piece") -> bytes:
    s = stream.Score()

    p1 = stream.Part()
    p1.id = "P1"
    p1.partName = "Violin I"
    m1 = stream.Measure(number=1)
    m1.append(meter.TimeSignature("4/4"))
    m1.append(note.Note("C4", type="whole"))
    p1.append(m1)
    s.insert(0, p1)

    p2 = stream.Part()
    p2.id = "P2"
    p2.partName = "Violin II"
    m2 = stream.Measure(number=1)
    m2.append(meter.TimeSignature("4/4"))
    m2.append(note.Note("G3", type="whole"))
    p2.append(m2)
    s.insert(0, p2)

    s.metadata = metadata.Metadata()
    s.metadata.title = title
    return _write_musicxml_bytes(s)


def _write_musicxml_bytes(score: stream.Score) -> bytes:
    from music21.musicxml.m21ToXml import GeneralObjectExporter

    return GeneralObjectExporter(score).parse()


def zip_mxl_bytes(musicxml_bytes: bytes, inner_name: str = "score.musicxml") -> bytes:
    """Wrap raw MusicXML bytes in a well-formed .mxl (compressed MusicXML)
    archive, matching the container.xml convention real .mxl files use.
    """
    container_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<container>\n"
        "  <rootfiles>\n"
        f'    <rootfile full-path="{inner_name}"/>\n'
        "  </rootfiles>\n"
        "</container>\n"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(inner_name, musicxml_bytes)
        zf.writestr("META-INF/container.xml", container_xml)
    return buf.getvalue()


XXE_PAYLOAD = b"""<?xml version="1.0"?>
<!DOCTYPE score-partwise [ <!ENTITY xxe SYSTEM "file:///etc/passwd"> ]>
<score-partwise version="4.0">
  <part-list><score-part id="P1"><part-name>&xxe;</part-name></score-part></part-list>
  <part id="P1"><measure number="1"><note><rest/><duration>4</duration></note></measure></part>
</score-partwise>
"""

BILLION_LAUGHS_PAYLOAD = b"""<?xml version="1.0"?>
<!DOCTYPE lolz [
 <!ENTITY lol "lol">
 <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
 <!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">
 <!ENTITY lol4 "&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;">
]>
<score-partwise version="4.0">&lol4;</score-partwise>
"""


def zip_bomb_mxl_bytes() -> bytes:
    """A well-formed .mxl archive whose declared uncompressed size exceeds
    the 50 MB cap, but whose compressed size is tiny (highly compressible
    repeated content) — the "zip bomb" shape the upload pipeline must
    reject before fully decompressing.
    """
    huge_payload = b"<!-- 0 -->" * 8_000_000  # ~80 MB uncompressed, compresses tiny
    container_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<container>\n"
        "  <rootfiles>\n"
        '    <rootfile full-path="score.musicxml"/>\n'
        "  </rootfiles>\n"
        "</container>\n"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("score.musicxml", huge_payload)
        zf.writestr("META-INF/container.xml", container_xml)
    return buf.getvalue()


def malformed_mxl_missing_container_bytes(musicxml_bytes: bytes) -> bytes:
    """A .mxl-shaped zip archive with no META-INF/container.xml entry."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("score.musicxml", musicxml_bytes)
    return buf.getvalue()
