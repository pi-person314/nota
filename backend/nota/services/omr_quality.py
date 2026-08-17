"""Heuristics for judging whether Audiveris optical music recognition (OMR)
output is usable, or garbled enough that recognition effectively failed.

Audiveris can "succeed" (exit cleanly, produce a MusicXML file) on a scan
it mostly couldn't read -- a blank or near-blank page, a scan too noisy to
transcribe -- and hand back a document that parses fine but contains
little or no actual music. This module looks at the shape of the already-
ingested MusicXML (empty measures, note counts, part agreement) to catch
that case and let the upload route reject it outright, or at least warn
the user, rather than silently saving a mangled score.

By the time `assess_omr_output` runs, its input has already been through
the ingest pipeline's XXE-safe validation and been re-exported by music21
into the score's canonical on-disk form, so it is trusted, well-formed XML.
Parsing it here with the standard library's `xml.etree.ElementTree` --
which offers no protection against hostile XML -- is safe only because of
that: nothing in this module should ever be pointed at unvalidated input.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass

# A score counts as failed recognition outright when it has no sounded
# notes at all, or when it has enough measures to judge and nearly all of
# them are empty. MIN_MEASURES_FOR_EMPTY_REJECT guards against rejecting a
# tiny, genuinely mostly-rest score on ratio alone.
EMPTY_MEASURE_REJECT_FRACTION = 0.9
MIN_MEASURES_FOR_EMPTY_REJECT = 4

# Below this, the score is still accepted but the user is warned.
EMPTY_MEASURE_WARN_FRACTION = 0.4
MIN_SOUNDED_NOTES_WARN = 8


@dataclass
class QualityReport:
    acceptable: bool
    warnings: list[str]


def _is_sounded_note(note_el: ET.Element) -> bool:
    """A <note> is "sounded" unless it has a direct <rest> child."""
    return note_el.find("rest") is None


def assess_omr_output(canonical_xml: str) -> QualityReport:
    """Assess the quality of OMR-derived MusicXML already accepted by the
    ingest pipeline, and decide whether it's usable.

    Walks every <part>/<measure> in the document counting sounded notes
    (a <note> with no direct <rest> child) and empty measures (a measure
    with none). Returns `acceptable=False` when recognition has clearly
    failed; otherwise `acceptable=True` with zero or more user-facing
    warning sentences about lower-confidence results.

    Malformed input is not expected here -- the ingest pipeline already
    validated and re-exported it -- but if `canonical_xml` somehow can't
    be parsed, this defers to that pipeline's judgment rather than
    second-guessing it, and returns a clean, unconditional pass.
    """
    try:
        root = ET.fromstring(canonical_xml)
    except ET.ParseError:
        return QualityReport(acceptable=True, warnings=[])

    total_measures = 0
    empty_measures = 0
    total_sounded_notes = 0
    part_measure_counts: list[int] = []

    for part_el in root.findall("part"):
        measures = part_el.findall("measure")
        part_measure_counts.append(len(measures))
        for measure_el in measures:
            total_measures += 1
            sounded_in_measure = sum(
                1 for note_el in measure_el.findall("note") if _is_sounded_note(note_el)
            )
            total_sounded_notes += sounded_in_measure
            if sounded_in_measure == 0:
                empty_measures += 1

    empty_fraction = (empty_measures / total_measures) if total_measures else 0.0

    if total_sounded_notes == 0:
        return QualityReport(acceptable=False, warnings=[])
    if (
        total_measures >= MIN_MEASURES_FOR_EMPTY_REJECT
        and empty_fraction > EMPTY_MEASURE_REJECT_FRACTION
    ):
        return QualityReport(acceptable=False, warnings=[])

    warnings: list[str] = []
    if empty_fraction > EMPTY_MEASURE_WARN_FRACTION:
        warnings.append(
            "Many measures came out empty — some notation was probably not recognized."
        )
    if len(set(part_measure_counts)) > 1:
        warnings.append(
            "Parts came out with different measure counts — some music may be missing."
        )
    if total_sounded_notes < MIN_SOUNDED_NOTES_WARN:
        warnings.append(
            "Very little notation was recognized — check the result carefully."
        )

    return QualityReport(acceptable=True, warnings=warnings)
