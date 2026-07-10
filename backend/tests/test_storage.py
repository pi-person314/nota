"""Tests for the shared storage layer: undo/redo snapshot behavior."""

from __future__ import annotations

from nota import db as db_module
from nota import models, storage


def test_undo_on_empty_stack_returns_none(score_id):
    assert storage.undo(score_id) is None


def test_redo_on_empty_stack_returns_none(score_id):
    assert storage.redo(score_id) is None


def test_snapshot_undo_redo_round_trip(score_id):
    original = storage.read_xml(score_id)

    storage.save_snapshot(score_id, "add_dynamic f m12 b1")
    storage.write_xml(score_id, original + "<!-- mutated -->")
    mutated = storage.read_xml(score_id)
    assert mutated != original

    undo_label = storage.undo(score_id)
    assert undo_label == "add_dynamic f m12 b1"
    assert storage.read_xml(score_id) == original  # byte-equivalent restore

    redo_label = storage.redo(score_id)
    assert redo_label == "add_dynamic f m12 b1"
    assert storage.read_xml(score_id) == mutated  # byte-equivalent restore


def test_new_snapshot_clears_redo_stack(score_id):
    original = storage.read_xml(score_id)

    storage.save_snapshot(score_id, "step1")
    storage.write_xml(score_id, original + "<!-- step1 -->")

    storage.undo(score_id)
    assert storage.read_xml(score_id) == original

    # A fresh mutation should wipe out the redo entry created by the undo above.
    storage.save_snapshot(score_id, "step2")
    storage.write_xml(score_id, original + "<!-- step2 -->")

    assert storage.redo(score_id) is None


def test_51st_snapshot_evicts_oldest(score_id):
    original = storage.read_xml(score_id)

    for i in range(51):
        storage.save_snapshot(score_id, f"step{i}")
        storage.write_xml(score_id, f"{original}<!-- step{i} -->")

    with db_module.session_scope() as session:
        undo_count = (
            session.query(models.Snapshot)
            .filter_by(score_id=score_id, stack="undo")
            .count()
        )
    assert undo_count == 50  # capped, oldest (step0) evicted

    labels = []
    for _ in range(50):
        label = storage.undo(score_id)
        assert label is not None
        labels.append(label)

    # The 51st undo has nothing left: the entry that would have restored
    # to the pre-loop original state (labeled "step0") was evicted.
    assert storage.undo(score_id) is None
    assert labels[-1] == "step1"
    assert storage.read_xml(score_id) == f"{original}<!-- step0 -->"
