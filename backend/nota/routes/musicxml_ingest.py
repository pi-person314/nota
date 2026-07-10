"""MusicXML upload ingestion: safe .mxl decompression, XXE-safe XML
validation, and score metadata extraction.

Kept separate from the upload route handler so the security-sensitive
parsing logic can be unit tested directly, without going through Flask
request/response plumbing. Nothing here touches the database or the
filesystem beyond reading the uploaded bytes; the route handler is
responsible for persisting the results.
"""

from __future__ import annotations

import io
import os
import zipfile
from dataclasses import dataclass

import defusedxml.ElementTree as defused_ET
import music21 as m21
from music21.musicxml.m21ToXml import GeneralObjectExporter

ALLOWED_EXTENSIONS = {".musicxml", ".xml", ".mxl"}

# Cap on the *uncompressed* size of a .mxl archive's contents, independent
# of the raw upload size limit. A small compressed file can still expand
# to an enormous document (a "zip bomb"); this bounds that regardless of
# how small the upload itself was.
MAX_MXL_UNCOMPRESSED_BYTES = 50 * 1024 * 1024


class UploadRejected(Exception):
    """Raised for any upload that must be rejected with a 4xx response.

    Carries the HTTP status and the machine-readable error code/message
    pair the route handler turns directly into the standard error JSON
    body, so every rejection reason in this module is expressed once.
    """

    def __init__(self, code: str, message: str, status: int = 422):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


@dataclass
class ScoreMetadata:
    canonical_xml: str
    display_name: str
    part_name: str | None
    measure_count: int
    has_pickup: bool
    parts: list[dict]
    time_signatures: list[dict]


def extension_of(filename: str) -> str:
    return os.path.splitext(filename or "")[1].lower()


def extract_source_xml(filename: str, raw_bytes: bytes) -> str:
    """Return the raw MusicXML text for an upload.

    Dispatches on file extension: `.mxl` archives are decompressed (see
    `_extract_mxl`); `.musicxml`/`.xml` are decoded as UTF-8 text directly.
    Raises `UploadRejected` for unsupported extensions or invalid text.
    """
    ext = extension_of(filename)
    if ext not in ALLOWED_EXTENSIONS:
        raise UploadRejected(
            "UNSUPPORTED_FILE_TYPE",
            "Only .musicxml, .xml, and .mxl files are accepted.",
        )

    if ext == ".mxl":
        return _extract_mxl(raw_bytes)

    try:
        return raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise UploadRejected("INVALID_XML", "File is not valid UTF-8 text.") from exc


def _extract_mxl(raw_bytes: bytes) -> str:
    """Decompress a .mxl (compressed MusicXML) archive.

    Follows the MusicXML container convention: `META-INF/container.xml`
    names the root MusicXML entry via a `<rootfile full-path="...">`
    element. Archive entry sizes are read from the zip central directory
    (`ZipInfo.file_size`) and checked against the uncompressed size cap
    *before* any entry is extracted, so a small malicious archive can't
    force a large decompression before being rejected.
    """
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw_bytes))
    except zipfile.BadZipFile as exc:
        raise UploadRejected("MALFORMED_MXL", "File is not a valid .mxl archive.") from exc

    try:
        infos = archive.infolist()
        names = set(archive.namelist())
    except (zipfile.BadZipFile, NotImplementedError) as exc:
        raise UploadRejected("MALFORMED_MXL", "File is not a valid .mxl archive.") from exc

    total_uncompressed = sum(info.file_size for info in infos)
    if total_uncompressed > MAX_MXL_UNCOMPRESSED_BYTES:
        raise UploadRejected("ARCHIVE_TOO_LARGE", "Archive expands to more than 50 MB.")

    if "META-INF/container.xml" not in names:
        raise UploadRejected(
            "MALFORMED_MXL", "Archive is missing META-INF/container.xml."
        )

    try:
        container_bytes = archive.read("META-INF/container.xml")
    except (KeyError, zipfile.BadZipFile, RuntimeError) as exc:
        raise UploadRejected(
            "MALFORMED_MXL", "Archive is missing META-INF/container.xml."
        ) from exc

    try:
        container_root = defused_ET.fromstring(container_bytes)
    except Exception as exc:
        raise UploadRejected("MALFORMED_MXL", "container.xml is not valid XML.") from exc

    rootfile_el = container_root.find(".//rootfile")
    root_path = rootfile_el.get("full-path") if rootfile_el is not None else None
    if not root_path:
        raise UploadRejected("MALFORMED_MXL", "container.xml does not name a rootfile.")

    if root_path not in names:
        raise UploadRejected(
            "MALFORMED_MXL", f"container.xml references missing entry '{root_path}'."
        )

    root_info = archive.getinfo(root_path)
    if root_info.file_size > MAX_MXL_UNCOMPRESSED_BYTES:
        raise UploadRejected("ARCHIVE_TOO_LARGE", "Archive expands to more than 50 MB.")

    try:
        raw = archive.read(root_path)
    except (zipfile.BadZipFile, RuntimeError) as exc:
        raise UploadRejected("MALFORMED_MXL", "Archive entry could not be read.") from exc

    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise UploadRejected("INVALID_XML", "Archive entry is not valid UTF-8 text.") from exc


