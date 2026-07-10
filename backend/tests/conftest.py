"""Shared pytest fixtures: an app wired to a temporary SQLite database and
a temporary score storage directory, plus a helper to create a real score
row + file for storage-layer tests.
"""

from __future__ import annotations

import os
import uuid

import pytest

from nota import create_app
from nota import db as db_module
from nota import models

SAMPLE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="4.0">
  <part-list>
    <score-part id="P1"><part-name>Violin</part-name></score-part>
  </part-list>
  <part id="P1">
    <measure number="1">
      <attributes>
        <divisions>1</divisions>
        <time><beats>4</beats><beat-type>4</beat-type></time>
      </attributes>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>4</duration><type>whole</type></note>
    </measure>
  </part>
</score-partwise>
"""


@pytest.fixture
def app(tmp_path):
    """A Flask app configured with an isolated temp SQLite DB and score
    storage directory, so tests never touch real data.
    """
    db_path = tmp_path / "test.db"
    storage_dir = tmp_path / "scores"

    env = {
        "SECRET_KEY": "test-secret-key",
        "DATABASE_URL": f"sqlite:///{db_path}",
        "SCORE_STORAGE_DIR": str(storage_dir),
        "MAX_UPLOAD_MB": "10",
        "PORT": "5001",
    }

    flask_app = create_app(env)
    flask_app.config.update(TESTING=True)
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def score_id(app):
    """Insert a User + Score row backed by a real MusicXML file in the
    temp storage directory, and return the score's id. Depends on `app`
    so the storage layer is already configured for the temp DB/dir.
    """
    cfg = app.config["NOTA_CONFIG"]

    user_id = uuid.uuid4().hex
    sid = uuid.uuid4().hex
    file_path = os.path.join(cfg.score_storage_dir, f"{sid}.musicxml")

    with db_module.session_scope() as session:
        session.add(
            models.User(id=user_id, name="Test User", email=f"{user_id}@example.com")
        )
        session.add(
            models.Score(
                id=sid,
                user_id=user_id,
                name="Test Score",
                file_path=file_path,
                measure_count=1,
                has_pickup=False,
                parts_json="[]",
                time_signatures_json="[]",
            )
        )

    os.makedirs(cfg.score_storage_dir, exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(SAMPLE_XML)

    return sid
