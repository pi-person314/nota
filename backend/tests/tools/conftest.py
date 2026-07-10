"""Fixtures for the notation-tool test suite.

This directory is self-contained: it does not import anything from
`backend/tests/conftest.py`. It configures the shared `nota.storage`
layer directly (the same entry point the standalone MCP server process
uses) against a fresh temporary database and score directory per test, and
provides a `make_score` factory that inserts a real Score row backed by one
of the fixture MusicXML files built by `musicxml_builders.py`.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from pathlib import Path

import music21 as m21
import pytest

from nota import db as db_module
from nota import models, storage

from .musicxml_builders import FIXTURE_BUILDERS

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@dataclass
class FixtureInfo:
    xml: str
    measure_count: int
    has_pickup: bool

try:
    import verovio  # noqa: F401

    VEROVIO_AVAILABLE = True
except ImportError:
    VEROVIO_AVAILABLE = False

requires_verovio = pytest.mark.skipif(not VEROVIO_AVAILABLE, reason="verovio is not installed")


@pytest.fixture(scope="session")
def fixture_xml_cache() -> dict[str, FixtureInfo]:
    """Build every fixture score once per test session and write it to
    `tests/tools/fixtures/<name>.musicxml`, returning {name: FixtureInfo}.

    Measure count / pickup metadata is computed directly from the
    in-memory music21 object the builder produced, rather than by
    re-parsing the serialized XML, so it's unaffected by any music21
    round-trip quirks.
    """
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    cache: dict[str, FixtureInfo] = {}
    for name, builder in FIXTURE_BUILDERS.items():
        score = builder()
        part = score.parts[0] if list(score.parts) else score
        measure_numbers = [m.number for m in part.getElementsByClass(m21.stream.Measure)]
        has_pickup = 0 in measure_numbers
        real_measures = [n for n in measure_numbers if n >= 1]
        measure_count = max(real_measures) if real_measures else 0

        path = FIXTURES_DIR / f"{name}.musicxml"
        score.write("musicxml", fp=str(path))
        cache[name] = FixtureInfo(
            xml=path.read_text(encoding="utf-8"),
            measure_count=measure_count,
            has_pickup=has_pickup,
        )
    return cache


@pytest.fixture
def storage_env(tmp_path):
    """Configure the shared storage layer against a fresh temp DB/dir for
    a single test, exactly as the standalone MCP server process would via
    DATABASE_URL/SCORE_STORAGE_DIR.
    """
    db_path = tmp_path / "test.db"
    storage_dir = tmp_path / "scores"
    storage.configure(
        database_url=f"sqlite:///{db_path}",
        score_storage_dir=str(storage_dir),
    )
    return storage_dir


@pytest.fixture
def make_score(storage_env, fixture_xml_cache):
    """Factory fixture: make_score("simple_4_4") -> score_id.

    Inserts a User + Score row backed by a fresh copy of the named
    fixture's MusicXML content, written into the test's isolated storage
    directory, and returns the new score's id.
    """

    def _make(fixture_name: str) -> str:
        info = fixture_xml_cache[fixture_name]

        user_id = uuid.uuid4().hex
        score_id = uuid.uuid4().hex
        file_path = os.path.join(str(storage_env), f"{score_id}.musicxml")

        with db_module.session_scope() as session:
            session.add(models.User(id=user_id, name="Test User", email=f"{user_id}@example.com"))
            session.add(
                models.Score(
                    id=score_id,
                    user_id=user_id,
                    name=fixture_name,
                    file_path=file_path,
                    measure_count=info.measure_count,
                    has_pickup=info.has_pickup,
                    parts_json="[]",
                    time_signatures_json="[]",
                )
            )

        os.makedirs(str(storage_env), exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(info.xml)

        return score_id

    return _make


@pytest.fixture
def read_score_xml(storage_env):
    """Return the live MusicXML text currently on disk for a score."""

    def _read(score_id: str) -> str:
        return storage.read_xml(score_id)

    return _read


@pytest.fixture
def undo_stack_labels(storage_env):
    """Return the labels currently on a score's undo stack, most recent
    first, without popping them (a peek, unlike storage.undo()).
    """

    def _labels(score_id: str) -> list[str]:
        with db_module.session_scope() as session:
            rows = (
                session.query(models.Snapshot)
                .filter_by(score_id=score_id, stack="undo")
                .order_by(models.Snapshot.id.desc())
                .all()
            )
            return [row.label for row in rows]

    return _labels


@pytest.fixture
def snapshot_count(storage_env):
    """Return how many entries are on a score's undo stack."""

    def _count(score_id: str) -> int:
        with db_module.session_scope() as session:
            return (
                session.query(models.Snapshot)
                .filter_by(score_id=score_id, stack="undo")
                .count()
            )

    return _count
