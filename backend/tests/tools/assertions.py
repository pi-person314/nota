"""Shared assertion helpers for the notation-tool test suite.

Not a test module itself (no `test_` prefix) so pytest won't try to
collect it directly; imported by the actual test files.
"""

from __future__ import annotations

import music21 as m21

from nota import storage

try:
    import verovio

    _VEROVIO_TOOLKIT = verovio.toolkit()
except ImportError:
    _VEROVIO_TOOLKIT = None


def assert_success(result: dict) -> dict:
    """Assert a tool call succeeded and return it (for chaining)."""
    assert result["success"] is True, result.get("message")
    assert isinstance(result["changed_element_ids"], list)
    assert isinstance(result["summary"], str) and result["summary"]
    return result


def assert_error(result: dict, code: str) -> dict:
    """Assert a tool call failed with the given error code and return it."""
    assert result["success"] is False, result
    assert result["error_code"] == code, result
    assert isinstance(result["message"], str) and result["message"]
    return result


def assert_round_trips(score_id: str) -> str:
    """Assert the score currently on disk re-parses cleanly with music21.
    Returns the raw XML text for further inspection.
    """
    xml = storage.read_xml(score_id)
    reparsed = m21.converter.parse(xml.encode("utf-8"), format="musicxml")
    assert reparsed is not None
    assert list(reparsed.parts) or isinstance(reparsed, m21.stream.Part)
    return xml


def assert_ids_present(score_id: str, changed_element_ids: list[str]) -> str:
    """Assert every id in `changed_element_ids` literally appears as an
    xml:id (serialized by music21 as a plain `id` attribute) in the score's
    current on-disk XML. This is the regression check for the frontend
    change-highlighting contract.
    """
    xml = storage.read_xml(score_id)
    for element_id in changed_element_ids:
        assert f'id="{element_id}"' in xml, f"{element_id} missing from serialized XML"
    return xml


def assert_renders_with_verovio(score_id: str) -> None:
    """If verovio is installed, assert it can load and render the score's
    current on-disk XML to SVG without raising and without an empty
    result. No-op (not a skip) when verovio isn't installed — callers that
    want a skip should use the `requires_verovio` marker from conftest
    instead so it's visible in the test report.
    """
    if _VEROVIO_TOOLKIT is None:
        return
    xml = storage.read_xml(score_id)
    loaded = _VEROVIO_TOOLKIT.loadData(xml)
    assert loaded, "verovio failed to load the rendered MusicXML"
    svg = _VEROVIO_TOOLKIT.renderToSVG(1)
    assert svg and "<svg" in svg
