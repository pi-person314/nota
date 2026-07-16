"""Deterministic MusicXML fixture used by the eval dataset, plus the
storage/db setup an eval run needs.

The fixture is a single part, plain 4/4, sixteen measures, with a quarter
note on every beat -- large enough that "measure 200" and "bars 8 to 12"
style cases have real headroom (in range vs. clearly out of range) without
needing a different fixture per case. Every eval case gets its own fresh
copy of this score (own Score row, own file, own CommandLog) so cases never
see each other's conversation history unless a case explicitly chains
`setup_transcripts` through it.
"""

from __future__ import annotations

import json
import os
import uuid

from music21 import meter, metadata as m21_metadata, note, stream
from music21.musicxml.m21ToXml import GeneralObjectExporter

from nota import db as db_module
from nota import models
from nota import storage
from nota.config import Config, load_config

MEASURE_COUNT = 16
BEATS_PER_MEASURE = 4
PART_ID = "P1"
PART_NAME = "Violin"

# Deliberately unremarkable pitches -- nothing in the dataset cares what
# note is actually sounding, only that one starts on every beat.
_PITCH_CYCLE = ["C4", "D4", "E4", "F4", "G4", "A4", "B4", "C5"]


def build_fixture_musicxml(title: str = "Eval Fixture") -> bytes:
    """Serialize the sixteen-measure 4/4 fixture score to MusicXML bytes."""
    score = stream.Score()
    part = stream.Part()
    part.id = PART_ID
    part.partName = PART_NAME
    for measure_num in range(1, MEASURE_COUNT + 1):
        measure = stream.Measure(number=measure_num)
        if measure_num == 1:
            measure.append(meter.TimeSignature("4/4"))
        for beat in range(BEATS_PER_MEASURE):
            pitch = _PITCH_CYCLE[(measure_num + beat) % len(_PITCH_CYCLE)]
            measure.append(note.Note(pitch, quarterLength=1))
        part.append(measure)
    score.insert(0, part)
    score.metadata = m21_metadata.Metadata()
    score.metadata.title = title
    return GeneralObjectExporter(score).parse()


def configure_isolated_env(tmp_dir: str) -> Config:
    """Point the shared storage layer (db + score files) at a temporary
    directory for the duration of one eval run, the same way the Flask app
    factory does for a real request. Safe to call more than once per
    process -- `storage.configure`/`db_module.init_db` both re-initialize
    on every call.
    """
    db_path = os.path.join(tmp_dir, "eval.db")
    storage_dir = os.path.join(tmp_dir, "scores")
    env = {
        "SECRET_KEY": "nota-evals",
        "DATABASE_URL": f"sqlite:///{db_path}",
        "SCORE_STORAGE_DIR": storage_dir,
    }
    cfg = load_config(env)
    db_module.init_db(cfg.database_url)
    storage.configure(database_url=cfg.database_url, score_storage_dir=cfg.score_storage_dir)
    return cfg


def register_fresh_score(cfg: Config, name: str = "Eval Fixture") -> str:
    """Insert a User + Score row and write a fresh copy of the fixture file
    under `cfg.score_storage_dir`, returning the new score_id.
    """
    user_id = uuid.uuid4().hex
    score_id = uuid.uuid4().hex
    file_path = os.path.join(cfg.score_storage_dir, f"{score_id}.musicxml")

    with db_module.session_scope() as session:
        session.add(models.User(id=user_id, name="Eval User", email=f"{user_id}@evals.nota"))
        session.add(
            models.Score(
                id=score_id,
                user_id=user_id,
                name=name,
                file_path=file_path,
                measure_count=MEASURE_COUNT,
                has_pickup=False,
                parts_json=json.dumps([{"id": PART_ID, "name": PART_NAME}]),
                time_signatures_json=json.dumps([{"measure": 1, "ts": "4/4"}]),
            )
        )

    os.makedirs(cfg.score_storage_dir, exist_ok=True)
    with open(file_path, "wb") as f:
        f.write(build_fixture_musicxml(name))

    return score_id