def validate_xml_safe(text: str) -> None:
    """Reject XXE / entity-expansion payloads before handing text to music21.

    `defusedxml` refuses any DOCTYPE that declares or references an
    entity (including external entities and "billion laughs" style
    internal-entity expansion), while still accepting the harmless
    DOCTYPE real MusicXML exporters emit (a bare DTD reference with no
    ENTITY declarations). music21's own parser has no such protection, so
    this check must run first, on the original text.
    """
    try:
        defused_ET.fromstring(text.encode("utf-8"))
    except defused_ET.ParseError as exc:
        raise UploadRejected("INVALID_XML", f"File is not valid XML: {exc}") from exc
    except Exception as exc:
        # defusedxml raises dedicated types for unsafe content
        # (EntitiesForbidden, ExternalReferenceForbidden, DTDForbidden,
        # ...); any of them means the upload must be rejected.
        raise UploadRejected(
            "UNSAFE_XML", f"File contains disallowed XML content: {exc}"
        ) from exc


def parse_score_metadata(text: str, filename: str) -> ScoreMetadata:
    """Parse already-validated MusicXML text with music21 and extract the
    metadata persisted on the Score row, plus the canonical (uncompressed,
    normalized) MusicXML text to store on disk.
    """
    try:
        parsed = m21.converter.parseData(text, format="musicxml")
    except Exception as exc:
        raise UploadRejected(
            "INVALID_MUSICXML", f"music21 could not parse this file: {exc}"
        ) from exc

    parts_stream = parsed.parts if hasattr(parsed, "parts") else []
    if len(parts_stream) == 0:
        raise UploadRejected("INVALID_MUSICXML", "Score has no parts.")

    parts: list[dict] = []
    for part in parts_stream:
        instrument = part.getInstrument(returnDefault=True)
        part_id = instrument.partId or part.id or f"P{len(parts) + 1}"
        part_display_name = instrument.partName or part.partName or part_id
        parts.append({"id": part_id, "name": part_display_name})

    first_part = parts_stream[0]
    measures = list(first_part.getElementsByClass(m21.stream.Measure))
    measure_count = len(measures)

    has_pickup = False
    if measures:
        first_measure = measures[0]
        has_pickup = first_measure.number == 0 or (first_measure.paddingLeft or 0) > 0

    time_signatures: list[dict] = []
    last_ts_seen: str | None = None
    for measure in measures:
        ts = measure.timeSignature
        if ts is None:
            continue
        ts_str = ts.ratioString
        if ts_str != last_ts_seen:
            time_signatures.append({"measure": measure.number, "ts": ts_str})
            last_ts_seen = ts_str

    if not time_signatures:
        # No <time> element directly on any measure (unusual, but not
        # invalid) — fall back to whatever time signature music21 infers
        # for the part so the map is never empty for a real score.
        inferred = list(first_part.recurse().getElementsByClass(m21.meter.TimeSignature))
        if inferred:
            time_signatures.append(
                {
                    "measure": measures[0].number if measures else 1,
                    "ts": inferred[0].ratioString,
                }
            )

    title = None
    if parsed.metadata is not None:
        title = parsed.metadata.title or parsed.metadata.movementName
    fallback_name = os.path.splitext(os.path.basename(filename or ""))[0]
    display_name = (title or "").strip() or fallback_name or "Untitled Score"

    canonical_bytes = GeneralObjectExporter(parsed).parse()
    canonical_xml = canonical_bytes.decode("utf-8")

    return ScoreMetadata(
        canonical_xml=canonical_xml,
        display_name=display_name,
        part_name=parts[0]["name"] if parts else None,
        measure_count=measure_count,
        has_pickup=has_pickup,
        parts=parts,
        time_signatures=time_signatures,
    )


def ingest_upload(filename: str, raw_bytes: bytes) -> ScoreMetadata:
    """Full pipeline: extension check -> .mxl decompression -> XXE-safe
    validation -> music21 parse -> metadata extraction. Raises
    `UploadRejected` at the first failing step.
    """
    source_xml = extract_source_xml(filename, raw_bytes)
    validate_xml_safe(source_xml)
    return parse_score_metadata(source_xml, filename)
